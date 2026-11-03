import logging
import sqlite3
from pathlib import Path

import httpx
import pytest

from rss_wiki import cli
from rss_wiki.config import load_config
from rss_wiki.db import DatabaseError, connect, init_schema
from rss_wiki.http import HttpClient
from rss_wiki.web import create_app

FIXTURES = Path(__file__).parent / "fixtures"
URL = "https://example.com/feed.xml"


@pytest.fixture
def config(tmp_path):
    return load_config(None, tmp_path)


@pytest.fixture
def client(config):
    return create_app(config).test_client()


def test_home_empty_state(client):
    resp = client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "등록된 피드가 없습니다" in html
    assert 'lang="ko"' in html
    assert "/static/style.css" in html


def test_home_with_feed(config, client):
    conn = connect(config.db_path)
    init_schema(conn)
    conn.execute("INSERT INTO feeds (url, name) VALUES ('https://example.com/f.xml', '블로그')")
    conn.close()
    html = client.get("/").get_data(as_text=True)
    assert "등록된 피드가 없습니다" not in html
    assert 'data-count="feeds">1<' in html
    assert 'data-count="articles">0<' in html
    assert 'data-count="pending">0<' in html


def test_static_css_has_tokens(client):
    resp = client.get("/static/style.css")
    assert resp.status_code == 200
    css = resp.get_data(as_text=True)
    assert ":root" in css and "--color-bg" in css and "prefers-color-scheme: dark" in css


def test_database_error_renders_500(monkeypatch, client, caplog):
    def boom(conn):
        raise DatabaseError("상태 조회 실패: boom")

    monkeypatch.setattr("rss_wiki.web.collect_status", boom)
    with caplog.at_level(logging.ERROR, logger="rss_wiki.web"):
        resp = client.get("/")
    assert resp.status_code == 500
    assert any(r.name == "rss_wiki.web" and r.levelno == logging.ERROR for r in caplog.records)
    html = resp.get_data(as_text=True)
    assert "상태 조회 실패: boom" in html
    assert "Traceback" not in html


