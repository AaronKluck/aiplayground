from playwright.sync_api import Browser, Page, Playwright, sync_playwright
from playwright._impl._errors import TimeoutError as PlaywrightTimeoutError
from playwright_stealth import stealth_sync
import random
import time
import threading
import traceback
from queue import Queue
from urllib.parse import urlparse, urljoin, ParseResult
from urllib.robotparser import RobotFileParser
from typing import Tuple

from aiplay.util.download import download_file, download_rendered

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

    def init_robots(self):
        try:
            rendered = download_rendered(self.robots_url)
            self.robots.parse(rendered.splitlines())
        except Exception as e:
            self.robots = RobotFileParser()

    def create_browser(self, p: Playwright, url: str) -> Browser:
        # Even with "stealth" mode, some sites may block one browser profile
        # while allowing another. Thus, try all three and stick with whatever
        # works first.
        for browser_type in [p.chromium, p.firefox, p.webkit]:
            browser = browser_type.launch(headless=True)
            try:
                page = self.browse_page(browser, url)

                # There may be other indicators of access denial, but these
                # are common.
                if "Access Denied" in page.title() or "Access Denied" in page.content():
                    browser.close()
                    continue
                return browser
            except:
                browser.close()
                raise
        raise ValueError("Failed to get rendered HTML from any browser type")

    def browse_page(self, browser: Browser, url: str) -> Page:
        page = browser.new_page()
        stealth_sync(page)
        page.goto(url, timeout=15000, wait_until="networkidle")
        return page

    def robot_allowed(self, url: str) -> bool:
        return self.robots.can_fetch(url, "*")

    def normalize_url(self, url: str) -> Tuple[str, bool]:
        if not url.startswith("http:") and not url.startswith("https:"):
            return url, False
        parsed: ParseResult = urlparse(url)
        norm_url: str = parsed._replace(fragment="").geturl()
        return norm_url, parsed.netloc in ("", self.domain) and self.robot_allowed(
            norm_url
        )

    def add_to_queue(self, norm_url: str):
        with self.condition:
            if norm_url not in self.visited:
                self.visited.add(norm_url)
                self.queue.put(norm_url)
                self.condition.notify_all()
                return True  # First time seen
        return False  # Already visited

    def worker(self, worker_id: int):
        with sync_playwright() as p:
            browser = self.create_browser(p, self.base_url)
            try:
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
                        self.process_url(worker_id, browser, url)

                        # Random sleep to avoid overwhelming the server. Yes,
                        # this slows us down, and yes, it's a bit counter-
                        # intuitive, given that we're also spawning threads,
                        # but it helps illustrate scale. A "real" product would
                        # use a more sophisticated approach to avoid hitting
                        # *specific* servers too often, such that the threads
                        # would intermingle their requests.
                        time.sleep(random.uniform(0.25, 0.5))
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
            finally:
                browser.close()

    def process_url(self, worker_id: int, browser: Browser, url: str) -> None:
        if url.lower().endswith(DOC_EXTENSIONS):
            data, mime = download_file(url)
            self.process_document(url, data, mime)
            return

        page = self.browse_page(browser, url)
        print(f"\n== {worker_id} Crawling: {url} ==")
        print(f"Title: {page.title()}")

        links = page.query_selector_all("a[href]")
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

    def process_document(self, url: str, data: bytes, mime: str) -> None:
        # Placeholder for document processing logic
        print(f"Processing document: {url} with MIME type: {mime}")

    def start(self) -> None:
        self.init_robots()

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

        print("Crawling complete.")
