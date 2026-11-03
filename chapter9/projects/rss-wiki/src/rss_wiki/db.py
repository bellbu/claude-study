"""SQLite connection and schema (PRD section 5)."""

import sqlite3
from pathlib import Path


class DatabaseError(Exception):
    """The database cannot be opened (fatal, exit code 2)."""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS feeds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    name TEXT,
    etag TEXT,
    last_modified TEXT,
    last_fetched_at TEXT,
    last_status TEXT,
    error_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    feed_id INTEGER REFERENCES feeds(id) ON DELETE SET NULL,
    guid TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    published_at TEXT,
    content TEXT,
    content_source TEXT CHECK (content_source IN ('rss', 'extracted')),
    fetched_at TEXT NOT NULL,
    UNIQUE (feed_id, guid)
);

CREATE TABLE IF NOT EXISTS summaries (
    article_id INTEGER PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('pending', 'done', 'failed')),
    tldr TEXT,
    key_points TEXT,
    model TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    summarized_at TEXT
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS article_tags (
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (article_id, tag_id)
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open the database at db_path, creating parent directories as needed.

    The connection is in autocommit mode (``isolation_level=None``) with
    foreign keys enabled. To group several statements atomically, the caller
    must execute ``BEGIN`` / ``COMMIT`` explicitly; ``with conn:`` does not
    open a transaction. Raises DatabaseError if the database cannot be opened;
    the connection is closed in that case.
    """
    db_path = Path(db_path)
    conn = None
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, isolation_level=None)
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("SELECT count(*) FROM sqlite_master")  # fails early on unreadable files
    except (sqlite3.Error, OSError) as e:
        if conn is not None:
            conn.close()
        raise DatabaseError(f"cannot open database {db_path}: {e}") from e
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Create all tables if missing (idempotent). Raises DatabaseError on failure."""
    try:
        conn.executescript(_SCHEMA)
    except sqlite3.Error as e:
        raise DatabaseError(f"cannot initialize schema: {e}") from e
