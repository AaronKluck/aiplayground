from bs4 import BeautifulSoup, Tag
from playwright.sync_api import Browser, BrowserType, Page as PlayPage, Playwright
from playwright_stealth import stealth_sync
from typing import TypedDict


class BrowserCtx:
    def __init__(self, browser_type: BrowserType) -> None:
        self._browser = browser_type.launch(headless=True)

    def __enter__(self) -> Browser:
        return self._browser

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._browser.close()


class PageCtx:
    def __init__(self, browser: Browser, url: str) -> None:
        self._page = browser.new_page()
        stealth_sync(self._page)
        self._page.goto(url, timeout=15000, wait_until="networkidle")

    def __enter__(self) -> PlayPage:
        return self._page

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._page.close()


class ExtractedLink(TypedDict):
    url: str
    text: str


def determine_browser_type(p: Playwright, url: str) -> BrowserType:
    """
    Even with "stealth" mode, some sites may block one browser profile while
    allowing another. Thus, try all three and stick with whatever works first.
    """
    for browser_type in [p.chromium, p.webkit, p.firefox]:
        with BrowserCtx(browser_type) as browser:
            with PageCtx(browser, url) as ppage:
                # There may be other indicators of access denial, but these
                # are common.
                if (
                    "Access Denied" in ppage.title()
                    or "Access Denied" in ppage.content()
                ):
                    browser.close()
                    continue
            return browser_type
    raise ValueError("Failed to get rendered HTML from any browser type")


def clean_page(page: PlayPage) -> None:
    tags_to_remove = [
        "script",
        "img",
        "style",
    ]
    tag_list = ",".join(tags_to_remove)
    js = f"""
        // Remove script/img/etc. tags
        for (const el of document.querySelectorAll("{tag_list}")) {{
            el.remove();
        }}

        // Remove elements with the [hidden] attribute
        for (const el of document.querySelectorAll("[hidden]")) {{
            el.remove();
        }}

        // Remove elements with type="hidden"
        for (const el of document.querySelectorAll('[type="hidden"]')) {{
            el.remove();
        }}

        // Remove <a> elements with no href
        for (const el of document.querySelectorAll("a:not([href])")) {{
            el.remove();
        }}

        // Remove <a> elements with useless href values
        for (const el of document.querySelectorAll("a[href]")) {{
            const href = el.getAttribute("href").trim().toLowerCase();
            if (href.startsWith("#") || href.startsWith("javascript:")) {{
                el.remove();
            }}
        }}

        // Remove id attribute from all elements
        for (const el of document.querySelectorAll("[id]")) {{
            el.removeAttribute("id");
        }}
    """
    page.evaluate(js)


def extract_links(base_url: str, content: str) -> list[ExtractedLink]:
    soup = BeautifulSoup(content, "html.parser")
    links: list[ExtractedLink] = []
    for a in soup.find_all("a", href=True):
        assert isinstance(a, Tag)
        text = a.get_text(" ", strip=True)
        href = a["href"]

        # Skip empty, anchor-only, or junk links
        if not isinstance(href, str) or href.startswith("#") or not text:
            continue

        # Make relative links absolute
        if href.startswith("/"):
            href = base_url + href

        # Skip non-HTTP links
        if not href.startswith("http") and not href.startswith("https"):
            continue

        # Remove query and fragment for normalization. This removes a whole ton
        # of effective duplicates. The fragment removal is safest, but the query
        # removal is more aggressive, since a page might have different content
        # based on the query string. In practice, however, this seems like a
        # reasonable tradeoff, given how many useless duplicates we see.
        last_slash = href.rfind("/")
        last_hash = href.rfind("#")
        if last_hash > last_slash:
            href = href[:last_hash]
        last_question = href.rfind("?")
        if last_question > last_slash:
            href = href[:last_question]

        if href and text:
            links.append({"url": href, "text": text})
    return links
