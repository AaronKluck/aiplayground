from dataclasses import dataclass
from datetime import datetime


@dataclass(kw_only=True)
class Site:
    id: int = 0
    url: str
    crawl_time: datetime


@dataclass(kw_only=True)
class Page:
    id: int = 0
    site_id: int
    url: str
    hash: str
    crawl_time: datetime
    error: str | None = None


@dataclass(kw_only=True)
class Link:
    id: int = 0
    site_id: int
    page_id: int
    url: str
    text: str
    score: float
    keywords: str
    crawl_time: datetime
