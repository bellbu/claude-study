import httpx

from rss_wiki.db import connect, set_setting
from rss_wiki.export import export_markdown, slugify
from rss_wiki.runner import run_job, start_job
from rss_wiki.scheduler import build_scheduler, reschedule
from rss_wiki.wiki import save_revision
from tests.fakes import FakeAnthropic, make_rss, mock_client, seed_topic_articles


def test_scheduler_jobs_follow_settings(config):
    conn = connect(config.db_path)
    scheduler = build_scheduler(config)
    collect, wiki = scheduler.get_job("collect"), scheduler.get_job("wiki")
    assert collect.trigger.interval.total_seconds() == 3600
    assert str(wiki.trigger.fields[wiki.trigger.FIELD_NAMES.index("hour")]) == "6"
    assert collect.args[1] == "collect" and wiki.args[1] == "wiki"

    set_setting(conn, "collect_interval_minutes", "30")
    set_setting(conn, "wiki_hour", "7")
    scheduler.start(paused=True)
    try:
        reschedule(scheduler, config)
        assert scheduler.get_job("collect").trigger.interval.total_seconds() == 1800
        w = scheduler.get_job("wiki").trigger
        assert str(w.fields[w.FIELD_NAMES.index("hour")]) == "7"
    finally:
        scheduler.shutdown(wait=False)
        conn.close()


def test_run_job_with_injected_services(config):
    conn = connect(config.db_path)
    conn.execute("INSERT INTO feeds(url, created_at) VALUES ('https://ex.com/f', 'x')")
    conn.commit()
    result = {
        "summary": "요약", "key_points": [], "topics": [{"name": "AI", "description": "", "is_new": True}],
        "importance": 3, "skip": False, "skip_reason": "",
    }
    services = {
        "http": lambda: mock_client({"https://ex.com/f": httpx.Response(200, text=make_rss([{}]))}),
        "anthropic": lambda: FakeAnthropic(result),
    }
    stats = run_job(config, "collect", services)
    assert stats["summarize_done"] == 1
    assert start_job(config, "collect", services, background=False) is True
    conn.close()


def test_export_markdown_relinks_topics(config, tmp_path):
    conn = connect(config.db_path)
    a, ids = seed_topic_articles(conn, "AI/ML 모델", n=1)
    b, _ = seed_topic_articles(conn, "반도체", n=1, start=5)
    hidden, _ = seed_topic_articles(conn, "숨김", n=1, start=9)
    save_revision(conn, a, f"## 관련 주제\n\n- [반도체](/topics/{b})\n- [없음](/topics/999)", ids, ids, None)
    save_revision(conn, b, "반도체 문서", [], [], None)
    save_revision(conn, hidden, "숨긴 문서", [], [], None)
    conn.execute("UPDATE topics SET status = 'hidden' WHERE id = ?", (hidden,))
    paths = export_markdown(conn, tmp_path / "out")
    names = sorted(p.name for p in paths)
    assert names == ["AI-ML-모델.md", "반도체.md"]
    text = (tmp_path / "out" / "AI-ML-모델.md").read_text(encoding="utf-8")
    assert "[반도체](반도체.md)" in text and "/topics/999" not in text and text.startswith("# AI/ML 모델")
    assert "(AI-ML-모델.md)" in (tmp_path / "out" / "index.md").read_text(encoding="utf-8")
    conn.close()


def test_slugify():
    assert slugify('a:b*c?  d') == "a-b-c-d" and slugify("...") == "topic"


def test_cli_export(config, monkeypatch, tmp_path, capsys):
    from rss_wiki.__main__ import main

    monkeypatch.setenv("RSS_WIKI_DATA_DIR", str(config.data_dir))
    assert main(["export", "--out", str(tmp_path / "exp")]) == 0
    assert "0개 페이지" in capsys.readouterr().out
