"""본문 추출: 원문에서 trafilatura로 추출하고, 부족하면 RSS 내용으로 폴백한다."""

from __future__ import annotations

import logging
import sqlite3

import httpx
import trafilatura

from rss_wiki.config import Config
from rss_wiki.dedup import content_hash, find_duplicate, mark_duplicate, strip_html

log = logging.getLogger(__name__)


def extract_content(html: str, url: str | None = None) -> str | None:
    try:
        return trafilatura.extract(html, url=url, include_comments=False, include_tables=False, favor_precision=True)
    except Exception:  # trafilatura 내부 파싱 오류는 폴백으로 처리
        log.exception("본문 추출 실패: %s", url)
        return None


def fetch_and_extract(url: str | None, client: httpx.Client) -> str | None:
    if not url:
        return None
    try:
        resp = client.get(url, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        log.info("원문을 가져오지 못함 %s: %s", url, e)
        return None
    if "html" not in resp.headers.get("content-type", "text/html"):
        return None
    return extract_content(resp.text, url)


def apply_extraction(conn: sqlite3.Connection, article_id: int, text: str | None, config: Config) -> str:
    """추출 결과(없으면 RSS 폴백)를 저장하고 content_source를 반환한다. 추출 후 중복이 드러나면 'duplicate'."""
    a = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
    if text and len(text.strip()) >= config.min_content_chars:
        content, source = text.strip(), "extracted"
    else:
        content, source = strip_html(a["rss_content"] or ""), "rss_fallback"
    chash = content_hash(content)
    conn.execute(
        "UPDATE articles SET content = ?, content_source = ?, content_hash = coalesce(?, content_hash) WHERE id = ?",
        (content, source, chash, article_id),
    )
    conn.commit()
    if chash:
        dup = find_duplicate(
            conn, feed_id=a["feed_id"], canonical_url=None, content_hash=chash,
            title="", published_at=a["published_at"], exclude_id=article_id,
        )
        if dup and dup != article_id:
            mark_duplicate(conn, article_id, dup)
            return "duplicate"
    return source


def extract_article(conn: sqlite3.Connection, article_id: int, client: httpx.Client, config: Config) -> str:
    url = conn.execute("SELECT url FROM articles WHERE id = ?", (article_id,)).fetchone()["url"]
    return apply_extraction(conn, article_id, fetch_and_extract(url, client), config)
