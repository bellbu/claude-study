"""RSS 2.0·Atom 파싱(`parse_feed`는 HTTP 비의존)과 피드 등록/목록/삭제."""

from __future__ import annotations

import logging
import sqlite3
from calendar import timegm
from dataclasses import dataclass, field
from datetime import UTC, datetime

import feedparser

from rss_wiki.http import HttpClient, HttpError

logger = logging.getLogger(__name__)


class FeedParseError(Exception):
    """피드가 아닌 문서(HTML 페이지 등)를 파싱하려 할 때."""


@dataclass
class ParsedEntry:
    guid: str
    url: str
    title: str | None
    published_at: str | None
    content: str


@dataclass
class ParsedFeed:
    title: str | None
    entries: list[ParsedEntry] = field(default_factory=list)


def _iso(parsed) -> str | None:
    if not parsed:
        return None
    return datetime.fromtimestamp(timegm(parsed), UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _content(entry) -> str:
    contents = entry.get("content")
    if contents and contents[0].get("value"):
        return contents[0]["value"]
    return entry.get("summary") or ""


def parse_feed(content: bytes, base_url: str) -> ParsedFeed:
    """피드 바이트를 파싱한다. 피드가 아니면 FeedParseError.

    guid는 id(Atom id/RSS guid), 없으면 링크 URL. 둘 다 없는 항목은 건너뛴다.
    """
    d = feedparser.parse(content, response_headers={"content-location": base_url})
    if not d.get("version"):
        raise FeedParseError(f"피드가 아닌 문서입니다: {base_url}")
    if d.get("bozo"):
        logger.debug("피드 문법 경고 (%s): %s", base_url, d.get("bozo_exception"))

    entries: list[ParsedEntry] = []
    for e in d.entries:
        url = e.get("link") or ""
        guid = e.get("id") or url
        if not guid:
            logger.warning("guid와 링크가 없는 항목을 건너뜁니다 (%s): %s", base_url, e.get("title"))
            continue
        entries.append(
            ParsedEntry(
                guid=guid,
                url=url,
                title=e.get("title"),
                published_at=_iso(e.get("published_parsed") or e.get("updated_parsed")),
                content=_content(e),
            )
        )
    return ParsedFeed(title=d.feed.get("title"), entries=entries)


class FeedError(Exception):
    """단일 피드 작업 실패(중복 URL, 없는 피드, 피드 아님, HTTP 실패)."""


@dataclass
class FeedRow:
    id: int
    name: str | None
    url: str
    last_fetched_at: str | None
    last_status: str | None


def add_feed(conn: sqlite3.Connection, client: HttpClient, url: str, name: str | None = None) -> int:
    """피드를 검증해 등록하고 새 feed id를 반환한다. 글은 저장하지 않는다(수집은 fetch)."""
    if conn.execute("SELECT 1 FROM feeds WHERE url = ?", (url,)).fetchone():
        raise FeedError(f"이미 등록된 피드입니다: {url}")
    try:
        resp = client.get(url)
        # 리다이렉트로 최종 URL이 바뀌어도 guid가 안정적이도록 base_url은 등록 URL을 쓴다
        parsed = parse_feed(resp.content, url)
    except HttpError as exc:
        suffix = " (일시적 오류, 나중에 다시 시도)" if exc.transient else ""
        raise FeedError(f"피드를 가져오지 못했습니다: {exc}{suffix}") from exc
    except FeedParseError as exc:
        raise FeedError(str(exc)) from exc
    cur = conn.execute(
        "INSERT INTO feeds (url, name) VALUES (?, ?)", (url, name or parsed.title or url)
    )
    return cur.lastrowid


def list_feeds(conn: sqlite3.Connection) -> list[FeedRow]:
    """등록된 피드를 id 오름차순으로 반환한다."""
    rows = conn.execute(
        "SELECT id, name, url, last_fetched_at, last_status FROM feeds ORDER BY id"
    ).fetchall()
    return [FeedRow(*r) for r in rows]


def remove_feed(conn: sqlite3.Connection, id_or_url: str) -> None:
    """id(정수 문자열) 또는 URL로 피드를 삭제한다. 기존 글은 feed_id가 NULL이 되어 유지된다."""
    if id_or_url.isascii() and id_or_url.isdigit():
        cur = conn.execute("DELETE FROM feeds WHERE id = ?", (int(id_or_url),))
    else:
        cur = conn.execute("DELETE FROM feeds WHERE url = ?", (id_or_url,))
    if cur.rowcount == 0:
        raise FeedError(f"등록된 피드가 없습니다: {id_or_url}")
