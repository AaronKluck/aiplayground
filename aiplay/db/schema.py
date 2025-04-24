from aiplay.db.context import Transaction


def create_schema():
    with Transaction() as db:
        # Turn on WAL mode
        db.connection.execute("PRAGMA journal_mode=WAL;")

        db.execute(
            """
        CREATE TABLE IF NOT EXISTS site (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL UNIQUE,
            crawl_time TIMESTAMP NOT NULL
        );
        """
        )

        db.execute(
            """
        CREATE TABLE IF NOT EXISTS page (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id INTEGER NOT NULL,
            url TEXT NOT NULL,
            hash TEXT NOT NULL,
            crawl_time TIMESTAMP NOT NULL,
            error TEXT,
            UNIQUE(site_id, url),
            FOREIGN KEY (site_id) REFERENCES site(id) ON DELETE CASCADE
        );
        """
        )

        db.execute(
            """
        CREATE TABLE IF NOT EXISTS link (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id INTEGER NOT NULL,
            page_id INTEGER NOT NULL,
            url TEXT NOT NULL,
            text TEXT NOT NULL,
            score REAL NOT NULL,
            keywords TEXT NOT NULL,
            crawl_time TIMESTAMP NOT NULL,
            UNIQUE(site_id, page_id, url),
            FOREIGN KEY (site_id) REFERENCES site(id) ON DELETE CASCADE,
            FOREIGN KEY (page_id) REFERENCES page(id) ON DELETE CASCADE
        );
        """
        )

        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_link_site_score ON link (site_id, score);"
        )
