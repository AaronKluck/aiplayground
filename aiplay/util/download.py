from playwright.sync_api import sync_playwright
import requests
from typing import Tuple

from aiplay.util.html import determine_browser_type


def download_file(url: str) -> Tuple[bytes, str]:
    """
    Download a file from a URL. Not that useful in practice, because many
    sites block you if you don't look like a browser.
    """

    response = requests.get(url)
    if response.status_code != 200:
        raise ValueError(f"Failed to download file: {response.status_code}")
    if "Content-Type" not in response.headers:
        raise ValueError("No Content-Type header in response")
    return response.content, response.headers["Content-Type"]


def download_rendered(url: str) -> str:
    """
    Download a page and return the rendered HTML.
    """
    with sync_playwright() as p:
        _, content = determine_browser_type(p, url)
    return content
