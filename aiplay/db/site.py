from datetime import datetime
from sqlite3 import Cursor

from aiplay.db.types import Site


def upsert_site(db: Cursor, site: Site) -> Site:
    """
    By doing upserts, we can update the site if it already exists or insert it
    if it doesn't without having to check if it exists first. The updating of
    crawl_time is involved with cleaning up stale pages and links.
    """
    db.execute(
        """
        INSERT INTO site (url, crawl_time)
        VALUES (?, ?)
        ON CONFLICT(url) DO UPDATE SET crawl_time = excluded.crawl_time
        RETURNING id
    """,
        (site.url, site.crawl_time.isoformat()),
    )
    row = db.fetchone()
    assert row is not None, "Failed to upsert site"
    return Site(
        id=row[0],
        url=site.url,
        crawl_time=site.crawl_time,
    )


def get_site_by_id(db: Cursor, site_id: int) -> Site | None:
    db.execute("SELECT * FROM site WHERE id = ?", (site_id,))
    row = db.fetchone()
    return (
        Site(
            id=row[0],
            url=row[1],
            crawl_time=datetime.fromisoformat(row[2]),
        )
        if row
        else None
    )


def get_site_by_url(db: Cursor, url: str) -> Site | None:
    db.execute("SELECT * FROM site WHERE url = ?", (url,))
    row = db.fetchone()
    return (
        Site(
            id=row[0],
            url=row[1],
            crawl_time=datetime.fromisoformat(row[2]),
        )
        if row
        else None
    )
