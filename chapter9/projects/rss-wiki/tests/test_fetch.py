import logging
import sqlite3
from pathlib import Path

import httpx
import pytest

from rss_wiki import cli
from rss_wiki import fetch as fetch_mod
from rss_wiki.cli import main
from rss_wiki.db import DatabaseError, connect
from rss_wiki.feeds import FeedError, FeedParseError
from rss_wiki.fetch import fetch_all, fetch_feed, load_feeds
from rss_wiki.http import HttpClient

FIXTURES = Path(__file__).parent / "fixtures"
ARTICLE_HTML = (FIXTURES / "article.html").read_bytes()
ARTICLE_URL = "https://example.com/posts/1"
URL = "https://example.com/feed.xml"
URL2 = "https://example.org/other.xml"
RSS = (FIXTURES / "rss2.xml").read_bytes()
ETAG = '"abc"'
LM = "Wed, 29 Oct 2025 00:00:00 GMT"


@pytest.fixture
def net(monkeypatch):
    """url -> handler(request) 매핑과 요청 기록을 가진 가짜 HTTP."""
    state = {"requests": [], "routes": {}}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        # 등록되지 않은 URL(원문 페이지 등)은 404
        return state["routes"].get(str(request.url), lambda r: httpx.Response(404))(request)

    state["handler"] = handler
    monkeypatch.setattr(
        cli,
        "make_http_client",
        lambda config: HttpClient(transport=httpx.MockTransport(handler), sleep=lambda s: None),
    )
    state["routes"][URL] = lambda r: httpx.Response(
        200, content=RSS, headers={"ETag": ETAG, "Last-Modified": LM}
    )
    return state


def run(tmp_path, *args):
    return main(["--data-dir", str(tmp_path), *args])


def rows(tmp_path, sql):
    conn = connect(tmp_path / "data" / "rss-wiki.db")
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def add(tmp_path, url=URL):
    assert run(tmp_path, "feed", "add", url) == 0


def test_first_fetch_stores_articles_and_validators(tmp_path, net):
    add(tmp_path)
    assert run(tmp_path, "fetch") == 0
    arts = rows(tmp_path, "SELECT guid, content_source, fetched_at FROM articles")
    assert len(arts) == 3  # guid·링크 없는 항목 제외
    assert {a[1] for a in arts} == {"rss"}
    assert all(a[2].endswith("Z") for a in arts)
    assert rows(tmp_path, "SELECT etag, last_modified, last_status, error_count FROM feeds") == [
        (ETAG, LM, "ok", 0)
    ]


def test_second_fetch_is_idempotent_and_conditional(tmp_path, net):
    add(tmp_path)
    run(tmp_path, "fetch")
    run(tmp_path, "fetch")
    assert len(rows(tmp_path, "SELECT id FROM articles")) == 3
    last = net["requests"][-1]
    assert last.headers["If-None-Match"] == ETAG
    assert last.headers["If-Modified-Since"] == LM


def test_304_marks_not_modified(tmp_path, net, capsys):
    add(tmp_path)
    run(tmp_path, "fetch")
    net["routes"][URL] = lambda r: httpx.Response(304)
    capsys.readouterr()
    assert run(tmp_path, "fetch") == 0
    assert "변경 없음" in capsys.readouterr().out
    assert rows(tmp_path, "SELECT last_status FROM feeds") == [("not_modified",)]
    assert len(rows(tmp_path, "SELECT id FROM articles")) == 3


def test_persistent_503_isolated_from_other_feeds(tmp_path, net, capsys):
    net["routes"][URL2] = lambda r: httpx.Response(200, content=RSS)
    add(tmp_path)
    add(tmp_path, URL2)
    net["routes"][URL] = lambda r: httpx.Response(503)
    capsys.readouterr()
    assert run(tmp_path, "fetch") == 1
    out = capsys.readouterr().out
    assert "오류:" in out
    r = rows(tmp_path, "SELECT id, last_status, error_count FROM feeds ORDER BY id")
    assert r[0][1].startswith("error:") and r[0][2] == 1
    assert r[1][1:] == ("ok", 0)
    assert len(rows(tmp_path, "SELECT id FROM articles WHERE feed_id = 2")) == 3


