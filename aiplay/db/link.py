from datetime import datetime
from sqlite3 import Cursor

from aiplay.db.types import Link, Page


def upsert_link(db: Cursor, link: Link) -> Link:
    db.execute(
        """
        INSERT INTO link (site_id, page_id, url, text, score, keywords, crawl_time)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(site_id, page_id, url) DO UPDATE SET
            score = excluded.score,
            keywords = excluded.keywords,
            crawl_time = excluded.crawl_time
        RETURNING id
    """,
        (
            link.site_id,
            link.page_id,
            link.url,
            link.text,
            link.score,
            link.keywords,
            link.crawl_time.isoformat(),
        ),
    )
    row = db.fetchone()
    assert row is not None, "Failed to upsert link"
    return Link(
        id=row[0],
        site_id=link.site_id,
        page_id=link.page_id,
        url=link.url,
        text=link.text,
        score=link.score,
        keywords=link.keywords,
        crawl_time=link.crawl_time,
    )


def get_link_by_id(db: Cursor, link_id: int) -> Link | None:
    db.execute("SELECT * FROM link WHERE id = ?", (link_id,))
    row = db.fetchone()
    return (
        Link(
            id=row[0],
            site_id=row[1],
            page_id=row[2],
            url=row[3],
            text=row[4],
            score=row[5],
            keywords=row[6],
            crawl_time=datetime.fromisoformat(row[7]),
        )
        if row
        else None
    )


def list_links_for_site(db: Cursor, site_id: int) -> list[tuple[Page, Link]]:
    db.execute(
        """
        SELECT
            page.id AS page_id,
            page.site_id AS page_site_id,
            page.url AS page_url,
            page.hash AS page_hash,
            page.crawl_time AS page_crawl_time,
            link.id AS link_id,
            link.site_id AS link_site_id,
            link.page_id AS link_page_id,
            link.url AS link_url,
            link.text as link_text,
            link.score AS link_score,
            link.keywords AS link_keywords,
            link.crawl_time AS link_crawl_time
        FROM link
        JOIN page ON link.page_id = page.id
        WHERE link.site_id = ?
    """,
        (site_id,),
    )

    results = []
    for row in db.fetchall():
        page = Page(
            id=row[0],
            site_id=row[1],
            url=row[2],
            hash=row[3],
            crawl_time=datetime.fromisoformat(row[4]),
        )
        link = Link(
            id=row[5],
            site_id=row[6],
            page_id=row[7],
            url=row[8],
            text=row[9],
            score=row[10],
            keywords=row[11],
            crawl_time=datetime.fromisoformat(row[12]),
        )
        results.append((page, link))

    return results


def list_links_for_page(db: Cursor, page_id: int) -> list[Link]:
    db.execute("SELECT * FROM link WHERE page_id = ?", (page_id,))
    return [
        Link(
            id=row[0],
            site_id=row[1],
            page_id=row[2],
            url=row[3],
            text=row[4],
            score=row[5],
            keywords=row[6],
            crawl_time=datetime.fromisoformat(row[7]),
        )
        for row in db.fetchall()
    ]


def delete_stale_links(db: Cursor, before_time: datetime) -> int:
    db.execute("DELETE FROM link WHERE crawl_time < ?", (before_time.isoformat(),))
    return db.rowcount