def test_serve_calls_run_server(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr("rss_wiki.web.run_server", lambda app, host, port: calls.append((host, port)))
    assert cli.main(["--data-dir", str(tmp_path), "serve", "--port", "8123"]) == 0
    assert calls == [("127.0.0.1", 8123)]


# --- T18: 피드 관리 ---


@pytest.fixture
def requests_seen():
    return []


@pytest.fixture
def web(config, requests_seen):
    def handler(request):
        requests_seen.append(str(request.url))
        if request.url.path.endswith("not_feed.html"):
            return httpx.Response(200, content=(FIXTURES / "not_feed.html").read_bytes())
        return httpx.Response(200, content=(FIXTURES / "rss2.xml").read_bytes())

    def factory():
        return HttpClient(transport=httpx.MockTransport(handler), sleep=lambda s: None)

    return create_app(config, http_client_factory=factory).test_client()


def _feed_count(config):
    conn = connect(config.db_path)
    try:
        init_schema(conn)
        return conn.execute("SELECT COUNT(*) FROM feeds").fetchone()[0]
    finally:
        conn.close()


def test_feeds_empty_page(client):
    resp = client.get("/feeds")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "등록된 피드가 없습니다" in html
    assert 'method="post"' in html and 'name="url"' in html


def test_feeds_add_success(config, web):
    resp = web.post("/feeds", data={"url": URL})
    assert resp.status_code == 303
    assert resp.headers["Location"].endswith("/feeds")
    assert _feed_count(config) == 1
    html = web.get("/feeds").get_data(as_text=True)
    assert "피드를 등록했습니다" in html
    conn = connect(config.db_path)
    name = conn.execute("SELECT name FROM feeds").fetchone()[0]
    conn.close()
    assert name in html


def test_feeds_add_duplicate(config, web):
    web.post("/feeds", data={"url": URL})
    web.get("/feeds")  # 첫 flash 소비
    resp = web.post("/feeds", data={"url": URL})
    assert resp.status_code == 303
    html = web.get("/feeds").get_data(as_text=True)
    assert "이미 등록된 피드입니다" in html and URL in html
    assert _feed_count(config) == 1


def test_feeds_add_not_a_feed(config, web):
    resp = web.post("/feeds", data={"url": "https://example.com/not_feed.html"})
    assert resp.status_code == 303
    html = web.get("/feeds").get_data(as_text=True)
    assert "flash-error" in html
    assert _feed_count(config) == 0


def test_feeds_add_empty_url(config, web, requests_seen):
    resp = web.post("/feeds", data={"url": "  "})
    assert resp.status_code == 303
    assert "flash-error" in web.get("/feeds").get_data(as_text=True)
    assert requests_seen == []
    assert _feed_count(config) == 0


def test_feeds_delete(config, web):
    web.post("/feeds", data={"url": URL})
    conn = connect(config.db_path)
    feed_id = conn.execute("SELECT id FROM feeds").fetchone()[0]
    conn.close()
    assert web.get(f"/feeds/{feed_id}/delete").status_code == 405
    resp = web.post(f"/feeds/{feed_id}/delete")
    assert resp.status_code == 303
    assert _feed_count(config) == 0


def test_feeds_delete_missing(web):
    resp = web.post("/feeds/999/delete")
    assert resp.status_code == 303
    html = web.get("/feeds").get_data(as_text=True)
    assert "flash-error" in html and "999" in html


def test_cross_origin_post_forbidden(config, web):
    resp = web.post("/feeds", data={"url": URL}, headers={"Origin": "https://evil.example"})
    assert resp.status_code == 403
    assert _feed_count(config) == 0


def test_same_origin_post_allowed(web):
    resp = web.post("/feeds", data={"url": URL}, headers={"Origin": "http://localhost"})
    assert resp.status_code == 303


def test_nav_links(client):
    html = client.get("/").get_data(as_text=True)
    assert 'href="/feeds"' in html
    assert 'href="/run"' not in html and 'href="/articles"' not in html
    assert "준비 중" in html


# --- T18a ---


def test_home_empty_links_to_feeds(client):
    html = client.get("/").get_data(as_text=True)
    assert 'href="/feeds"' in html
    assert "곧 추가됩니다" not in html


def test_feeds_delete_form_has_confirm(config, web):
    web.post("/feeds", data={"url": URL})
    html = web.get("/feeds").get_data(as_text=True)
    assert "onsubmit=" in html and "confirm(" in html


def test_add_feed_sqlite_error_renders_500(monkeypatch, web, caplog):
    def boom(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr("rss_wiki.web.add_feed", boom)
    with caplog.at_level(logging.ERROR, logger="rss_wiki.web"):
        resp = web.post("/feeds", data={"url": URL})
    assert resp.status_code == 500
    html = resp.get_data(as_text=True)
    assert "database is locked" in html and "Traceback" not in html
    assert any(r.name == "rss_wiki.web" and r.levelno == logging.ERROR for r in caplog.records)


def test_add_without_name_flash_shows_feed_title(web):
    web.post("/feeds", data={"url": URL})
    assert "한국어 테크 블로그" in web.get("/feeds").get_data(as_text=True)


def test_not_feed_error_flash_has_url(web):
    bad = "https://example.com/not_feed.html"
    web.post("/feeds", data={"url": bad})
    assert bad in web.get("/feeds").get_data(as_text=True)


def test_delete_success_redirects_with_message(config, web):
    web.post("/feeds", data={"url": URL})
    conn = connect(config.db_path)
    feed_id = conn.execute("SELECT id FROM feeds").fetchone()[0]
    conn.close()
    resp = web.post(f"/feeds/{feed_id}/delete")
    assert resp.status_code == 303 and resp.headers["Location"].endswith("/feeds")
    html = web.get("/feeds").get_data(as_text=True)
    assert "삭제했습니다" in html and "기존 글은 유지" in html
