from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync
import requests
from typing import Tuple


def download_file(url: str) -> Tuple[bytes, str]:
    """Download a file from a URL."""

    response = requests.get(url)
    if response.status_code != 200:
        raise ValueError(f"Failed to download file: {response.status_code}")
    if "Content-Type" not in response.headers:
        raise ValueError("No Content-Type header in response")
    return response.content, response.headers["Content-Type"]


def download_rendered(url: str) -> str:
    with sync_playwright() as p:
        for browser_type in [p.chromium, p.firefox, p.webkit]:
            browser = browser_type.launch(headless=True)
            try:
                page = browser.new_page()
                stealth_sync(page)
                page.goto(url, wait_until="networkidle")

                # Get full rendered HTML
                rendered_html = page.content()
                if "<h1>Access Denied</h1>" in rendered_html:
                    print(f"Access Denied for {browser_type.name}")
                    continue
                return rendered_html
            finally:
                browser.close()
    raise ValueError("Failed to get rendered HTML from any browser type")
