"""테스트용 RSS 생성기와 가짜 HTTP 클라이언트."""

from __future__ import annotations

from email.utils import format_datetime
from datetime import datetime, timedelta, timezone

import httpx


def make_rss(items: list[dict], title: str = "Example Feed", link: str = "https://ex.com/") -> str:
    base = datetime(2026, 10, 1, tzinfo=timezone.utc)
    parts = []
    for i, it in enumerate(items):
        pub = format_datetime(it.get("published", base + timedelta(hours=i)))
        parts.append(
            "<item>"
            f"<title>{it.get('title', f'Post {i}')}</title>"
            f"<link>{it.get('link', f'https://ex.com/p/{i}')}</link>"
            f"<guid>{it.get('guid', it.get('link', f'https://ex.com/p/{i}'))}</guid>"
            f"<pubDate>{pub}</pubDate>"
            f"<description><![CDATA[{it.get('description', f'본문 {i}')}]]></description>"
            "</item>"
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        f"<title>{title}</title><link>{link}</link><description>d</description>"
        + "".join(parts)
        + "</channel></rss>"
    )


def mock_client(routes: dict, calls: list | None = None) -> httpx.Client:
    """routes: url -> httpx.Response | callable(request) -> Response | list[Response](순서대로)."""

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if calls is not None:
            calls.append(request)
        route = routes.get(url)
        if route is None:
            return httpx.Response(404, text="not found")
        if isinstance(route, list):
            return route.pop(0) if len(route) > 1 else route[0]
        if callable(route):
            return route(request)
        return route

    return httpx.Client(transport=httpx.MockTransport(handler))


class FakeAnthropic:
    """messages.create / beta.messages.create를 흉내 낸다. responses: dict 또는 callable(params)->dict|Exception."""

    def __init__(self, responder, usage=(1000, 200), stop_reason="end_turn"):
        import json as _json
        from types import SimpleNamespace as NS

        self.calls: list[dict] = []
        outer = self

        def create(**params):
            outer.calls.append(params)
            result = responder(params) if callable(responder) else responder
            if isinstance(result, Exception):
                raise result
            text = result if isinstance(result, str) else _json.dumps(result, ensure_ascii=False)
            return NS(
                content=[NS(type="text", text=text)],
                stop_reason=stop_reason,
                usage=NS(input_tokens=usage[0], output_tokens=usage[1],
                         cache_creation_input_tokens=0, cache_read_input_tokens=0),
            )

        self.messages = NS(create=create)
        self.beta = NS(messages=NS(create=create))


def seed_topic_articles(conn, topic="AI", n=2, importance=4, feed_url="https://ex.com/feed", start=0):
    """status=done 글 n개를 주제에 연결한다. (topic_id, [article_id])"""
    from rss_wiki.db import utcnow

    conn.execute("INSERT OR IGNORE INTO feeds(url, title, created_at) VALUES (?, 'Ex', ?)", (feed_url, utcnow()))
    fid = conn.execute("SELECT id FROM feeds WHERE url = ?", (feed_url,)).fetchone()[0]
    conn.execute("INSERT OR IGNORE INTO topics(name, description, created_at) VALUES (?, '설명', ?)", (topic, utcnow()))
    tid = conn.execute("SELECT id FROM topics WHERE name = ?", (topic,)).fetchone()[0]
    ids = []
    for i in range(start, start + n):
        aid = conn.execute(
            "INSERT INTO articles(feed_id, guid, url, title, content, summary, key_points, importance, status, "
            "published_at, collected_at, processed_at) VALUES (?, ?, ?, ?, '본문', '요약', '[\"핵심\"]', ?, 'done', ?, ?, ?)",
            (fid, f"{topic}-{i}", f"https://ex.com/{topic}/{i}", f"{topic} 글 {i}", importance,
             f"2026-10-{i % 28 + 1:02d}T00:00:00+00:00", utcnow(), utcnow()),
        ).lastrowid
        conn.execute("INSERT INTO article_topics(article_id, topic_id, is_primary) VALUES (?, ?, 1)", (aid, tid))
        ids.append(aid)
    conn.commit()
    return tid, ids
