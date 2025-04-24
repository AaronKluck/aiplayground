from datetime import datetime
from sqlite3 import Cursor

from aiplay.db.types import Page


def upsert_page(db: Cursor, page: Page) -> Page:
    db.execute(
        """
        INSERT INTO page (site_id, url, hash, crawl_time, error)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(site_id, url) DO UPDATE SET
            hash = excluded.hash,
            crawl_time = excluded.crawl_time
        RETURNING *
    """,
        (page.site_id, page.url, page.hash, page.crawl_time.isoformat(), page.error),
    )
    row = db.fetchone()
    assert row is not None, "Failed to upsert page"
    return Page(
        id=row[0],
        site_id=row[1],
        url=row[2],
        hash=row[3],
        crawl_time=datetime.fromisoformat(row[4]),
        error=row[5],
    )


def update_page_crawl_time(db: Cursor, page_id: int, crawl_time: datetime) -> None:
    db.execute(
        "UPDATE page SET crawl_time = ? WHERE id = ?",
        (crawl_time.isoformat(), page_id),
    )


def update_page_error(db: Cursor, page_id: int, error: str) -> None:
    """
    Update the error message for a page. Also decrements the crawl_time so that
    the page appears as stale.
    """
    db.execute(
        "UPDATE page SET error = ?, crawl_time = DATETIME(crawl_time, '-1 second') WHERE id = ?",
        (error, page_id),
    )


def get_page_by_id(db: Cursor, page_id: int) -> Page | None:
    db.execute("SELECT * FROM page WHERE id = ?", (page_id,))
    row = db.fetchone()
    return (
        Page(
            id=row[0],
            site_id=row[1],
            url=row[2],
            hash=row[3],
            crawl_time=datetime.fromisoformat(row[4]),
            error=row[5],
        )
        if row
        else None
    )


def get_page_by_url(db: Cursor, site_id: int, url: str) -> Page | None:
    db.execute("SELECT * FROM page WHERE site_id = ? AND url = ?", (site_id, url))
    row = db.fetchone()
    return (
        Page(
            id=row[0],
            site_id=row[1],
            url=row[2],
            hash=row[3],
            crawl_time=datetime.fromisoformat(row[4]),
            error=row[5],
        )
        if row
        else None
    )


def list_pages_for_site(db: Cursor, site_id: int) -> list[Page]:
    db.execute("SELECT * FROM page WHERE site_id = ?", (site_id,))
    rows = db.fetchall()
    return [
        Page(
            id=row[0],
            site_id=row[1],
            url=row[2],
            hash=row[3],
            crawl_time=datetime.fromisoformat(row[4]),
            error=row[5],
        )
        for row in rows
    ]


def delete_stale_pages(db: Cursor, before_time: datetime) -> int:
    db.execute("DELETE FROM page WHERE crawl_time < ?", (before_time.isoformat(),))
    return db.rowcount
