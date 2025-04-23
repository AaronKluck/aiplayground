from playwright.sync_api import Browser, BrowserType, Page as PlayPage, Playwright
from playwright_stealth import stealth_sync


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


def determine_browser_type(p: Playwright, url: str) -> BrowserType:
    """
    Even with "stealth" mode, some sites may block one browser profile while
    allowing another. Thus, try all three and stick with whatever works first.
    """
    for browser_type in [p.chromium, p.firefox, p.webkit]:
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