def test_removed_feed_articles_are_reattached(tmp_path, net):
    add(tmp_path)
    run(tmp_path, "fetch")
    assert run(tmp_path, "feed", "remove", URL) == 0
    add(tmp_path)
    run(tmp_path, "fetch")
    assert len(rows(tmp_path, "SELECT id FROM articles")) == 3
    assert rows(tmp_path, "SELECT DISTINCT feed_id FROM articles") == [(2,)]


def test_relative_guid_uses_registered_url_after_redirect(tmp_path, net):
    body = (
        b'<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>'
        b"<item><title>x</title><guid>post-1</guid><link>/rel/1</link></item></channel></rss>"
    )
    net["routes"][URL] = lambda r: httpx.Response(
        302, headers={"Location": "https://cdn.example.net/moved.xml"}
    )
    net["routes"]["https://cdn.example.net/moved.xml"] = lambda r: httpx.Response(200, content=body)
    add(tmp_path)
    assert run(tmp_path, "fetch") == 0
    assert rows(tmp_path, "SELECT guid, url FROM articles") == [
        ("https://example.com/post-1", "https://example.com/rel/1")
    ]


def test_fetch_missing_feed_returns_1(tmp_path, net, capsys):
    assert run(tmp_path, "fetch", "--feed", "999") == 1
    assert "999" in capsys.readouterr().err


def test_fetch_no_feeds_returns_0(tmp_path, net, capsys):
    assert run(tmp_path, "fetch") == 0
    assert "등록된 피드가 없습니다" in capsys.readouterr().out


def test_fetch_single_feed(tmp_path, net):
    net["routes"][URL2] = lambda r: httpx.Response(200, content=RSS)
    add(tmp_path)
    add(tmp_path, URL2)
    assert run(tmp_path, "fetch", "--feed", "2") == 0
    assert rows(tmp_path, "SELECT DISTINCT feed_id FROM articles") == [(2,)]


def test_failure_logs_warning_with_feed_url(tmp_path, net, caplog):
    add(tmp_path)
    net["routes"][URL] = lambda r: httpx.Response(503)
    conn = connect(tmp_path / "data" / "rss-wiki.db")
    try:
        client = HttpClient(
            transport=httpx.MockTransport(net["handler"]), sleep=lambda s: None
        )
        # add()의 main()이 basicConfig(force=True)로 루트의 caplog 핸들러를 떼므로 다시 붙임
        logging.getLogger().addHandler(caplog.handler)
        with caplog.at_level(logging.WARNING, logger="rss_wiki.fetch"):
            fetch_all(conn, client)
    finally:
        conn.close()
    recs = [r for r in caplog.records if r.name == "rss_wiki.fetch"]
    assert len(recs) >= 1
    assert any(URL in r.getMessage() for r in recs)


def test_non_feed_response_returns_1_and_records_error(tmp_path, net):
    add(tmp_path)
    net["routes"][URL] = lambda r: httpx.Response(200, content=(FIXTURES / "not_feed.html").read_bytes())
    assert run(tmp_path, "fetch") == 1
    status, count = rows(tmp_path, "SELECT last_status, error_count FROM feeds")[0]
    assert status.startswith("error:")
    assert count == 1


def test_success_after_failure_resets_error_count(tmp_path, net):
    add(tmp_path)
    net["routes"][URL] = lambda r: httpx.Response(503)
    assert run(tmp_path, "fetch") == 1
    assert rows(tmp_path, "SELECT error_count FROM feeds") == [(1,)]
    net["routes"][URL] = lambda r: httpx.Response(200, content=RSS)
    assert run(tmp_path, "fetch") == 0
    assert rows(tmp_path, "SELECT error_count, last_status FROM feeds") == [(0, "ok")]


