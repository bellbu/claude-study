"""새 글 수집: guid 중복 제거, 고아 글 재연결, 조건부 요청, 피드별 실패 격리."""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlparse

from rss_wiki.db import DatabaseError
from rss_wiki.extract import extract_article, html_to_text
from rss_wiki.feeds import FeedError, FeedParseError, parse_feed
from rss_wiki.http import HttpClient, HttpError

logger = logging.getLogger(__name__)

MAX_STATUS_CHARS = 200


@dataclass
class FeedRecord:
    id: int
    name: str | None
    url: str
    etag: str | None
    last_modified: str | None


@dataclass
class FetchResult:
    feed_id: int
    new: int = 0
    not_modified: bool = False
    error: str | None = None


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_feeds(conn: sqlite3.Connection, feed_id: int | None = None) -> list[FeedRecord]:
    """수집 대상 피드를 id 오름차순으로 읽는다. feed_id가 주어졌는데 없으면 FeedError."""
    sql = "SELECT id, name, url, etag, last_modified FROM feeds"
    params: tuple = ()
    if feed_id is not None:
        sql += " WHERE id = ?"
        params = (feed_id,)
    rows = conn.execute(sql + " ORDER BY id", params).fetchall()
    if feed_id is not None and not rows:
        raise FeedError(f"등록된 피드가 없습니다: {feed_id}")
    return [FeedRecord(*r) for r in rows]


def _status_message(message: str) -> str:
    if len(message) > MAX_STATUS_CHARS:
        return message[:MAX_STATUS_CHARS] + "…"
    return message


def _record_error(conn: sqlite3.Connection, feed: FeedRecord, message: str) -> FetchResult:
    try:
        conn.execute(
            "UPDATE feeds SET error_count = error_count + 1, last_status = ?, last_fetched_at = ? WHERE id = ?",
            (f"error: {_status_message(message)}", _now(), feed.id),
        )
    except sqlite3.Error as exc:
        raise DatabaseError(f"수집 오류 기록 실패 (feed id={feed.id}, {feed.url}): {exc}") from exc
    logger.warning("피드 수집 실패 (id=%s): %s", feed.id, message)
    return FetchResult(feed.id, error=message)


