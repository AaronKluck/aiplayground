from datetime import datetime
from hashlib import sha3_256
from playwright.sync_api import (
    Browser,
    sync_playwright,
)
from playwright._impl._errors import TimeoutError as PlaywrightTimeoutError
import threading
import traceback
from queue import Queue
from urllib.parse import urlparse, urljoin, ParseResult
from urllib.robotparser import RobotFileParser

from aiplay.db.context import Transaction
from aiplay.db.link import delete_stale_links
from aiplay.db.page import list_pages_for_site, upsert_page, delete_stale_pages
from aiplay.db.site import upsert_site
from aiplay.db.types import Site, Page
from aiplay.util.containers import ThreadSafeDict
from aiplay.util.download import download_file, download_rendered
from aiplay.util.html import BrowserCtx, clean_page, determine_browser_type, PageCtx

NUM_WORKERS = 8

DOC_EXTENSIONS = (".pdf", ".csv", ".xml", ".md", ".txt", ".rtf")


class Crawler:
    def __init__(self, seed_url):
        self.seed_url = seed_url
        self.domain = urlparse(seed_url).netloc
        self.scheme = urlparse(seed_url).scheme
        self.base_url = f"{self.scheme}://{self.domain}"

        self.queue: Queue[str] = Queue()
        self.visited = set()
        self.condition = threading.Condition()
        self.active_workers = 0

        self.robots_url = f"{self.base_url}/robots.txt"
        self.robots = RobotFileParser()
        self.robots.set_url(self.robots_url)

        self._site: Site | None = None
        self.crawl_time = datetime.now()

        self.cache = ThreadSafeDict[str, Page]()

        self.count = 0

    def init_robots(self):
        try:
            rendered = download_rendered(self.robots_url)
            self.robots.parse(rendered.splitlines())
        except:
            self.robots = RobotFileParser()

    def init_db(self):
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

    def normalize_url(self, url: str) -> tuple[str, bool]:
        if not url.startswith("http:") and not url.startswith("https:"):
            return url, False
        parsed: ParseResult = urlparse(url)

        # Remove query and fragment for normalization. This removes a whole ton
        # of effective duplicates. The fragment removal is safest, but the query
        # removal is more aggressive, since a page might have different content
        # based on the query string. In practice, however, this seems like a
        # reasonable tradeoff, given how many useless duplicates we see.
        norm_url: str = parsed._replace(query="", fragment="").geturl()
        return norm_url, parsed.netloc in ("", self.domain) and self.robot_allowed(
            norm_url
        )

    def add_to_queue(self, norm_url: str):
        with self.condition:
            # Remove this limit when ready for futher testing
            if self.count > 10:
                return False
            if norm_url not in self.visited:
                self.visited.add(norm_url)
                self.queue.put(norm_url)
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

                        url = self.queue.get()
                        self.active_workers += 1

                    try:
                        print(f"== {worker_id} Crawling: {url} ==")
                        self.process_url(worker_id, browser, url)
                    except PlaywrightTimeoutError:
                        print(f"Timeout while crawling {url}")
                    except Exception as e:
                        print(f"Error crawling {url}: {e}")
                        traceback.print_exc()

                    finally:
                        with self.condition:
                            self.queue.task_done()
                            self.active_workers -= 1
                            self.condition.notify_all()

    def process_url(self, worker_id: int, browser: Browser, url: str) -> None:
        if url.lower().endswith(DOC_EXTENSIONS):
            data, mime = download_file(url)
            self.process_document(url, data, mime)
            return

        with PageCtx(browser, url) as ppage:
            orig_content = ppage.content()
            clean_page(ppage)
            clean_content = ppage.content()

            hash = sha3_256(clean_content.encode()).hexdigest()

            existing_page = self.cache.get(url)
            if existing_page and existing_page.hash == hash:
                print(f"{worker_id}: No changes detected for {url}")
            else:
                self.process_page(url, orig_content)

            links = ppage.query_selector_all("a[href]")
            for link in links:
                href = link.get_attribute("href")
                text = link.inner_text().strip()
                if not href:
                    continue

                norm_url, is_allowed = self.normalize_url(urljoin(url, href))
                if is_allowed:
                    first_seen = self.add_to_queue(norm_url)
                    if first_seen:
                        print(f"{worker_id}: [{text}] -> {norm_url}")

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
            self.cache.set(url, db_page)

    def process_page(self, url: str, content: str) -> None:
        # Placeholder for HTML processing logic
        print(f"Inspecting HTML content from: {url}")

    def process_document(self, url: str, data: bytes, mime: str) -> None:
        # Placeholder for document processing logic
        print(f"Processing document: {url} with MIME type: {mime}")

    @property
    def site(self) -> Site:
        assert self._site is not None, "site not initialized"
        return self._site

    @site.setter
    def site(self, site: Site) -> None:
        self._site = site

    def run(self) -> None:
        self.init_robots()
        self.init_db()

        self.add_to_queue(self.seed_url)

        threads: list[threading.Thread] = []
        for i in range(NUM_WORKERS):
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
            delete_stale_pages(db, self.crawl_time)
            delete_stale_links(db, self.crawl_time)

        print("Crawling complete.")