def test_304_resets_error_count_and_updates_fetched_at(tmp_path, net):
    add(tmp_path)
    net["routes"][URL] = lambda r: httpx.Response(503)
    run(tmp_path, "fetch")
    net["routes"][URL] = lambda r: httpx.Response(304)
    assert run(tmp_path, "fetch") == 0
    count, fetched = rows(tmp_path, "SELECT error_count, last_fetched_at FROM feeds")[0]
    assert count == 0
    assert fetched is not None


def test_fetch_all_orders_by_id_and_rejects_unknown_id(tmp_path, net):
    net["routes"][URL2] = lambda r: httpx.Response(200, content=RSS)
    add(tmp_path)
    add(tmp_path, URL2)
    conn = connect(tmp_path / "data" / "rss-wiki.db")
    try:
        client = HttpClient(transport=httpx.MockTransport(net["handler"]))
        results = fetch_all(conn, client)
        assert [r.feed_id for r in results] == [1, 2]
        with pytest.raises(FeedError):
            fetch_all(conn, client, 999)
    finally:
        conn.close()


def test_store_failure_is_fatal_and_rolled_back(tmp_path, net, monkeypatch, capsys):
    add(tmp_path)

    real_store = fetch_mod._store_entries

    def boom(conn, feed, entries, *args):
        real_store(conn, feed, entries, *args)  # 실제 INSERT 발생 후 실패
        assert conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] > 0
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(fetch_mod, "_store_entries", boom)
    capsys.readouterr()
    assert run(tmp_path, "fetch") == 2
    err = capsys.readouterr().err
    assert "database is locked" in err
    assert "Traceback" not in err
    assert rows(tmp_path, "SELECT id FROM articles") == []
    assert rows(tmp_path, "SELECT last_status FROM feeds")[0][0] != "ok"


def test_long_error_is_truncated_in_last_status(tmp_path, net, monkeypatch):
    add(tmp_path)
    long_msg = "x" * 1000

    def bad_parse(content, base_url):
        raise FeedParseError(long_msg)

    monkeypatch.setattr(fetch_mod, "parse_feed", bad_parse)
    conn = connect(tmp_path / "data" / "rss-wiki.db")
    try:
        client = HttpClient(transport=httpx.MockTransport(net["handler"]))
        result = fetch_all(conn, client)[0]
        status = conn.execute("SELECT last_status FROM feeds").fetchone()[0]
    finally:
        conn.close()
    assert len(status) == len("error: ") + 201
    assert status.endswith("…")
    assert result.error == long_msg


def _add_failing_update_trigger(tmp_path):
    conn = connect(tmp_path / "data" / "rss-wiki.db")
    try:
        conn.execute(
            "CREATE TRIGGER fail_upd BEFORE UPDATE ON feeds BEGIN SELECT RAISE(ABORT, 'boom'); END"
        )
    finally:
        conn.close()


def test_record_error_failure_is_fatal(tmp_path, net, capsys):
    add(tmp_path)
    net["routes"][URL] = lambda r: httpx.Response(503)
    _add_failing_update_trigger(tmp_path)
    capsys.readouterr()
    assert run(tmp_path, "fetch") == 2
    err = capsys.readouterr().err
    assert "수집 오류 기록 실패" in err
    assert "Traceback" not in err


def test_304_update_failure_is_fatal(tmp_path, net, capsys):
    add(tmp_path)
    net["routes"][URL] = lambda r: httpx.Response(304)
    _add_failing_update_trigger(tmp_path)
    capsys.readouterr()
    assert run(tmp_path, "fetch") == 2
    err = capsys.readouterr().err
    assert "수집 상태 기록 실패" in err
    assert "Traceback" not in err


def test_fetch_help_exits_0():
    assert main(["fetch", "--help"]) == 0


def _rss_one(link: str, body: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>t</title>'
        f"<item><title>x</title><link>{link}</link><guid>g-1</guid>"
        f"<description><![CDATA[{body}]]></description></item></channel></rss>"
    ).encode()


def _article_requests(net):
    return [r for r in net["requests"] if str(r.url) != URL]


