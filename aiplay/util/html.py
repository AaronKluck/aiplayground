from bs4 import BeautifulSoup, Tag
import json
from playwright.sync_api import Browser, BrowserType, Page as PlayPage, Playwright
from playwright_stealth import stealth_sync
import re
from typing import Any, TypedDict
from urllib.parse import urljoin


class BrowserCtx:
    """
    Context manager for a Playwright browser instance; cleans up after itelf.
    """

    def __init__(self, browser_type: BrowserType) -> None:
        self._browser = browser_type.launch(headless=True)

    def __enter__(self) -> Browser:
        return self._browser

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._browser.close()


class PageCtx:
    """
    Context manager for a Playwright page instance; cleans up after itelf.
    """

    def __init__(self, browser: Browser, url: str) -> None:
        self._page = browser.new_page()
        stealth_sync(self._page)
        self._page.goto(url, timeout=15000, wait_until="networkidle")

    def __enter__(self) -> PlayPage:
        return self._page

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self._page.close()


class ExtractedLink(TypedDict):
    """
    Each link we extract from a page has a URL and the visible text that the
    user can click on. I had experimented with including neary contextual text
    as well, but I'm not a DOM manipulation expert, and it was too inconsistent.
    """

    url: str
    text: str


def determine_browser_type(p: Playwright, url: str) -> tuple[BrowserType, str]:
    """
    Even with "stealth" mode, some sites may block one browser profile while
    allowing another. Thus, try all three and stick with whatever works first.
    Also returns the successfully rendered page content.
    """
    for browser_type in [p.chromium, p.webkit, p.firefox]:
        with BrowserCtx(browser_type) as browser:
            with PageCtx(browser, url) as ppage:
                # There may be other indicators of access denial, but these
                # are common.
                content = ppage.content()
                if "Access Denied" in ppage.title() or "Access Denied" in content:
                    browser.close()
                    continue
            return browser_type, content
    raise ValueError("Failed to get rendered HTML from any browser type")


def extract_links(
    base_url: str, content: str, max_params: int | None = None
) -> list[ExtractedLink]:
    """
    Extracts links from HTML content. The URL is normalized so as to reduce
    duplicates.
    """
    # Parse out links from raw <h ref/> tags
    soup = BeautifulSoup(content, "html.parser")
    raw_links: list[ExtractedLink] = []
    for a in soup.find_all("a", href=True):
        assert isinstance(a, Tag)
        text = a.get_text(" ", strip=True)
        href = a["href"]

        if isinstance(href, str) and href:
            raw_links.append({"url": href, "text": text})

    # Parse out links from Drupal settings
    raw_links.extend(extract_links_from_drupal_settings(base_url, soup))

    # Perform some normalization on the links we've found
    clean_links: list[ExtractedLink] = []
    for link in raw_links:
        href = link["url"]

        # Skip empty, anchor-only, or junk links
        if href.startswith("#"):
            continue

        # Make relative links absolute
        if href.startswith("/"):
            href = base_url + href

        # Skip non-HTTP links
        if not href.startswith("http") and not href.startswith("https"):
            continue

        # Remove fragment for normalization. This removes a whole ton of
        # effective duplicates.
        href = href.split("#")[0]

        # Heuristically limit query string parameters of the links we extract.
        # Most query params don't materially affect the *link* content of a
        # page, yet various combinations make the URL look unique, which would
        # cause us to process the same page over and over. But *sometimes* the
        # query string is important in making the page valid (e.g. a YouTube
        # video ID). In order to strike a balance, we allow a configurable
        # number of query string parameters to be included in the link, using
        # the assumptionat the earliest parameters are the most important.
        if max_params is not None:
            param_split = href.split("?", 1)
            href = param_split[0]
            if max_params > 0 and len(param_split) > 1:
                params = param_split[1].split("&")[:max_params]
                href += "?" + "&".join(params)

        clean_links.append({"url": href, "text": link["text"]})
    return clean_links


def extract_links_from_drupal_settings(
    base_url: str, soup: BeautifulSoup
) -> list[ExtractedLink]:
    """
    # Not all links are in <a> tags. Some sites use JavaScript plugins to manage
    # some of their links, e.g. Drupal. Far from all-encompassing, but this does
    # at least catch some Drupal edge cases. In addition to https://asu.edu, I
    # found another page, https://purple.com, that this scrapes links from
    # successfully, for example.
    """
    # The Drupal config we care about looks like this:
    # <script type="application/json " data-drupal-selector="drupal-settings-json">
    #     {"json": "stuff"}
    # </script>
    script = soup.find(
        "script",
        {"type": "application/json", "data-drupal-selector": "drupal-settings-json"},
    )

    if not isinstance(script, Tag) or not script.string:
        return []

    try:
        data = json.loads(script.string)
    except json.JSONDecodeError:
        return []

    return extract_links_from_json(base_url, data)


def extract_links_from_json(base_url: str, obj: Any) -> list[ExtractedLink]:
    """
    Recursively extracts links from a JSON object. Any given site can have its
    own custom Drupal config structure, so in order to be as generic as
    possible, we just look for any property whose value is a string starting
    "http", "https", or "/". We make an assumption about the kinds of property
    names a descriptive name might have, but it's not exhaustive, so we might
    end up with a URL by itself sometimes.
    """
    links: list[ExtractedLink] = []
    label_words = ("label", "title", "name", "text")

    if isinstance(obj, dict):
        for key, value in obj.items():
            if isinstance(value, str) and (
                value.startswith("/") or re.match(r"https?://", value)
            ):
                # Find keys within the object that contain one of the following
                # words: "text", "label", "title", "name". This is a heuristic
                # to find the label text for the link. It may not always be
                # accurate, but it should work for most cases. The goal is to
                # find a human-readable label for the link, which is often
                # present in the same object as the URL.
                label = ""
                # Check for exact matches first
                for maybe_key in label_words:
                    if maybe_key in obj and isinstance(obj[maybe_key], str):
                        label = obj[maybe_key]
                        break

                # If no exact match, check for partial matches
                if not label:
                    for obj_key in obj.keys():
                        if not isinstance(obj_key, str) or not isinstance(
                            obj[obj_key], str
                        ):
                            continue

                        # Check whether the key *contains* one of the words
                        for maybe_key in label_words:
                            low_key = obj_key.lower()
                            # ...Unless it also has "alttext" (which would
                            # otherwise match "text").
                            if maybe_key in low_key and "alttext" not in low_key:
                                label = obj[obj_key]
                                break
                        if label:
                            break

                full_url = urljoin(base_url, value)
                links.append({"url": full_url, "text": label})
            else:
                links.extend(extract_links_from_json(base_url, value))

    elif isinstance(obj, list):
        for item in obj:
            links.extend(extract_links_from_json(base_url, item))

    return links
