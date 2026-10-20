import httpx
import pytest
from fastapi.testclient import TestClient

from rss_wiki.db import connect, get_setting, utcnow
from rss_wiki.web.app import create_app
from rss_wiki.wiki import save_revision
from tests.fakes import FakeAnthropic, make_rss, mock_client, seed_topic_articles

FEED_URL = "https://ex.com/feed.xml"
RESULT = {
    "summary": "요약", "key_points": ["핵심"], "topics": [{"name": "AI", "description": "AI", "is_new": True}],
    "importance": 3, "skip": False, "skip_reason": "",
}


@pytest.fixture
def db(config):
    c = connect(config.db_path)
    yield c
    c.close()


def _routes():
    return {FEED_URL: httpx.Response(200, text=make_rss([{"title": "첫 번째 글 제목"}], title="Ex Blog"))}


@pytest.fixture
def client(config):
    services = {
        "http": lambda: mock_client(_routes()),
        "anthropic": lambda: FakeAnthropic(RESULT),
        "sync_jobs": True,
    }
    return TestClient(create_app(config, services=services))


def test_feed_add_pause_delete(client, db):
    r = client.post("/feeds", data={"url": FEED_URL})
    assert "피드를 추가했습니다" in r.text and "Ex Blog" in r.text
    fid = db.execute("SELECT id FROM feeds").fetchone()[0]
    client.post(f"/feeds/{fid}/status", data={"status": "paused"})
    assert db.execute("SELECT status FROM feeds").fetchone()[0] == "paused"
    assert client.post(f"/feeds/{fid}/status", data={"status": "x"}).status_code == 400
    assert "추가하지 못했습니다" in client.post("/feeds", data={"url": "https://nope.com/"}).text
    client.post(f"/feeds/{fid}/delete")
    assert db.execute("SELECT count(*) FROM feeds").fetchone()[0] == 0


def test_opml_import_export(client, db):
    opml = b'<?xml version="1.0"?><opml version="2.0"><body><outline text="A" xmlUrl="https://a.com/rss"/></body></opml>'
    r = client.post("/feeds/import", files={"file": ("subs.opml", opml, "text/xml")})
    assert "피드 1개를 가져왔습니다" in r.text
    r = client.get("/feeds/export")
    assert r.status_code == 200 and 'xmlUrl="https://a.com/rss"' in r.text
    assert "attachment" in r.headers["content-disposition"]
    assert "OPML 파싱 실패" in client.post("/feeds/import", files={"file": ("x.opml", b"<opml>", "text/xml")}).text


def test_feeds_page_shows_failures(client, db):
    db.execute("INSERT INTO feeds(url, created_at, consecutive_failures) VALUES ('https://bad.com', ?, 2)", (utcnow(),))
    db.execute(
        "INSERT INTO fetch_logs(feed_id, attempted_at, attempt_no, error_type, http_status, message) VALUES (1, ?, 4, 'server_error', 503, 'Service Unavailable')",
        (utcnow(),),
    )
    db.commit()
    page = client.get("/feeds").text
    assert "server_error (503)" in page and "2회" in page
    assert "연속 2회 실패" in client.get("/").text


def test_manual_collect_then_articles_pages(client, db):
    client.post("/feeds", data={"url": FEED_URL})
    r = client.post("/jobs/collect")
    assert "수집을(를) 마쳤습니다" in r.text
    aid = db.execute("SELECT id FROM articles").fetchone()[0]
    page = client.get("/articles").text
    assert "첫 번째 글 제목" in page and "처리완료" in page
    assert "첫 번째 글 제목" in client.get("/articles?status=done").text
    assert "첫 번째 글 제목" not in client.get("/articles?status=failed").text
    detail = client.get(f"/articles/{aid}").text
    assert "요약" in detail and "핵심" in detail and "RSS 내용" in detail
    assert client.get("/articles/999").status_code == 404
    jobs = client.get("/jobs").text
    assert "claude-haiku-5-5" in jobs and "성공" in jobs


def test_retry_failed_article(client, db):
    tid, ids = seed_topic_articles(db, "AI", n=1)
    db.execute("UPDATE articles SET status = 'failed', retry_count = 3")
    db.commit()
    client.post(f"/articles/{ids[0]}/retry")
    assert db.execute("SELECT status, retry_count FROM articles").fetchone()[:] == ("pending", 0)


