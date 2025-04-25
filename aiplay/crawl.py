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
    delete_stale_pages,
    list_pages_for_site,
    update_page_error,
    update_page_hash,
    upsert_page,
)
from aiplay.db.schema import create_schema
from aiplay.db.site import upsert_site
from aiplay.db.types import Link, Page, Site
from aiplay.ai.inspect import inspect_links, KEYWORDS, LinkKeywords
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
    """
    This serves as both the entrypoint to the crawler application as well as
    the main logic behind each worker thread. In a real product, I would break
    this down. The workers would be separated, and I might break apart the
    static configs from the shared, mutable state.
    """

    def __init__(
        self,
        seed_url: str,
        workers: int,
        stale_hours: int,
        *,
        max_count: int | None = None,
        max_components: int | None = None,
        max_depth: int | None = None,
        max_params: int | None = None,
    ) -> None:
        self.seed_url = seed_url
        self.domain = urlparse(seed_url).netloc
        self.scheme = urlparse(seed_url).scheme
        self.base_url = f"{self.scheme}://{self.domain}"

        self.robots_url = f"{self.base_url}/robots.txt"
        self.robots = RobotFileParser()
        self.robots.set_url(self.robots_url)

        # New DB records will include this time
        self.crawl_time = datetime.now()

        # Populated during init_db()
        self._site: Site | None = None
        self.cache: dict[str, Page] = {}

        # These set of variables can be mutated by any worker thread
        self.queue: Queue[tuple[str, int]] = Queue()
        self.visited: set[str] = set()
        self.condition = threading.Condition()
        self.active_workers = 0
        self.count = 0

        # Optional configurations
        self.stale_hours = stale_hours
        self.max_workers = workers
        self.max_count = max_count
        self.max_components = max_components
        self.max_depth = max_depth
        self.max_params = max_params

    def init_robots(self):
        """
        Initialize the robots.txt parser.
        """
        try:
            rendered = download_rendered(self.robots_url)
            self.robots.parse(rendered.splitlines())
        except:
            self.robots = RobotFileParser()

    def init_db(self):
        """
        Create the DB schema if it doesn't exist, create the site record if it
        doesn't exist, and load the pages for the site into the cache.
        """
        create_schema()
        with Transaction() as db:
            self.site = upsert_site(
                db, Site(url=self.base_url, crawl_time=self.crawl_time)
            )
            pages = list_pages_for_site(db, self.site.id)

        for page in pages:
            self.cache[page.url] = page

    def robot_allowed(self, url: str) -> bool:
        return self.robots.can_fetch(url, "*")

    def allowed_to_crawl(self, url: str) -> bool:
        """
        Checks whether a link we encountered should be added to the queue.
        """
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
            # unlikely to be more than a few clicks away from the home page, so
            # we don't need to crawl too deep. This avoids going in circles when
            # the site has links that merely adjust the view of a page (though
            # that particular edge case is also handled by some other optional
            # heuristics).
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
        """
        Entrypoint of each worker thread.
        """
        with sync_playwright() as p:
            browser_type, _ = determine_browser_type(p, self.base_url)
            with BrowserCtx(browser_type) as browser:
                while True:
                    # Wait for work to be available
                    with self.condition:
                        # An empty queue but active workers means work might
                        # soon be produced.
                        while self.queue.empty() and self.active_workers > 0:
                            self.condition.wait()

                        # Once the queue is exhausted and no workers are active,
                        # we can start shutting down.
                        if self.queue.empty() and self.active_workers == 0:
                            self.condition.notify_all()  # Wake any other waiting threads
                            print(f"Exiting worker thread {worker_id}")
                            break  # No work and no active threads → done

                        # Otherwise, we have work to do. Get the next URL and
                        # increment the active worker count.
                        url, depth = self.queue.get()
                        self.active_workers += 1

                    try:
                        print(f"{worker_id}: == Crawling: {url} ==")
                        self.process_url(worker_id, browser, url, depth)
                    except PlaywrightError as e:
                        print(f"{worker_id}: Error reading/rendering {url}: {e}")
                    except Exception as e:
                        print(f"{worker_id}: Error crawling {url}: {e}")
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
            # At one time, I thought I might have the AI process documents too,
            # but once I switched to pre-extracting links, this stretch goal
            # became a much bigger set of work, so I decided to skip it.
            print(f"{worker_id}: Skipping document URL: {url}")
            return

        try:
            # Render a page with a fake browser, then extract the links from it.
            # These links service two purposes. First, they are what's hashed
            # and stored in the page's databae record, so that on subsequent
            # crawls we can check for changes. Second, they are passed to the AI
            # for inspection and keyword extraction.
            with PageCtx(browser, url) as ppage:
                content = ppage.content()
                links = extract_links(self.base_url, content, self.max_params)
                hash = sha3_256(json.dumps(links).encode()).hexdigest()
        except Exception as e:
            # If we can't render the page, we still want to record it in the
            # database with an empty hash and the error message.
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

        # On successful render, insert with an empty hash. We'll update the hash
        # later if all goes well. The reason we do this now is that we need a
        # page ID to insert the links with.
        with Transaction() as db:
            db_page = upsert_page(
                db,
                Page(
                    site_id=self.site.id,
                    url=url,
                    hash="",
                    crawl_time=self.crawl_time,
                ),
            )

        # Check whether we already had the page. We don't need to update teh
        # cache ever because we'll never visit the page again this run.
        existing_page = self.cache.get(url)

        try:
            # Either skip the page (if unchanged) or process its links
            if existing_page and existing_page.hash == hash:
                print(f"{worker_id}: No changes detected for {url}")
            else:
                self.process_links(db_page.id, links)

            # Update the page hash so that next time we crawl it, we can
            # check for changes.
            with Transaction() as db:
                update_page_hash(db, db_page.id, hash)
        except Exception as e:
            # If we can't proces the links, record the error
            with Transaction() as db:
                update_page_error(db, db_page.id, str(e))

        # "Recurse" into the links we found
        for link in links:
            if self.allowed_to_crawl(link["url"]):
                self.add_to_queue(link["url"], depth)

    def process_links(self, page_id: int, links: list[ExtractedLink]) -> None:
        # If we didn't find any links we might care about, short-circuit
        if not links:
            return

        # Ask the AI to inspect the links and map to keywords
        kw_links = inspect_links(links)

        # Determine score for each link and build the DB records
        db_links: list[Link] = []
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

    def keyword_ranking(self, kw_link: LinkKeywords) -> tuple[str, float]:
        # Apply weights to the keywords, some of which are more important than
        # others.
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

        # Sort them by score, high to low
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
