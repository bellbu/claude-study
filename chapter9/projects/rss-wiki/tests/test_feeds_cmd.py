from pathlib import Path

import httpx
import pytest

from rss_wiki import cli
from rss_wiki.cli import main
from rss_wiki.db import connect
from rss_wiki.http import HttpClient

FIXTURES = Path(__file__).parent / "fixtures"
URL = "https://example.com/feed.xml"


@pytest.fixture
def http(monkeypatch):
    """make_http_client를 MockTransport 클라이언트로 대체. state로 응답과 요청 기록을 제어."""
    state = {"requests": [], "handler": None}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(str(request.url))
        return state["handler"](request)

    def serve(path_or_status):
        if isinstance(path_or_status, int):
            state["handler"] = lambda r: httpx.Response(path_or_status)
        else:
            body = (FIXTURES / path_or_status).read_bytes()
            state["handler"] = lambda r: httpx.Response(200, content=body)

    monkeypatch.setattr(
        cli,
        "make_http_client",
        lambda config: HttpClient(
            transport=httpx.MockTransport(handler), sleep=lambda s: None
        ),
    )
    state["serve"] = serve
    serve("rss2.xml")
    return state


def run(tmp_path, *args):
    return main(["--data-dir", str(tmp_path), *args])


def rows(tmp_path, sql):
    conn = connect(tmp_path / "data" / "rss-wiki.db")
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_add_uses_feed_title_and_prints_id(tmp_path, http, capsys):
    assert run(tmp_path, "feed", "add", URL) == 0
    out = capsys.readouterr().out
    r = rows(tmp_path, "SELECT id, name, url FROM feeds")
    assert len(r) == 1
    assert r[0][1] == "한국어 테크 블로그"
    assert r[0][2] == URL
    assert str(r[0][0]) in out


def test_add_with_name(tmp_path, http):
    assert run(tmp_path, "feed", "add", URL, "--name", "내블로그") == 0
    assert rows(tmp_path, "SELECT name FROM feeds")[0][0] == "내블로그"


def test_add_duplicate_fails_without_request(tmp_path, http, capsys):
    assert run(tmp_path, "feed", "add", URL) == 0
    assert len(http["requests"]) == 1
    capsys.readouterr()
    assert run(tmp_path, "feed", "add", URL) == 1
    assert URL in capsys.readouterr().err
    assert len(http["requests"]) == 1
    assert len(rows(tmp_path, "SELECT id FROM feeds")) == 1


def test_add_html_fails(tmp_path, http, capsys):
    http["serve"]("not_feed.html")
    assert run(tmp_path, "feed", "add", URL) == 1
    assert URL in capsys.readouterr().err
    assert rows(tmp_path, "SELECT id FROM feeds") == []


def test_add_404_fails(tmp_path, http, capsys):
    http["serve"](404)
    assert run(tmp_path, "feed", "add", URL) == 1
    err = capsys.readouterr().err
    assert "404" in err
    assert URL in err
    assert "일시적 오류" not in err
    assert rows(tmp_path, "SELECT id FROM feeds") == []


def test_add_persistent_503_mentions_transient(tmp_path, http, capsys):
    http["serve"](503)
    assert run(tmp_path, "feed", "add", URL) == 1
    assert "일시적 오류" in capsys.readouterr().err
    assert rows(tmp_path, "SELECT id FROM feeds") == []


def test_list_shows_feeds(tmp_path, http, capsys):
    run(tmp_path, "feed", "add", URL, "--name", "내블로그")
    capsys.readouterr()
    assert run(tmp_path, "feed", "list") == 0
    out = capsys.readouterr().out
    assert out.splitlines() == [f"1\t내블로그\t{URL}\t-\t-"]


def test_list_empty(tmp_path, http, capsys):
    assert run(tmp_path, "feed", "list") == 0
    assert "등록된 피드가 없습니다" in capsys.readouterr().out


def test_remove_by_id_and_by_url(tmp_path, http):
    run(tmp_path, "feed", "add", URL)
    fid = rows(tmp_path, "SELECT id FROM feeds")[0][0]
    assert run(tmp_path, "feed", "remove", str(fid)) == 0
    assert rows(tmp_path, "SELECT id FROM feeds") == []
    run(tmp_path, "feed", "add", URL)
    assert run(tmp_path, "feed", "remove", URL) == 0
    assert rows(tmp_path, "SELECT id FROM feeds") == []


def test_remove_missing_returns_1(tmp_path, http, capsys):
    run(tmp_path, "init")
    assert run(tmp_path, "feed", "remove", "999") == 1
    assert "999" in capsys.readouterr().err


def test_remove_unicode_digit_is_not_an_id(tmp_path, http, capsys):
    run(tmp_path, "init")
    assert run(tmp_path, "feed", "remove", "²") == 1
    err = capsys.readouterr().err
    assert "오류:" in err
    assert "등록된 피드가 없습니다" in err
    assert "Traceback" not in err


def test_add_redirect_keeps_registered_url(tmp_path, http):
    body = (FIXTURES / "rss2.xml").read_bytes()

    def handler(request):
        if str(request.url) == URL:
            return httpx.Response(302, headers={"Location": "https://example.com/moved.xml"})
        return httpx.Response(200, content=body)

    http["handler"] = handler
    assert run(tmp_path, "feed", "add", URL) == 0
    assert http["requests"] == [URL, "https://example.com/moved.xml"]
    assert rows(tmp_path, "SELECT url FROM feeds") == [(URL,)]


def test_remove_keeps_articles_with_null_feed(tmp_path, http):
    run(tmp_path, "feed", "add", URL)
    fid = rows(tmp_path, "SELECT id FROM feeds")[0][0]
    conn = connect(tmp_path / "data" / "rss-wiki.db")
    conn.execute(
        "INSERT INTO articles (feed_id, guid, url, fetched_at) VALUES (?, 'g1', 'https://example.com/1', '2026-01-01T00:00:00Z')",
        (fid,),
    )
    conn.close()
    assert run(tmp_path, "feed", "remove", str(fid)) == 0
    r = rows(tmp_path, "SELECT guid, feed_id FROM articles")
    assert r == [("g1", None)]


def test_feed_help_exits_0():
    assert main(["feed", "--help"]) == 0
