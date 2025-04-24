from datetime import datetime, timedelta
from hashlib import sha3_256
import json
from playwright.sync_api import (
    Browser,
    sync_playwright,
)
from playwright._impl._errors import Error as PlaywrightError
import threading
import traceback
from queue import Queue
from urllib.parse import urlparse, ParseResult
from urllib.robotparser import RobotFileParser

from aiplay.db.context import Transaction
from aiplay.db.link import upsert_link, delete_stale_links
from aiplay.db.page import (
    list_pages_for_site,
    update_page_error,
    upsert_page,
    delete_stale_pages,
)
from aiplay.db.schema import create_schema
from aiplay.db.site import upsert_site
from aiplay.db.types import Link, Page, Site
from aiplay.ai.inspect import inspect_links, KEYWORDS, LinkKeywords
from aiplay.ai.types import AIModel
from aiplay.util.containers import ThreadSafeDict
from aiplay.util.download import download_rendered
from aiplay.util.html import (
    BrowserCtx,
    determine_browser_type,
    extract_links,
    ExtractedLink,
    PageCtx,
)

DOC_EXTENSIONS = (".pdf", ".csv", ".xml", ".md", ".txt", ".rtf")
KW_DELIM = ";"


class Crawler:
    def __init__(self, seed_url: str):
        self.seed_url = seed_url
        self.domain = urlparse(seed_url).netloc
        self.scheme = urlparse(seed_url).scheme
        self.base_url = f"{self.scheme}://{self.domain}"

        self.queue: Queue[tuple[str, int]] = Queue()
        self.visited: set[str] = set()
        self.condition = threading.Condition()
        self.active_workers = 0

        self.robots_url = f"{self.base_url}/robots.txt"
        self.robots = RobotFileParser()
        self.robots.set_url(self.robots_url)

        self._site: Site | None = None
        self.crawl_time = datetime.now()

        self.cache = ThreadSafeDict[str, Page]()
        self.count = 0

        self.ai_model = AIModel.OPENAI

        self.stale_hours = 24
        self.max_workers = 6

        # These are used to heuristically limit how we crawl. For now, they're
        # hardcoded here. Will make them configurable later.
        self.max_count: int | None = None
        self.max_components: int | None = 10
        self.max_depth: int | None = 5

    def init_robots(self):
        try:
            rendered = download_rendered(self.robots_url)
            self.robots.parse(rendered.splitlines())
        except:
            self.robots = RobotFileParser()

    def init_db(self):
        create_schema()
        with Transaction() as db:
            self.site = upsert_site(
                db, Site(url=self.base_url, crawl_time=self.crawl_time)
            )
            pages = list_pages_for_site(db, self.site.id)

        with self.cache as cache:
            for page in pages:
                cache[page.url] = page

    def robot_allowed(self, url: str) -> bool:
        return self.robots.can_fetch(url, "*")

    def allowed_to_crawl(self, url: str) -> bool:
        if not self.robot_allowed(url):
            return False

        parsed: ParseResult = urlparse(url)
        if parsed.netloc != self.domain:
            return False

        # Heuristically prune URLs with too many components. Anything important
        # is likely to be navigable with a few clicks from the home page, so
        # once down in the weeds, there are unlikely to be useful links that
        # are not already in the queue. The reason to limit based on component
        # count is because many times the last few components are really just
        # parameters for a previous component. For example:
        # https://bozeman.net/services/advanced-components/basic-pages/city-of-bozeman-events/-curdate-4-3-2025/-sortn-EName/-sortd-asc/-toggle-next30days
        # In this case, the last 3 components are just viewing parameters.
        if self.max_components is not None:
            num_components = len(parsed.path.lstrip("/").rstrip("/").split("/"))
            if num_components > self.max_components:
                return False

        return True

    def add_to_queue(self, norm_url: str, depth: int):
        with self.condition:
            # A non-None limit artificially stops processing when hit
            if self.max_count and self.count >= self.max_count:
                return False

            # Heuristically limit the depth of the crawl. Important links are
            # unlinkely to be more than a few clicks away from the home page, so
            # we don't need to crawl too deep. This avoids going in circles when
            # the site has links that merely adjust the view of a page.
            if self.max_depth and depth > self.max_depth:
                return False

            if norm_url not in self.visited:
                self.visited.add(norm_url)
                self.queue.put((norm_url, depth + 1))
                self.condition.notify_all()
                self.count += 1
                return True  # First time seen
        return False  # Already visited

    def worker(self, worker_id: int) -> None:
        with sync_playwright() as p:
            browser_type = determine_browser_type(p, self.base_url)
            with BrowserCtx(browser_type) as browser:
                while True:
                    with self.condition:
                        while self.queue.empty() and self.active_workers > 0:
                            self.condition.wait()

                        if self.queue.empty() and self.active_workers == 0:
                            self.condition.notify_all()  # Wake any other waiting threads
                            print(f"Exiting worker thread {worker_id}")
                            break  # No work and no active threads → done

                        url, depth = self.queue.get()
                        self.active_workers += 1

                    try:
                        print(f"== {worker_id} Crawling: {url} ==")
                        self.process_url(worker_id, browser, url, depth)
                    except PlaywrightError as e:
                        print(f"Error reading/rendering {url}: {e}")
                    except Exception as e:
                        print(f"Error crawling {url}: {e}")
                        traceback.print_exc()

                    finally:
                        with self.condition:
                            self.queue.task_done()
                            self.active_workers -= 1
                            self.condition.notify_all()

    def process_url(
        self, worker_id: int, browser: Browser, url: str, depth: int
    ) -> None:
        if url.lower().endswith(DOC_EXTENSIONS):
            print("Skipping document URL:", url)
            # data, mime = download_file(url)
            # self.process_document(url, data, mime)
            return

        try:
            with PageCtx(browser, url) as ppage:
                content = ppage.content()
                links = extract_links(self.base_url, content)
                hash = sha3_256(json.dumps(links).encode()).hexdigest()
        except Exception as e:
            with Transaction() as db:
                db_page = upsert_page(
                    db,
                    Page(
                        site_id=self.site.id,
                        url=url,
                        hash="",
                        crawl_time=self.crawl_time - timedelta(seconds=1),
                        error=str(e),
                    ),
                )
            raise

        with Transaction() as db:
            db_page = upsert_page(
                db,
                Page(
                    site_id=self.site.id,
                    url=url,
                    hash=hash,
                    crawl_time=self.crawl_time,
                ),
            )

        # Check whether we already had the page, then set the latest
        existing_page = self.cache.get(url)
        self.cache.set(url, db_page)

        if existing_page and existing_page.hash == hash:
            print(f"{worker_id}: No changes detected for {url}")
        else:
            try:
                self.process_links(db_page.id, links)
            except Exception as e:
                # Not really necessary to update our cached page, as we aren't
                # going to touch it again.
                with Transaction() as db:
                    update_page_error(db, db_page.id, str(e))

        for link in links:
            if self.allowed_to_crawl(link["url"]):
                self.add_to_queue(link["url"], depth)

    def process_links(self, page_id: int, links: list[ExtractedLink]) -> None:
        # If we didn't find any links we might care about, short-circuit
        if not links:
            return

        db_links: list[Link] = []
        kw_links = inspect_links(self.ai_model, links)
        for kw_link in kw_links:
            kw_str, score = self.keyword_ranking(kw_link)
            # If the score is 0, we don't want to keep it. (Often means a
            # link was returned with no keywords.)
            if score:
                db_links.append(
                    Link(
                        site_id=self.site.id,
                        page_id=page_id,
                        url=kw_link.url,
                        text=kw_link.text,
                        score=score,
                        keywords=kw_str,
                        crawl_time=self.crawl_time,
                    )
                )

        with Transaction() as db:
            for db_link in db_links:
                upsert_link(db, db_link)

    def process_document(self, url: str, data: bytes, mime: str) -> None:
        # Placeholder for document processing logic
        print(f"Processing document: {url} with MIME type: {mime}")

    def keyword_ranking(self, kw_link: LinkKeywords) -> tuple[str, float]:
        # Sort them by score, high to low
        kw_sorted: list[tuple[str, float]] = []
        for k, v in kw_link.keywords.items():
            # Sometimes the AI produces its own keywords. Some are topical,
            # but others are not. We kick those responses back and ask the AI
            # to try agin, but if they *still* come back with extra keywords,
            # just give them a low weight rather than the configured one.
            if k in KEYWORDS:
                kw_sorted.append((k, v * KEYWORDS[k]))
            else:
                kw_sorted.append((k, v * 0.25))
        kw_sorted.sort(key=lambda x: x[1], reverse=True)

        # The string looks like ;foo;bar;cat;dog;
        kw_str = KW_DELIM + KW_DELIM.join([kw[0] for kw in kw_sorted]) + KW_DELIM

        # The highest score gets its full value, the next highest is worth half,
        # the next is worth a quarter, et cetera. Even with an infinite number
        # of keywords, the total score will converge to (but never reach) 2.0.
        scores = [kw[1] for kw in kw_sorted]
        total_score = 0.0
        for i, score in enumerate(scores):
            total_score += score / (2**i)

        return kw_str, total_score

    @property
    def site(self) -> Site:
        """
        This is a property because it doesn't exist after __init__, but rather
        is added later. I didn't want to make every usage check for whether it
        was None or not (and I'm a stickler for checking optionals), so the
        property does it instead. The check is an assert because if it fails,
        that's a programming error, not a runtime error.
        """
        assert self._site is not None, "site not initialized"
        return self._site

    @site.setter
    def site(self, site: Site) -> None:
        self._site = site

    def run(self) -> None:
        self.init_robots()
        self.init_db()

        self.add_to_queue(self.seed_url, 0)

        threads: list[threading.Thread] = []
        for i in range(self.max_workers):
            t = threading.Thread(target=self.worker, args=(i,))
            t.start()
            threads.append(t)

        # Wait for the queue to be empty
        self.queue.join()

        # Join all threads
        for t in threads:
            t.join()

        # Remove stale pages and links from the database
        with Transaction() as db:
            stale_threshold = self.crawl_time - timedelta(hours=self.stale_hours)
            delete_stale_pages(db, stale_threshold)
            delete_stale_links(db, stale_threshold)

        print("Crawling complete.")
