"""피드 관리: 추가(자동 탐지 포함)·삭제·일시정지, OPML 가져오기·내보내기."""

from __future__ import annotations

import sqlite3
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import urljoin

import feedparser
import httpx

from rss_wiki.db import utcnow

FEED_TYPES = {"application/rss+xml", "application/atom+xml", "application/feed+json", "application/xml", "text/xml"}


class FeedError(Exception):
    pass


class _AlternateLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "link":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        rels = a.get("rel", "").lower().split()
        if "alternate" in rels and a.get("type", "").lower() in FEED_TYPES and a.get("href"):
            self.links.append(a["href"])


def discover_feed_links(html: str, base_url: str) -> list[str]:
    parser = _AlternateLinkParser()
    parser.feed(html)
    return [urljoin(base_url, href) for href in parser.links]


def _parse_feed(content: bytes) -> feedparser.FeedParserDict | None:
    parsed = feedparser.parse(content)
    if parsed.get("version") or parsed.entries:
        return parsed
    return None


def resolve_feed(url: str, client: httpx.Client) -> tuple[str, feedparser.FeedParserDict]:
    """URL이 피드면 그대로, HTML이면 alternate 링크를 따라가 피드를 찾는다."""
    try:
        resp = client.get(url, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise FeedError(f"URL을 가져오지 못했습니다: {e}") from e

    parsed = _parse_feed(resp.content)
    if parsed is not None:
        return str(resp.url), parsed

    for candidate in discover_feed_links(resp.text, str(resp.url)):
        try:
            r = client.get(candidate, follow_redirects=True)
            r.raise_for_status()
        except httpx.HTTPError:
            continue
        parsed = _parse_feed(r.content)
        if parsed is not None:
            return str(r.url), parsed
    raise FeedError("피드를 찾지 못했습니다")


def add_feed(conn: sqlite3.Connection, url: str, client: httpx.Client) -> int:
    feed_url, parsed = resolve_feed(url.strip(), client)
    existing = conn.execute("SELECT id FROM feeds WHERE url = ?", (feed_url,)).fetchone()
    if existing:
        raise FeedError("이미 구독 중인 피드입니다")
    info = parsed.get("feed", {})
    cur = conn.execute(
        "INSERT INTO feeds(url, title, site_url, created_at) VALUES (?, ?, ?, ?)",
        (feed_url, info.get("title"), info.get("link"), utcnow()),
    )
    conn.commit()
    return cur.lastrowid


def list_feeds(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM feeds ORDER BY coalesce(title, url)").fetchall()


def get_feed(conn: sqlite3.Connection, feed_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM feeds WHERE id = ?", (feed_id,)).fetchone()


def delete_feed(conn: sqlite3.Connection, feed_id: int) -> None:
    conn.execute("DELETE FROM feeds WHERE id = ?", (feed_id,))
    conn.commit()


def set_feed_status(conn: sqlite3.Connection, feed_id: int, status: str) -> None:
    if status not in ("active", "paused"):
        raise ValueError(status)
    conn.execute("UPDATE feeds SET status = ? WHERE id = ?", (status, feed_id))
    conn.commit()


def import_opml(conn: sqlite3.Connection, opml_text: str | bytes) -> int:
    """OPML의 xmlUrl을 모두 구독한다. 이미 있는 피드는 건너뛰고 추가된 수를 반환."""
    try:
        root = ET.fromstring(opml_text)
    except ET.ParseError as e:
        raise FeedError(f"OPML 파싱 실패: {e}") from e
    added = 0
    for outline in root.iter("outline"):
        url = outline.get("xmlUrl")
        if not url:
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO feeds(url, title, site_url, created_at) VALUES (?, ?, ?, ?)",
            (url, outline.get("title") or outline.get("text"), outline.get("htmlUrl"), utcnow()),
        )
        added += cur.rowcount
    conn.commit()
    return added


def export_opml(conn: sqlite3.Connection) -> str:
    opml = ET.Element("opml", version="2.0")
    head = ET.SubElement(opml, "head")
    ET.SubElement(head, "title").text = "RSS Wiki subscriptions"
    body = ET.SubElement(opml, "body")
    for f in list_feeds(conn):
        attrs = {"type": "rss", "text": f["title"] or f["url"], "xmlUrl": f["url"]}
        if f["title"]:
            attrs["title"] = f["title"]
        if f["site_url"]:
            attrs["htmlUrl"] = f["site_url"]
        ET.SubElement(body, "outline", attrs)
    return ET.tostring(opml, encoding="unicode", xml_declaration=True)
