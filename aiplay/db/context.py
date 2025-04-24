import sqlite3
from typing import Any

DB_FILE = "crawler.db"


class Transaction:
    def __init__(self, db_path=DB_FILE):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=10.0)
        self.conn.execute("PRAGMA foreign_keys = ON;")
        self.cursor = self.conn.cursor()

    def __enter__(self) -> sqlite3.Cursor:
        return self.cursor

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            self.conn.commit()
        else:
            self.conn.rollback()
        self.cursor.close()
        self.conn.close()


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
