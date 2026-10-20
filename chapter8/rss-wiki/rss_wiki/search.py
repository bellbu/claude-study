"""FTS5(trigram) 전문 검색. trigram은 3글자 미만 검색어를 못 찾으므로 그때는 LIKE로 대신한다."""

from __future__ import annotations

import html
import re
import sqlite3
from dataclasses import dataclass, field

START, END = "\x02", "\x03"
SNIPPET_RADIUS = 60


@dataclass
class SearchResults:
    query: str
    wiki: list[dict] = field(default_factory=list)
    articles: list[dict] = field(default_factory=list)


def _terms(query: str) -> list[str]:
    return [t for t in query.split() if t]


def _fts_query(terms: list[str]) -> str:
    return " ".join('"' + t.replace('"', '""') + '"' for t in terms)


def clean_wiki_snippet(snippet: str) -> str:
    """위키 미리보기에서 각주 표기([^12])와 Markdown 제목·강조 기호를 뺀다."""
    snippet = re.sub(r"\[\^\d+\]:?", "", snippet)
    snippet = re.sub(r"(^|\s)#{1,6}\s", " ", snippet)
    snippet = snippet.replace("**", "").replace("_아직 정리할 내용이 없습니다._", "")
    return re.sub(r"\s+", " ", snippet).strip()


def highlight(snippet: str) -> str:
    """마커가 들어간 스니펫을 HTML 이스케이프한 뒤 <mark>로 바꾼다."""
    return html.escape(snippet).replace(START, "<mark>").replace(END, "</mark>")


def _manual_snippet(text: str, terms: list[str]) -> str:
    lower = text.lower()
    pos = min((p for p in (lower.find(t.lower()) for t in terms) if p != -1), default=0)
    start = max(0, pos - SNIPPET_RADIUS)
    chunk = text[start:pos + SNIPPET_RADIUS * 2]
    for t in terms:
        idx, out, low = 0, [], chunk.lower()
        while (found := low.find(t.lower(), idx)) != -1:
            out.append(chunk[idx:found] + START + chunk[found:found + len(t)] + END)
            idx = found + len(t)
        out.append(chunk[idx:])
        chunk = "".join(out)
    return ("…" if start > 0 else "") + chunk + ("…" if pos + SNIPPET_RADIUS * 2 < len(text) else "")


def search(
    conn: sqlite3.Connection,
    query: str,
    *,
    feed_id: int | None = None,
    topic_id: int | None = None,
    since: str | None = None,
    until: str | None = None,
    limit: int = 50,
) -> SearchResults:
    terms = _terms(query)
    results = SearchResults(query=query)
    if not terms:
        return results
    use_fts = all(len(t) >= 3 for t in terms)

    # 글 검색
    where, params = ["a.status != 'duplicate'"], []
    if feed_id:
        where.append("a.feed_id = ?")
        params.append(feed_id)
    if topic_id:
        where.append("a.id IN (SELECT article_id FROM article_topics WHERE topic_id = ?)")
        params.append(topic_id)
    if since:
        where.append("coalesce(a.published_at, a.collected_at) >= ?")
        params.append(since)
    if until:
        where.append("coalesce(a.published_at, a.collected_at) < ?")
        params.append(until)
    if use_fts:
        sql = (
            "SELECT a.id, a.title, a.url, a.published_at, a.collected_at, a.status, f.title AS feed_title, "
            f"snippet(articles_fts, -1, '{START}', '{END}', '…', 64) AS snip "
            "FROM articles_fts JOIN articles a ON a.id = articles_fts.rowid JOIN feeds f ON f.id = a.feed_id "
            f"WHERE articles_fts MATCH ? AND {' AND '.join(where)} ORDER BY rank LIMIT ?"
        )
        rows = conn.execute(sql, [_fts_query(terms), *params, limit]).fetchall()
    else:
        for t in terms:
            where.append("(a.title LIKE ? OR coalesce(a.content, a.rss_content, '') LIKE ? OR coalesce(a.summary, '') LIKE ?)")
            params.extend([f"%{t}%"] * 3)
        sql = (
            "SELECT a.id, a.title, a.url, a.published_at, a.collected_at, a.status, f.title AS feed_title, "
            "a.summary, coalesce(a.content, a.rss_content, '') AS body "
            f"FROM articles a JOIN feeds f ON f.id = a.feed_id WHERE {' AND '.join(where)} "
            "ORDER BY coalesce(a.published_at, a.collected_at) DESC LIMIT ?"
        )
        rows = conn.execute(sql, [*params, limit]).fetchall()
    for r in rows:
        snip = r["snip"] if use_fts else _manual_snippet(f"{r['title']} {r['summary'] or ''} {r['body']}", terms)
        results.articles.append({
            "id": r["id"], "title": r["title"], "url": r["url"], "feed_title": r["feed_title"],
            "date": (r["published_at"] or r["collected_at"])[:10], "status": r["status"], "snippet": highlight(snip),
        })

    # 위키 검색 (현재 리비전만)
    wwhere, wparams = ["t.merged_into IS NULL", "t.status != 'hidden'"], []
    if topic_id:
        wwhere.append("t.id = ?")
        wparams.append(topic_id)
    if use_fts:
        sql = (
            f"SELECT t.id, t.name, snippet(wiki_fts, 1, '{START}', '{END}', '…', 64) AS snip "
            "FROM wiki_fts JOIN topics t ON t.id = wiki_fts.topic_id "
            f"WHERE wiki_fts MATCH ? AND {' AND '.join(wwhere)} ORDER BY rank LIMIT ?"
        )
        wrows = conn.execute(sql, [_fts_query(terms), *wparams, limit]).fetchall()
    else:
        for t in terms:
            wwhere.append("w.content LIKE ?")
            wparams.append(f"%{t}%")
        sql = (
            "SELECT t.id, t.name, w.content FROM wiki_fts w JOIN topics t ON t.id = w.topic_id "
            f"WHERE {' AND '.join(wwhere)} LIMIT ?"
        )
        wrows = conn.execute(sql, [*wparams, limit]).fetchall()
    for r in wrows:
        snip = r["snip"] if use_fts else _manual_snippet(r["content"], terms)
        results.wiki.append({"topic_id": r["id"], "name": r["name"], "snippet": highlight(clean_wiki_snippet(snip))})
    return results
