from datetime import datetime

from aiplay.db.context import Transaction
from aiplay.db.types import Link, Page


def upsert_link(db: Transaction, link: Link) -> Link:
    db.execute(
        """
        INSERT INTO link (site_id, page_id, url, score, keywords, crawl_time)
        VALUES (?, ?, ?, ?, ?, ?)
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
        score=link.score,
        keywords=link.keywords,
        crawl_time=link.crawl_time,
    )


def get_link_by_id(db: Transaction, link_id: int) -> Link | None:
    db.execute("SELECT * FROM link WHERE id = ?", (link_id,))
    row = db.fetchone()
    return (
        Link(
            id=row[0],
            site_id=row[1],
            page_id=row[2],
            url=row[3],
            score=row[4],
            keywords=row[5],
            crawl_time=datetime.fromisoformat(row[6]),
        )
        if row
        else None
    )


def list_links_for_site(db: Transaction, site_id: int) -> list[tuple[Page, Link]]:
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
            score=row[9],
            keywords=row[9],
            crawl_time=datetime.fromisoformat(row[10]),
        )
        results.append((page, link))

    return results


def list_links_for_page(db: Transaction, page_id: int) -> list[Link]:
    db.execute("SELECT * FROM link WHERE page_id = ?", (page_id,))
    return [
        Link(
            id=row[0],
            site_id=row[1],
            page_id=row[2],
            url=row[3],
            score=row[4],
            keywords=row[5],
            crawl_time=datetime.fromisoformat(row[6]),
        )
        for row in db.fetchall()
    ]


def delete_stale_links(db: Transaction, before_time: datetime) -> int:
    db.execute("DELETE FROM link WHERE crawl_time < ?", (before_time.isoformat(),))
    return db.cursor.rowcount
