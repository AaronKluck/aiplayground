from fastapi import FastAPI, HTTPException
from typing import List, Optional
import sqlite3
from pydantic import BaseModel
from typing import Optional

"""
I didn't spend *nearly* as much time on the API as I did on the crawler. In a
production API, I would want a stronger tie between my models and the database
tables. Ideally, the tables would be generated from models (which could then
influence the input/output models of the API), and those models would be shared
between the API and the crawler.

I also prefer async/await mode for API services (which need to handle any number
of simultaneous requests, each of which spends most of its time blocked on I/O),
but it was simpler to set up this way.
"""

app = FastAPI()

DB_PATH = "crawler.db"


class Site(BaseModel):
    id: int
    url: str
    crawl_time: str


class Page(BaseModel):
    id: int
    site_id: int
    url: str
    hash: str
    crawl_time: str
    error: Optional[str]


class LinkWithPage(BaseModel):
    id: int
    site_id: int
    page_id: int
    page_url: str
    url: str
    text: str
    score: float
    keywords: List[str]
    crawl_time: str


KW_DELIM = ";"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def format_link_row(row: dict) -> dict:
    """
    Convert the keywords string to a list of keywords. The input format looks
    like ";keyword1;keyword2;keyword3;", and the output format looks like
    ["keyword1", "keyword2", "keyword3"].
    """
    keywords: str = row["keywords"]
    keywords = keywords.lstrip(KW_DELIM).rstrip(KW_DELIM)
    row["keywords"] = [kw for kw in keywords.split(KW_DELIM)]
    return row


# -----------------
# Routes: Site
# -----------------
@app.get(
    "/sites", response_model=List[Site], response_model_exclude_none=True, tags=["site"]
)
def get_site_by_url(limit=100):
    """
    Looks up all sites.
    """
    conn = get_db()
    cur = conn.execute("SELECT * FROM site LIMIT ?", (limit,))
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.get(
    "/sites/{site_id}",
    response_model=Site,
    response_model_exclude_none=True,
    tags=["site"],
)
def get_site(site_id: int):
    """
    Looks up a single site.
    """
    conn = get_db()
    cur = conn.execute("SELECT * FROM site WHERE id = ?", (site_id,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Site not found")
    return dict(row)


# -----------------
# Routes: Page
# -----------------
@app.get(
    "/sites/{site_id}/pages",
    response_model=List[Page],
    response_model_exclude_none=True,
    tags=["page"],
)
def list_pages_by_site(site_id: int, limit=100):
    """
    Looks up all pages for a given site.
    """
    conn = get_db()
    cur = conn.execute("SELECT * FROM page WHERE site_id = ? LIMIT ?", (site_id, limit))
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


@app.get(
    "/sites/{site_id}/pages/{page_id}",
    response_model=Page,
    response_model_exclude_none=True,
    tags=["page"],
)
def get_page(site_id: int, page_id: int):
    """
    Looks up a single page.
    The site_id is entirely redundant here, but it expresses the REST hierarchy
    much more explicitly. You wouldn't even need it for the query if you had the
    page_id, but including it validates the input at the very least.
    """
    conn = get_db()
    cur = conn.execute(
        "SELECT * FROM page WHERE id = ? AND site_id = ?", (page_id, site_id)
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return dict(row)


# -----------------
# Routes: Link
# -----------------
@app.get(
    "/sites/{site_id}/links",
    response_model=List[LinkWithPage],
    response_model_exclude_none=True,
    tags=["link"],
)
def list_links_by_site(site_id: int, keyword: Optional[str] = None, limit: int = 100):
    """
    Looks up all links for a given site.
    """
    conn = get_db()
    if keyword:
        like_pattern = f"%;{keyword};%"
        cur = conn.execute(
            """
            SELECT l.*, p.url AS page_url
            FROM link l
            JOIN page p ON l.page_id = p.id
            WHERE l.site_id = ? AND l.keywords LIKE ?
            ORDER BY l.score DESC
            LIMIT ?
        """,
            (site_id, like_pattern, limit),
        )
    else:
        cur = conn.execute(
            """
            SELECT l.*, p.url AS page_url
            FROM link l
            JOIN page p ON l.page_id = p.id
            WHERE l.site_id = ?
            ORDER BY l.score DESC
            LIMIT ?
        """,
            (site_id, limit),
        )
    rows = cur.fetchall()
    conn.close()
    return [format_link_row(dict(row)) for row in rows]


@app.get(
    "/sites/{site_id}/pages/{page_id}/links",
    response_model=List[LinkWithPage],
    response_model_exclude_none=True,
    tags=["link"],
)
def list_links_by_page(site_id: int, page_id: int, limit=100):
    """
    Looks up all links for a given page.
    The site_id is entirely redundant here, but it expresses the REST hierarchy
    much more explicitly. You wouldn't even need it for the query if you had the
    page_id, but including it validates the input at the very least.
    """
    conn = get_db()
    cur = conn.execute(
        """
        SELECT l.*, p.url AS page_url
        FROM link l
        JOIN page p ON l.page_id = p.id
        WHERE l.page_id = ? AND l.site_id = ?
        ORDER BY l.score DESC
        LIMIT ?
    """,
        (page_id, site_id, limit),
    )
    rows = cur.fetchall()
    conn.close()
    return [format_link_row(dict(row)) for row in rows]


@app.get(
    "/sites/{site_id}/page/{page_id}/link/{link_id}",
    response_model=LinkWithPage,
    response_model_exclude_none=True,
    tags=["link"],
)
def get_link(site_id: int, page_id: int, link_id: int):
    """
    Looks up a single link.
    The site_id and page_id are entirely redundant here, but it expresses the
    REST hierarchy much more explicitly. You wouldn't even need them for the
    query if you had the link_id, but including them validates the input at the
    very least.
    """
    conn = get_db()
    cur = conn.execute(
        """
        SELECT l.*, p.url AS page_url
        FROM link l
        JOIN page p ON l.page_id = p.id
        WHERE l.id = ? AND l.site_id = ? AND l.page_id = ?
    """,
        (link_id, site_id, page_id),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Link not found")
    return format_link_row(dict(row))
