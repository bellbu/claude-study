"""SQLite 연결과 스키마. 모든 상태는 DB 파일 하나에 저장한다."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from rss_wiki.config import DEFAULT_SETTINGS

SCHEMA = """
CREATE TABLE IF NOT EXISTS feeds (
    id INTEGER PRIMARY KEY,
    url TEXT NOT NULL UNIQUE,
    title TEXT,
    site_url TEXT,
    etag TEXT,
    last_modified TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused')),
    initial_fetch_done INTEGER NOT NULL DEFAULT 0,
    last_success_at TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fetch_logs (
    id INTEGER PRIMARY KEY,
    feed_id INTEGER NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
    attempted_at TEXT NOT NULL,
    attempt_no INTEGER NOT NULL,
    error_type TEXT NOT NULL,
    http_status INTEGER,
    message TEXT
);

CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY,
    feed_id INTEGER NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
    guid TEXT,
    url TEXT,
    canonical_url TEXT,
    title TEXT NOT NULL DEFAULT '',
    author TEXT,
    published_at TEXT,
    rss_content TEXT,
    content TEXT,
    content_source TEXT CHECK (content_source IN ('extracted', 'rss_fallback')),
    content_hash TEXT,
    duplicate_of INTEGER REFERENCES articles(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'done', 'skipped', 'failed', 'duplicate')),
    retry_count INTEGER NOT NULL DEFAULT 0,
    summary TEXT,
    key_points TEXT,
    importance INTEGER,
    collected_at TEXT NOT NULL,
    processed_at TEXT,
    UNIQUE (feed_id, guid)
);
CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);
CREATE INDEX IF NOT EXISTS idx_articles_canonical ON articles(canonical_url);
CREATE INDEX IF NOT EXISTS idx_articles_hash ON articles(content_hash);

CREATE TABLE IF NOT EXISTS topics (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived', 'hidden')),
    user_locked INTEGER NOT NULL DEFAULT 0,
    merged_into INTEGER REFERENCES topics(id),
    created_at TEXT NOT NULL,
    last_article_at TEXT
);

CREATE TABLE IF NOT EXISTS article_topics (
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    is_primary INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (article_id, topic_id)
);

CREATE TABLE IF NOT EXISTS topic_changes (
    id INTEGER PRIMARY KEY,
    type TEXT NOT NULL CHECK (type IN ('merge', 'rename', 'archive', 'hide', 'unarchive')),
    topic_id INTEGER NOT NULL,
    before TEXT,
    after TEXT,
    source TEXT NOT NULL CHECK (source IN ('auto', 'user')),
    reverted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS wiki_revisions (
    id INTEGER PRIMARY KEY,
    topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    article_ids TEXT NOT NULL DEFAULT '[]',
    new_article_ids TEXT NOT NULL DEFAULT '[]',
    model TEXT,
    created_at TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_wiki_topic ON wiki_revisions(topic_id, is_current);

CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY,
    job_type TEXT NOT NULL CHECK (job_type IN ('collect', 'wiki')),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    stats TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY,
    job_run_id INTEGER REFERENCES job_runs(id) ON DELETE SET NULL,
    model TEXT NOT NULL,
    purpose TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
    title, content, summary,
    content='articles', content_rowid='id', tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS articles_ai AFTER INSERT ON articles BEGIN
    INSERT INTO articles_fts(rowid, title, content, summary)
    VALUES (new.id, new.title, coalesce(new.content, new.rss_content), new.summary);
END;
CREATE TRIGGER IF NOT EXISTS articles_ad AFTER DELETE ON articles BEGIN
    INSERT INTO articles_fts(articles_fts, rowid, title, content, summary)
    VALUES ('delete', old.id, old.title, coalesce(old.content, old.rss_content), old.summary);
END;
CREATE TRIGGER IF NOT EXISTS articles_au AFTER UPDATE OF title, content, rss_content, summary ON articles BEGIN
    INSERT INTO articles_fts(articles_fts, rowid, title, content, summary)
    VALUES ('delete', old.id, old.title, coalesce(old.content, old.rss_content), old.summary);
    INSERT INTO articles_fts(rowid, title, content, summary)
    VALUES (new.id, new.title, coalesce(new.content, new.rss_content), new.summary);
END;

-- 위키는 현재 리비전만 검색 대상으로 둔다
CREATE VIRTUAL TABLE IF NOT EXISTS wiki_fts USING fts5(
    topic_id UNINDEXED, content, tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS wiki_ai AFTER INSERT ON wiki_revisions WHEN new.is_current = 1 BEGIN
    DELETE FROM wiki_fts WHERE topic_id = new.topic_id;
    INSERT INTO wiki_fts(topic_id, content) VALUES (new.topic_id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS wiki_au AFTER UPDATE OF is_current ON wiki_revisions
WHEN new.is_current = 1 BEGIN
    DELETE FROM wiki_fts WHERE topic_id = new.topic_id;
    INSERT INTO wiki_fts(topic_id, content) VALUES (new.topic_id, new.content);
END;
CREATE TRIGGER IF NOT EXISTS wiki_topic_ad AFTER DELETE ON topics BEGIN
    DELETE FROM wiki_fts WHERE topic_id = old.id;
END;
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: str | Path) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    init_schema(conn)
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def get_setting(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    if row is not None:
        return row["value"]
    return DEFAULT_SETTINGS[key]


def get_all_settings(conn: sqlite3.Connection) -> dict[str, str]:
    values = dict(DEFAULT_SETTINGS)
    for row in conn.execute("SELECT key, value FROM settings"):
        values[row["key"]] = row["value"]
    return values


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    if key not in DEFAULT_SETTINGS:
        raise KeyError(f"알 수 없는 설정: {key}")
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()