def test_article_link_rejects_javascript_url(client, db):
    tid, ids = seed_topic_articles(db, "AI", n=1)
    db.execute("UPDATE articles SET url = 'javascript:alert(1)'")
    db.commit()
    assert "javascript:" not in client.get(f"/articles/{ids[0]}").text


def test_manual_wiki_job(client, db):
    seed_topic_articles(db, "AI", n=1)
    assert "위키 갱신을(를) 마쳤습니다" in client.post("/jobs/wiki").text
    assert client.post("/jobs/unknown").status_code == 404


def test_search_page(client, db):
    tid, ids = seed_topic_articles(db, "반도체", n=1)
    save_revision(db, tid, "메모리 반도체 정리 문서", ids, ids, None)
    page = client.get("/search", params={"q": "반도체 정리"}).text
    assert "위키 페이지 (1)" in page and "<mark>" in page
    assert "검색" in client.get("/search").text


def test_settings_validation_and_save(client, db):
    form = {"collect_interval_minutes": "30", "wiki_hour": "7", "wiki_minute": "15", "daily_budget_usd": "2.5",
            "page_max_chars": "5000", "archive_after_days": "14"}
    r = client.post("/settings", data=form)
    assert "설정을 저장했습니다" in r.text
    assert get_setting(db, "wiki_hour") == "7" and get_setting(db, "daily_budget_usd") == "2.5"
    r = client.post("/settings", data={**form, "wiki_hour": "25", "page_max_chars": "abc"})
    assert "0~23" in r.text and "숫자가 아닙니다" in r.text
    assert get_setting(db, "wiki_hour") == "7"
    assert "설정됨" in client.get("/settings").text


def test_settings_change_callback(config, db):
    app = create_app(config)
    calls = []
    app.state.on_settings_changed = lambda: calls.append(1)
    form = {"collect_interval_minutes": "60", "wiki_hour": "6", "wiki_minute": "0", "daily_budget_usd": "1",
            "page_max_chars": "4000", "archive_after_days": "30"}
    TestClient(app).post("/settings", data=form)
    assert calls == [1]


def test_d01_empty_filter_params_from_forms(client, db):
    """D-01: 폼이 보내는 빈 select 값(feed_id=&topic_id=)은 필터 없음으로 처리한다 (422가 나던 결함)."""
    tid, ids = seed_topic_articles(db, "반도체", n=1)
    r = client.get("/search?q=%EB%B0%98%EB%8F%84%EC%B2%B4&feed_id=&topic_id=&since=&until=")
    assert r.status_code == 200 and "반도체 글 0" in r.text
    assert client.get("/articles?status=&feed_id=&topic_id=").status_code == 200
    assert client.get("/articles?status=done&feed_id=&topic_id=&page_no=").status_code == 200
    assert client.get("/articles?feed_id=abc").status_code == 200


def test_d09_error_pages_are_html(client):
    r = client.get("/articles/999")
    assert r.status_code == 404 and "페이지를 찾을 수 없습니다" in r.text and "text/html" in r.headers["content-type"]


def test_d05_duration_label():
    from rss_wiki.web.render import duration

    assert duration("2026-10-20T00:00:00+00:00", "2026-10-20T00:00:14+00:00") == "14초"
    assert duration("2026-10-20T00:00:00+00:00", "2026-10-20T00:02:05+00:00") == "2분 5초"
    assert duration("2026-10-20T00:00:00+00:00", None) == "실행 중"


def test_d04_start_job_reports_running_immediately(config):
    """D-04: 수동 실행 직후 화면이 '실행 중'을 보여줄 수 있도록, start_job은 작업이 잠금을 잡은 뒤 돌아온다."""
    import threading

    from rss_wiki.jobs import is_running
    from rss_wiki.runner import start_job

    release = threading.Event()

    def slow_handler(request):
        release.wait(5)
        return httpx.Response(200, text=make_rss([]))

    conn = connect(config.db_path)
    conn.execute("INSERT INTO feeds(url, created_at) VALUES ('https://slow.test/feed', 'x')")
    conn.commit()
    conn.close()
    services = {"http": lambda: mock_client({"https://slow.test/feed": slow_handler}), "anthropic": lambda: FakeAnthropic(RESULT)}
    try:
        assert start_job(config, "collect", services, background=True) is True
        assert is_running("collect")
        assert start_job(config, "collect", services, background=True) is False
    finally:
        release.set()
    for _ in range(200):
        if not is_running("collect"):
            break
        threading.Event().wait(0.02)
    assert not is_running("collect")