def test_long_rss_body_skips_original_fetch(tmp_path, net):
    net["routes"][URL] = lambda r: httpx.Response(200, content=_rss_one(ARTICLE_URL, "<p>" + "가" * 600 + "</p>"))
    add(tmp_path)
    assert run(tmp_path, "fetch") == 0
    assert _article_requests(net) == []
    assert rows(tmp_path, "SELECT content_source FROM articles") == [("rss",)]


def test_short_rss_body_uses_extracted_original(tmp_path, net):
    net["routes"][URL] = lambda r: httpx.Response(200, content=_rss_one(ARTICLE_URL, "<p>짧음</p>"))
    net["routes"][ARTICLE_URL] = lambda r: httpx.Response(200, content=ARTICLE_HTML)
    add(tmp_path)
    assert run(tmp_path, "fetch") == 0
    src, content = rows(tmp_path, "SELECT content_source, content FROM articles")[0]
    assert src == "extracted"
    assert "빌림 검사기는 하나의 가변 참조" in content


def test_original_404_falls_back_to_rss_body(tmp_path, net):
    net["routes"][URL] = lambda r: httpx.Response(200, content=_rss_one(ARTICLE_URL, "<p>짧음</p>"))
    add(tmp_path)
    assert run(tmp_path, "fetch") == 0
    src, content = rows(tmp_path, "SELECT content_source, content FROM articles")[0]
    assert (src, content) == ("rss", "<p>짧음</p>")
    assert rows(tmp_path, "SELECT last_status FROM feeds") == [("ok",)]
    assert len(_article_requests(net)) == 1


def test_original_404_logs_info(tmp_path, net, caplog):
    net["routes"][URL] = lambda r: httpx.Response(200, content=_rss_one(ARTICLE_URL, "<p>짧음</p>"))
    add(tmp_path)
    conn = connect(tmp_path / "data" / "rss-wiki.db")
    try:
        client = HttpClient(transport=httpx.MockTransport(net["handler"]), sleep=lambda s: None)
        logging.getLogger().addHandler(caplog.handler)
        with caplog.at_level(logging.INFO, logger="rss_wiki.fetch"):
            result = fetch_all(conn, client)[0]
    finally:
        conn.close()
    assert result.error is None
    assert any(
        r.levelno == logging.INFO and "원문 추출 실패, RSS 본문 사용" in r.getMessage() and ARTICLE_URL in r.getMessage()
        for r in caplog.records
    )


def test_non_http_url_skips_original_fetch(tmp_path, net):
    net["routes"][URL] = lambda r: httpx.Response(200, content=_rss_one("urn:1", "<p>짧음</p>"))
    add(tmp_path)
    assert run(tmp_path, "fetch") == 0
    assert _article_requests(net) == []
    assert rows(tmp_path, "SELECT content_source FROM articles") == [("rss",)]


def test_refetch_does_not_fetch_original_again(tmp_path, net):
    net["routes"][URL] = lambda r: httpx.Response(200, content=_rss_one(ARTICLE_URL, "<p>짧음</p>"))
    net["routes"][ARTICLE_URL] = lambda r: httpx.Response(200, content=ARTICLE_HTML)
    add(tmp_path)
    run(tmp_path, "fetch")
    before = len(_article_requests(net))
    assert before == 1
    run(tmp_path, "fetch")
    assert len(_article_requests(net)) == before
    assert len(rows(tmp_path, "SELECT id FROM articles")) == 1


def test_min_content_chars_zero_skips_original_fetch(tmp_path, net):
    add(tmp_path)
    conn = connect(tmp_path / "data" / "rss-wiki.db")
    try:
        client = HttpClient(transport=httpx.MockTransport(net["handler"]))
        fetch_all(conn, client, min_content_chars=0)
    finally:
        conn.close()
    assert _article_requests(net) == []
    assert len(rows(tmp_path, "SELECT id FROM articles")) == 3


