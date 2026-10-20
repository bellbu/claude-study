"""피드 수집: 조건부 GET, 파싱, 실패 정책(지수 백오프 3회 + 실패 로그)."""

from __future__ import annotations

import calendar
import random
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

import feedparser
import httpx

from rss_wiki.config import Config
from rss_wiki.db import utcnow

MAX_RETRIES = 3
BASE_DELAY = 2.0
MAX_RETRY_AFTER = 60.0


@dataclass
class FetchResult:
    feed_id: int
    status: str  # ok | not_modified | error
    entries: list[dict] = field(default_factory=list)
    etag: str | None = None
    last_modified: str | None = None
    attempts: int = 0
    error_type: str | None = None
    http_status: int | None = None
    message: str | None = None


def _retry_after(resp: httpx.Response) -> float | None:
    value = resp.headers.get("retry-after")
    if not value:
        return None
    try:
        return min(float(value), MAX_RETRY_AFTER)
    except ValueError:
        return None


def backoff_delay(attempt: int) -> float:
    """attempt번째 재시도 전 대기 시간: 2s, 4s, 8s + 지터."""
    return BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 1)


def _iso(struct: time.struct_time | None) -> str | None:
    if not struct:
        return None
    return datetime.fromtimestamp(calendar.timegm(struct), tz=timezone.utc).isoformat(timespec="seconds")


def parse_entries(content: bytes) -> list[dict] | None:
    """피드를 파싱해 글 목록을 반환한다. 피드가 아니면 None."""
    parsed = feedparser.parse(content)
    if not parsed.get("version") and not parsed.entries:
        return None
    entries = []
    for e in parsed.entries:
        if e.get("content"):
            body = e.content[0].get("value", "")
        else:
            body = e.get("summary", "")
        link = e.get("link")
        entries.append({
            "guid": e.get("id") or link or e.get("title"),
            "url": link,
            "title": e.get("title", ""),
            "author": e.get("author"),
            "published_at": _iso(e.get("published_parsed") or e.get("updated_parsed")),
            "rss_content": body,
        })
    return entries


def fetch_feed(
    feed: sqlite3.Row | dict,
    client: httpx.Client,
    sleep: Callable[[float], None] = time.sleep,
) -> FetchResult:
    """HTTP 요청은 여기서만 한다(DB 접근 없음 — 스레드에서 실행됨)."""
    headers = {}
    if feed["etag"]:
        headers["If-None-Match"] = feed["etag"]
    if feed["last_modified"]:
        headers["If-Modified-Since"] = feed["last_modified"]

    result = FetchResult(feed_id=feed["id"], status="error")
    for attempt in range(1, MAX_RETRIES + 2):  # 최초 1회 + 재시도 3회
        result.attempts = attempt
        retry_wait: float | None = None
        try:
            resp = client.get(feed["url"], headers=headers, follow_redirects=True)
        except httpx.TransportError as e:
            result.error_type = "timeout" if isinstance(e, httpx.TimeoutException) else "network"
            result.http_status = None
            result.message = str(e) or type(e).__name__
        else:
            if resp.status_code == 304:
                result.status = "not_modified"
                return result
            if resp.status_code < 400:
                entries = parse_entries(resp.content)
                if entries is None:
                    result.error_type, result.http_status = "parse", resp.status_code
                    result.message = "피드 형식이 아닙니다"
                    return result
                result.status = "ok"
                result.entries = entries
                result.etag = resp.headers.get("etag")
                result.last_modified = resp.headers.get("last-modified")
                result.error_type = result.message = result.http_status = None
                return result
            result.http_status = resp.status_code
            result.message = resp.reason_phrase
            if resp.status_code == 429:
                result.error_type = "rate_limited"
                retry_wait = _retry_after(resp)
            elif resp.status_code >= 500:
                result.error_type = "server_error"
            else:
                result.error_type = "client_error"
                return result  # 429 외의 4xx는 재시도하지 않는다
        if attempt <= MAX_RETRIES:
            sleep(retry_wait if retry_wait is not None else backoff_delay(attempt))
    return result


def record_result(conn: sqlite3.Connection, result: FetchResult, initial_limit: int) -> list[dict]:
    """수집 결과를 피드 상태와 fetch_logs에 반영하고, 저장할 글 목록을 반환한다."""
    feed = conn.execute("SELECT * FROM feeds WHERE id = ?", (result.feed_id,)).fetchone()
    if feed is None:
        return []
    if result.status == "error":
        conn.execute(
            "INSERT INTO fetch_logs(feed_id, attempted_at, attempt_no, error_type, http_status, message) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (result.feed_id, utcnow(), result.attempts, result.error_type, result.http_status, result.message),
        )
        conn.execute(
            "UPDATE feeds SET consecutive_failures = consecutive_failures + 1 WHERE id = ?",
            (result.feed_id,),
        )
        conn.commit()
        return []

    entries = result.entries
    if not feed["initial_fetch_done"] and entries:
        entries = sorted(entries, key=lambda e: e["published_at"] or "", reverse=True)[:initial_limit]
    conn.execute(
        "UPDATE feeds SET consecutive_failures = 0, last_success_at = ?, initial_fetch_done = 1, "
        "etag = coalesce(?, etag), last_modified = coalesce(?, last_modified) WHERE id = ?",
        (utcnow(), result.etag, result.last_modified, result.feed_id),
    )
    conn.commit()
    return entries


def fetch_all(
    conn: sqlite3.Connection,
    client: httpx.Client,
    config: Config,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[dict[int, list[dict]], dict[str, int]]:
    """활성 피드를 동시에 수집한다. (feed_id -> 새 글 후보, 통계)를 반환."""
    feeds = [dict(r) for r in conn.execute("SELECT * FROM feeds WHERE status = 'active'")]
    with ThreadPoolExecutor(max_workers=config.fetch_concurrency) as pool:
        results = list(pool.map(lambda f: fetch_feed(f, client, sleep), feeds))

    by_feed: dict[int, list[dict]] = {}
    stats = {"feeds": len(feeds), "ok": 0, "not_modified": 0, "failed": 0}
    for res in results:
        entries = record_result(conn, res, config.initial_fetch_limit)
        if res.status == "error":
            stats["failed"] += 1
        else:
            stats[res.status] += 1
            by_feed[res.feed_id] = entries
    return by_feed, stats


def make_client(config: Config) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": config.user_agent},
        timeout=httpx.Timeout(20.0, connect=10.0),
    )
