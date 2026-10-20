import httpx

from rss_wiki.db import utcnow
from rss_wiki.fetcher import backoff_delay, fetch_all, fetch_feed, parse_entries
from tests.fakes import make_rss, mock_client

URL = "https://ex.com/feed.xml"


def _add_feed(conn, url=URL, **cols):
    fid = conn.execute("INSERT INTO feeds(url, created_at) VALUES (?, ?)", (url, utcnow())).lastrowid
    for k, v in cols.items():
        conn.execute(f"UPDATE feeds SET {k} = ? WHERE id = ?", (v, fid))
    conn.commit()
    return fid


def _feed(conn, fid):
    return conn.execute("SELECT * FROM feeds WHERE id = ?", (fid,)).fetchone()


def test_parse_entries_fields():
    entries = parse_entries(make_rss([{"title": "A", "link": "https://ex.com/a", "description": "<p>본문</p>"}]).encode())
    e = entries[0]
    assert e["guid"] == "https://ex.com/a" and e["title"] == "A"
    assert e["published_at"].startswith("2026-10-01") and "본문" in e["rss_content"]
    assert parse_entries(b"<html>nope</html>") is None


def test_conditional_get_and_state_update(conn, config):
    calls = []
    client = mock_client(
        {URL: httpx.Response(200, text=make_rss([{}]), headers={"etag": '"v1"', "last-modified": "Wed, 01 Oct 2026 00:00:00 GMT"})},
        calls,
    )
    fid = _add_feed(conn)
    by_feed, stats = fetch_all(conn, client, config, sleep=lambda s: None)
    assert stats["ok"] == 1 and len(by_feed[fid]) == 1
    f = _feed(conn, fid)
    assert f["etag"] == '"v1"' and f["last_success_at"] and f["initial_fetch_done"] == 1

    client = mock_client({URL: httpx.Response(304)}, calls)
    by_feed, stats = fetch_all(conn, client, config, sleep=lambda s: None)
    assert stats["not_modified"] == 1 and by_feed[fid] == []
    assert calls[-1].headers["If-None-Match"] == '"v1"'
    assert calls[-1].headers["If-Modified-Since"] == "Wed, 01 Oct 2026 00:00:00 GMT"


def test_initial_fetch_limited_to_recent_n(conn, config):
    client = mock_client({URL: httpx.Response(200, text=make_rss([{} for _ in range(25)]))})
    fid = _add_feed(conn)
    by_feed, _ = fetch_all(conn, client, config, sleep=lambda s: None)
    assert len(by_feed[fid]) == config.initial_fetch_limit
    assert by_feed[fid][0]["title"] == "Post 24"  # 최신순
    by_feed, _ = fetch_all(conn, client, config, sleep=lambda s: None)
    assert len(by_feed[fid]) == 25  # 첫 수집 이후에는 제한 없음 (중복 제거는 저장 단계에서)


def test_retries_with_exponential_backoff_then_logs(conn, config):
    sleeps, calls = [], []
    client = mock_client({URL: httpx.Response(503)}, calls)
    fid = _add_feed(conn)
    _, stats = fetch_all(conn, client, config, sleep=sleeps.append)
    assert stats["failed"] == 1
    assert len(calls) == 4  # 최초 1회 + 재시도 3회
    assert [int(s) for s in sleeps] == [2, 4, 8]
    log = conn.execute("SELECT * FROM fetch_logs WHERE feed_id = ?", (fid,)).fetchall()
    assert len(log) == 1 and log[0]["error_type"] == "server_error" and log[0]["attempt_no"] == 4
    assert _feed(conn, fid)["consecutive_failures"] == 1
    fetch_all(conn, client, config, sleep=lambda s: None)
    assert _feed(conn, fid)["consecutive_failures"] == 2
    assert _feed(conn, fid)["status"] == "active"  # 자동 비활성화하지 않음


def test_recovers_after_transient_failure(conn, config):
    client = mock_client({URL: [httpx.Response(500), httpx.Response(200, text=make_rss([{}]))]})
    fid = _add_feed(conn, consecutive_failures=3)
    _, stats = fetch_all(conn, client, config, sleep=lambda s: None)
    assert stats["ok"] == 1 and _feed(conn, fid)["consecutive_failures"] == 0
    assert conn.execute("SELECT count(*) FROM fetch_logs").fetchone()[0] == 0


def test_429_respects_retry_after(conn):
    sleeps = []
    client = mock_client({URL: [httpx.Response(429, headers={"retry-after": "7"}), httpx.Response(200, text=make_rss([{}]))]})
    res = fetch_feed({"id": 1, "url": URL, "etag": None, "last_modified": None}, client, sleeps.append)
    assert res.status == "ok" and sleeps == [7.0]


def test_4xx_and_parse_errors_not_retried(conn, config):
    calls = []
    client = mock_client({URL: httpx.Response(410), "https://ex.com/bad": httpx.Response(200, text="<html/>")}, calls)
    _add_feed(conn)
    _add_feed(conn, url="https://ex.com/bad")
    _, stats = fetch_all(conn, client, config, sleep=lambda s: None)
    assert stats["failed"] == 2 and len(calls) == 2
    types = {r["error_type"] for r in conn.execute("SELECT error_type FROM fetch_logs")}
    assert types == {"client_error", "parse"}


def test_network_error_classified(conn):
    def boom(request):
        raise httpx.ConnectTimeout("timed out")

    res = fetch_feed({"id": 1, "url": URL, "etag": None, "last_modified": None}, mock_client({URL: boom}), lambda s: None)
    assert res.status == "error" and res.error_type == "timeout" and res.attempts == 4


def test_paused_feeds_skipped(conn, config):
    calls = []
    _add_feed(conn, status="paused")
    fetch_all(conn, mock_client({}, calls), config, sleep=lambda s: None)
    assert calls == []


def test_backoff_delay_growth():
    assert 2 <= backoff_delay(1) < 3 and 4 <= backoff_delay(2) < 5 and 8 <= backoff_delay(3) < 9
