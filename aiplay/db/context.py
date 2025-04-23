import sqlite3
from typing import Any

DB_FILE = "crawler.db"


class Transaction:
    def __init__(self, db_path=DB_FILE):
        self.db_path = db_path
        self.conn: sqlite3.Connection | None = None
        self._cursor: sqlite3.Cursor | None = None

    def __enter__(self):
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self._cursor = self.conn.cursor()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if self.conn:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
            self.cursor.close()
            self.conn.close()

    @property
    def cursor(self) -> sqlite3.Cursor:
        assert self._cursor is not None
        return self._cursor

    def execute(self, *args, **kwargs) -> None:
        self.cursor.execute(*args, **kwargs)

    def fetchone(self) -> Any | None:
        return self.cursor.fetchone()

    def fetchall(self) -> list[Any]:
        return self.cursor.fetchall()


def create_schema(db_path=DB_FILE):
    with Transaction(db_path) as db:
        db.execute(
            """
        CREATE TABLE IF NOT EXISTS site (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL UNIQUE,
            crawl_time TIMESTAMP
        );
        """
        )

        db.execute(
            """
        CREATE TABLE IF NOT EXISTS page (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            site_id INTEGER NOT NULL,
            url TEXT NOT NULL,
            hash TEXT,
            crawl_time TIMESTAMP,
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
            score REAL,
            keywords TEXT,
            crawl_time TIMESTAMP,
            FOREIGN KEY (site_id) REFERENCES site(id) ON DELETE CASCADE,
            FOREIGN KEY (page_id) REFERENCES page(id) ON DELETE CASCADE
        );
        """
        )
