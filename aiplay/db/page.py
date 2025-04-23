from datetime import datetime

from aiplay.db.context import Transaction
from aiplay.db.types import Page


def upsert_page(db: Transaction, page: Page) -> Page:
    db.execute(
        """
        INSERT INTO page (site_id, url, hash, crawl_time)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(site_id, url) DO UPDATE SET
            hash = excluded.hash,
            crawl_time = excluded.crawl_time
        RETURNING id
    """,
        (page.site_id, page.url, page.hash, page.crawl_time.isoformat()),
    )
    row = db.fetchone()
    assert row is not None, "Failed to upsert page"
    return Page(
        id=row[0],
        site_id=page.site_id,
        url=page.url,
        hash=page.hash,
        crawl_time=page.crawl_time,
    )


def update_page_crawl_time(db: Transaction, page_id: int, crawl_time: datetime) -> None:
    db.execute(
        "UPDATE page SET crawl_time = ? WHERE id = ?",
        (crawl_time.isoformat(), page_id),
    )


def get_page_by_id(db: Transaction, page_id: int) -> Page | None:
    db.execute("SELECT * FROM page WHERE id = ?", (page_id,))
    row = db.fetchone()
    return (
        Page(
            id=row[0],
            site_id=row[1],
            url=row[2],
            hash=row[3],
            crawl_time=datetime.fromisoformat(row[4]),
        )
        if row
        else None
    )


def get_page_by_url(db: Transaction, site_id: int, url: str) -> Page | None:
    db.execute("SELECT * FROM page WHERE site_id = ? AND url = ?", (site_id, url))
    row = db.fetchone()
    return (
        Page(
            id=row[0],
            site_id=row[1],
            url=row[2],
            hash=row[3],
            crawl_time=datetime.fromisoformat(row[4]),
        )
        if row
        else None
    )


def list_pages_for_site(db: Transaction, site_id: int) -> list[Page]:
    db.execute("SELECT * FROM page WHERE site_id = ?", (site_id,))
    rows = db.fetchall()
    return [
        Page(
            id=row[0],
            site_id=row[1],
            url=row[2],
            hash=row[3],
            crawl_time=datetime.fromisoformat(row[4]),
        )
        for row in rows
    ]


def delete_stale_pages(db: Transaction, before_time: datetime) -> int:
    db.execute("DELETE FROM page WHERE crawl_time < ?", (before_time.isoformat(),))
    return db.cursor.rowcount
