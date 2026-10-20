import json
import threading

import httpx
import pytest

from rss_wiki.db import set_setting, utcnow
from rss_wiki.jobs import JobAlreadyRunning, job_run, run_collect
from rss_wiki.llm import LLMClient
from tests.fakes import FakeAnthropic, make_rss, mock_client

RESULT = {
    "summary": "요약", "key_points": ["k"], "topics": [{"name": "AI", "description": "AI", "is_new": True}],
    "importance": 3, "skip": False, "skip_reason": "",
}


def _setup(conn, n=3):
    conn.execute("INSERT INTO feeds(url, created_at) VALUES ('https://ex.com/feed', ?)", (utcnow(),))
    conn.commit()
    routes = {"https://ex.com/feed": httpx.Response(200, text=make_rss([{"title": f"글 제목 번호 {i}"} for i in range(n)]))}
    return mock_client(routes)  # 원문 URL은 404 → RSS 폴백


def test_full_pipeline(conn, config):
    http = _setup(conn)
    fake = FakeAnthropic(RESULT)
    stats = run_collect(conn, config, http, LLMClient(conn, config, fake))
    assert stats["new_articles"] == 3 and stats["rss_fallback"] == 3 and stats["summarize_done"] == 3
    run = conn.execute("SELECT * FROM job_runs").fetchone()
    assert run["status"] == "ok" and run["finished_at"] and json.loads(run["stats"])["new_articles"] == 3
    assert conn.execute("SELECT count(*) FROM llm_usage WHERE job_run_id = ?", (run["id"],)).fetchone()[0] == 3
    # 두 번째 실행에서는 새 글이 없다
    stats = run_collect(conn, config, http, LLMClient(conn, config, fake))
    assert stats["new_articles"] == 0 and len(fake.calls) == 3


def test_budget_exceeded_stops_and_leaves_pending(conn, config):
    http = _setup(conn)
    set_setting(conn, "daily_budget_usd", "0.0001")
    fake = FakeAnthropic(RESULT, usage=(10_000, 1000))  # 호출 1회로 상한 초과
    stats = run_collect(conn, config, http, LLMClient(conn, config, fake))
    assert stats["budget_exceeded"] and len(fake.calls) == 1
    assert conn.execute("SELECT count(*) FROM articles WHERE status = 'pending'").fetchone()[0] == 2
    assert conn.execute("SELECT status FROM job_runs").fetchone()[0] == "budget_exceeded"


def test_feed_failure_does_not_stop_job(conn, config):
    conn.execute("INSERT INTO feeds(url, created_at) VALUES ('https://bad.com/feed', ?)", (utcnow(),))
    http = _setup(conn)
    import rss_wiki.fetcher as f
    orig, f.BASE_DELAY = f.BASE_DELAY, 0
    try:
        stats = run_collect(conn, config, http, LLMClient(conn, config, FakeAnthropic(RESULT)))
    finally:
        f.BASE_DELAY = orig
    assert stats["failed"] == 1 and stats["summarize_done"] == 3


def test_exception_recorded_as_error(conn, config):
    with job_run(conn, "collect") as (run_id, stats):
        raise RuntimeError("boom")
    run = conn.execute("SELECT * FROM job_runs").fetchone()
    assert run["status"] == "error" and "boom" in json.loads(run["stats"])["error"]


def test_concurrent_job_rejected(conn, config):
    with job_run(conn, "collect"):
        with pytest.raises(JobAlreadyRunning):
            with job_run(conn, "collect"):
                pass