def _rollback(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ROLLBACK")
    except sqlite3.Error:
        pass


def _is_new(conn: sqlite3.Connection, feed: FeedRecord, guid: str) -> bool:
    """이 피드에도, 고아 글로도 없는 guid면 INSERT될 새 글이다."""
    if conn.execute("SELECT 1 FROM articles WHERE feed_id = ? AND guid = ?", (feed.id, guid)).fetchone():
        return False
    return not conn.execute(
        "SELECT 1 FROM articles WHERE feed_id IS NULL AND guid = ?", (guid,)
    ).fetchone()


def _resolve_bodies(
    conn: sqlite3.Connection, client: HttpClient, feed: FeedRecord, entries, min_content_chars: int
) -> dict[str, tuple[str, str]]:
    """새 글 중 RSS 본문이 짧은 것의 원문을 추출한다 (PRD 4.2). guid -> (content, content_source).

    트랜잭션 밖에서 호출해야 한다(원문 GET 동안 DB 쓰기 잠금을 잡지 않기 위해).
    추출에 실패한 글은 맵에 넣지 않으며, 저장 시 RSS 본문(rss)이 쓰인다.
    """
    bodies: dict[str, tuple[str, str]] = {}
    seen: set[str] = set()
    for e in entries:
        if e.guid in seen:
            continue
        seen.add(e.guid)
        try:
            is_new = _is_new(conn, feed, e.guid)
        except sqlite3.Error as exc:
            raise DatabaseError(f"글 조회 실패 (feed id={feed.id}, {feed.url}): {exc}") from exc
        if not is_new or len(html_to_text(e.content)) >= min_content_chars:
            continue
        if urlparse(e.url).scheme not in ("http", "https"):
            logger.info("원문 추출 실패, RSS 본문 사용 (%s): http(s) URL이 아님", e.url)
            continue
        try:
            resp = client.get(e.url)
        except HttpError as exc:
            logger.info("원문 추출 실패, RSS 본문 사용 (%s): %s", e.url, exc)
            continue
        text = extract_article(resp.content, e.url)
        if text is None:
            logger.info("원문 추출 실패, RSS 본문 사용 (%s): 본문을 찾지 못함", e.url)
            continue
        bodies[e.guid] = (text, "extracted")
    return bodies


def _store_entries(
    conn: sqlite3.Connection,
    feed: FeedRecord,
    entries,
    bodies: dict[str, tuple[str, str]] | None = None,
) -> int:
    bodies = bodies or {}
    new = 0
    fetched_at = _now()
    for e in entries:
        if conn.execute(
            "SELECT 1 FROM articles WHERE feed_id = ? AND guid = ?", (feed.id, e.guid)
        ).fetchone():
            continue
        orphan = conn.execute(
            "SELECT id FROM articles WHERE feed_id IS NULL AND guid = ? ORDER BY id LIMIT 1",
            (e.guid,),
        ).fetchone()
        if orphan:
            conn.execute("UPDATE articles SET feed_id = ? WHERE id = ?", (feed.id, orphan[0]))
            continue
        content, source = bodies.get(e.guid, (e.content, "rss"))
        conn.execute(
            "INSERT INTO articles (feed_id, guid, url, title, published_at, content, content_source, fetched_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (feed.id, e.guid, e.url, e.title, e.published_at, content, source, fetched_at),
        )
        new += 1
    return new


def fetch_feed(
    conn: sqlite3.Connection, client: HttpClient, feed: FeedRecord, *, min_content_chars: int = 500
) -> FetchResult:
    """피드 하나를 수집한다. HTTP·파싱 실패는 예외 대신 FetchResult.error와 DB 기록으로 남긴다.

    RSS 본문이 min_content_chars보다 짧은 새 글은 원문을 추출해 저장한다(실패하면 RSS 본문).
    """
    try:
        resp = client.get(feed.url, etag=feed.etag, last_modified=feed.last_modified)
        if resp.not_modified:
            try:
                conn.execute(
                    "UPDATE feeds SET last_status = 'not_modified', last_fetched_at = ?, error_count = 0"
                    " WHERE id = ?",
                    (_now(), feed.id),
                )
            except sqlite3.Error as exc:
                raise DatabaseError(f"수집 상태 기록 실패 (feed id={feed.id}, {feed.url}): {exc}") from exc
            return FetchResult(feed.id, not_modified=True)
        # base_url은 리다이렉트와 무관하게 등록 URL (guid 안정화)
        parsed = parse_feed(resp.content, feed.url)
    except (HttpError, FeedParseError) as exc:
        return _record_error(conn, feed, str(exc))

    bodies = _resolve_bodies(conn, client, feed, parsed.entries, min_content_chars)

    conn.execute("BEGIN")
    try:
        new = _store_entries(conn, feed, parsed.entries, bodies)
        conn.execute(
            "UPDATE feeds SET etag = ?, last_modified = ?, last_status = 'ok', last_fetched_at = ?, error_count = 0"
            " WHERE id = ?",
            (resp.etag, resp.last_modified, _now(), feed.id),
        )
        conn.execute("COMMIT")
    except sqlite3.Error as exc:
        _rollback(conn)
        raise DatabaseError(f"글 저장 실패 (feed id={feed.id}, {feed.url}): {exc}") from exc
    except BaseException:
        _rollback(conn)
        raise
    logger.info("피드 수집 완료 (id=%s): 새 글 %d건", feed.id, new)
    return FetchResult(feed.id, new=new)


def fetch_all(
    conn: sqlite3.Connection,
    client: HttpClient,
    feed_id: int | None = None,
    *,
    min_content_chars: int = 500,
) -> list[FetchResult]:
    """등록된 피드를 id 순으로 순차 수집한다. 없는 feed_id면 FeedError."""
    return [
        fetch_feed(conn, client, f, min_content_chars=min_content_chars)
        for f in load_feeds(conn, feed_id)
    ]
