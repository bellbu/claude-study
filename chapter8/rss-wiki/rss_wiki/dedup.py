"""중복 제거와 글 저장. 같은 소식은 대표 글 하나에 duplicate_of로 연결한다."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from html import unescape
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from rss_wiki.db import utcnow

TRACKING_PARAMS = {"fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "ref", "ref_src", "igshid", "_hsenc", "_hsmi"}
MIN_HASH_CHARS = 50
TITLE_SIMILARITY = 0.9
TITLE_WINDOW_DAYS = 3
MIN_TITLE_CHARS = 10


def normalize_url(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
    ]
    path = parts.path or "/"
    if len(path) > 1:
        path = path.rstrip("/")
    return urlunsplit(("https" if parts.scheme in ("http", "https") else parts.scheme, host, path, urlencode(sorted(query)), ""))


def strip_html(text: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def content_hash(text: str | None) -> str | None:
    if not text:
        return None
    normalized = strip_html(text).lower()
    if len(normalized) < MIN_HASH_CHARS:
        return None  # "Read more…" 같은 짧은 요약은 충돌하기 쉬워 해시하지 않는다
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _norm_title(title: str) -> str:
    return re.sub(r"[\W_]+", "", title.lower())


def _root(row: sqlite3.Row) -> int:
    return row["duplicate_of"] or row["id"]


def find_duplicate(
    conn: sqlite3.Connection,
    *,
    feed_id: int,
    canonical_url: str | None,
    content_hash: str | None,
    title: str,
    published_at: str | None,
    exclude_id: int | None = None,
) -> int | None:
    """대표 글 id를 반환한다. 중복이 아니면 None."""
    ex = exclude_id or -1
    if canonical_url:
        row = conn.execute(
            "SELECT id, duplicate_of FROM articles WHERE canonical_url = ? AND id != ? ORDER BY id LIMIT 1",
            (canonical_url, ex),
        ).fetchone()
        if row:
            return _root(row)
    if content_hash:
        row = conn.execute(
            "SELECT id, duplicate_of FROM articles WHERE content_hash = ? AND id != ? ORDER BY id LIMIT 1",
            (content_hash, ex),
        ).fetchone()
        if row:
            return _root(row)

    norm = _norm_title(title)
    if len(norm) < MIN_TITLE_CHARS:
        return None
    pivot = datetime.fromisoformat(published_at) if published_at else datetime.fromisoformat(utcnow())
    lo = (pivot - timedelta(days=TITLE_WINDOW_DAYS)).isoformat(timespec="seconds")
    hi = (pivot + timedelta(days=TITLE_WINDOW_DAYS)).isoformat(timespec="seconds")
    rows = conn.execute(
        "SELECT id, duplicate_of, title FROM articles WHERE feed_id != ? AND id != ? "
        "AND coalesce(published_at, collected_at) BETWEEN ? AND ? ORDER BY id",
        (feed_id, ex, lo, hi),
    )
    for row in rows:
        if SequenceMatcher(None, norm, _norm_title(row["title"])).ratio() >= TITLE_SIMILARITY:
            return _root(row)
    return None


def store_entries(conn: sqlite3.Connection, feed_id: int, entries: list[dict]) -> list[int]:
    """새 글을 저장하고, 처리 대상(pending)으로 저장된 글 id 목록을 반환한다."""
    new_ids: list[int] = []
    for e in entries:
        guid = e.get("guid") or e.get("url")
        if not guid:
            continue
        if conn.execute("SELECT 1 FROM articles WHERE feed_id = ? AND guid = ?", (feed_id, guid)).fetchone():
            continue
        canonical = normalize_url(e.get("url"))
        if canonical and conn.execute(
            "SELECT 1 FROM articles WHERE feed_id = ? AND canonical_url = ?", (feed_id, canonical)
        ).fetchone():
            continue  # 같은 피드에서 guid만 바뀐 글
        chash = content_hash(e.get("rss_content"))
        title = e.get("title") or ""
        dup = find_duplicate(
            conn, feed_id=feed_id, canonical_url=canonical, content_hash=chash,
            title=title, published_at=e.get("published_at"),
        )
        cur = conn.execute(
            "INSERT INTO articles(feed_id, guid, url, canonical_url, title, author, published_at, "
            "rss_content, content_hash, duplicate_of, status, collected_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                feed_id, guid, e.get("url"), canonical, title, e.get("author"), e.get("published_at"),
                e.get("rss_content"), chash, dup, "duplicate" if dup else "pending", utcnow(),
            ),
        )
        if dup is None:
            new_ids.append(cur.lastrowid)
    conn.commit()
    return new_ids


def mark_duplicate(conn: sqlite3.Connection, article_id: int, original_id: int) -> None:
    conn.execute(
        "UPDATE articles SET duplicate_of = ?, status = 'duplicate' WHERE id = ?", (original_id, article_id)
    )
    conn.commit()