def test_original_fetch_happens_outside_transaction(tmp_path, net):
    net["routes"][URL] = lambda r: httpx.Response(200, content=_rss_one(ARTICLE_URL, "<p>짧음</p>"))
    add(tmp_path)
    checked = []

    def article(request):
        other = connect(tmp_path / "data" / "rss-wiki.db")
        try:
            other.execute("BEGIN IMMEDIATE")  # 쓰기 잠금을 잡고 있으면 실패
            other.execute("ROLLBACK")
            checked.append(True)
        finally:
            other.close()
        return httpx.Response(200, content=ARTICLE_HTML)

    net["routes"][ARTICLE_URL] = article
    assert run(tmp_path, "fetch") == 0
    assert checked == [True]


def test_extraction_failure_prints_no_trafilatura_error(tmp_path, net, capfd):
    net["routes"][URL] = lambda r: httpx.Response(200, content=_rss_one(ARTICLE_URL, "<p>짧음</p>"))
    net["routes"][ARTICLE_URL] = lambda r: httpx.Response(200, content=b"<html><body></body></html>")
    add(tmp_path)
    capfd.readouterr()
    assert run(tmp_path, "fetch") == 0
    err = capfd.readouterr().err
    assert "trafilatura" not in err
    assert rows(tmp_path, "SELECT content_source FROM articles") == [("rss",)]


def test_lookup_failure_is_fatal(tmp_path, net, monkeypatch, capsys):
    net["routes"][URL] = lambda r: httpx.Response(200, content=_rss_one(ARTICLE_URL, "<p>짧음</p>"))
    add(tmp_path)

    def boom(conn, feed, guid):
        raise sqlite3.OperationalError("disk I/O error")

    monkeypatch.setattr(fetch_mod, "_is_new", boom)
    capsys.readouterr()
    assert run(tmp_path, "fetch") == 2
    err = capsys.readouterr().err
    assert "글 조회 실패" in err
    assert "disk I/O error" in err
    assert "Traceback" not in err
    assert rows(tmp_path, "SELECT id FROM articles") == []

    # fetch_feed 직접 호출: DatabaseError의 원인이 sqlite3 예외로 연결됨
    conn = connect(tmp_path / "data" / "rss-wiki.db")
    try:
        feed = load_feeds(conn)[0]
        client = HttpClient(transport=httpx.MockTransport(net["handler"]), sleep=lambda s: None)
        with pytest.raises(DatabaseError) as exc:
            fetch_feed(conn, client, feed)
    finally:
        conn.close()
    assert isinstance(exc.value.__cause__, sqlite3.OperationalError)


def test_duplicate_guid_in_response_fetches_original_once(tmp_path, net):
    item = "<item><title>x</title><link>%s</link><guid>g-1</guid><description>짧음</description></item>"
    body = (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>t</title>'
        + (item % ARTICLE_URL) * 2
        + "</channel></rss>"
    ).encode()
    net["routes"][URL] = lambda r: httpx.Response(200, content=body)
    net["routes"][ARTICLE_URL] = lambda r: httpx.Response(200, content=ARTICLE_HTML)
    add(tmp_path)
    assert run(tmp_path, "fetch") == 0
    assert len(_article_requests(net)) == 1
    assert len(rows(tmp_path, "SELECT id FROM articles")) == 1


def test_original_503_falls_back_to_rss_body(tmp_path, net):
    net["routes"][URL] = lambda r: httpx.Response(200, content=_rss_one(ARTICLE_URL, "<p>짧음</p>"))
    net["routes"][ARTICLE_URL] = lambda r: httpx.Response(503)
    add(tmp_path)
    conn = connect(tmp_path / "data" / "rss-wiki.db")
    max_retries = 3
    try:
        client = HttpClient(
            max_retries=max_retries, transport=httpx.MockTransport(net["handler"]), sleep=lambda s: None
        )
        result = fetch_all(conn, client)[0]
    finally:
        conn.close()
    assert result.error is None
    assert len(_article_requests(net)) == 1 + max_retries
    assert rows(tmp_path, "SELECT content_source, last_status FROM articles, feeds") == [("rss", "ok")]
    assert rows(tmp_path, "SELECT content FROM articles") == [("<p>짧음</p>",)]
