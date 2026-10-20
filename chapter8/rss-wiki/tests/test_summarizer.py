import json

import pytest

from rss_wiki.db import set_setting, utcnow
from rss_wiki.llm import BudgetExceeded, LLMClient
from rss_wiki.summarizer import process_article
from tests.fakes import FakeAnthropic


def _article(conn, title="AI 칩 발표", content="본문 내용"):
    fid = conn.execute("INSERT OR IGNORE INTO feeds(url, title, created_at) VALUES ('f', 'Feed', ?)", (utcnow(),)).lastrowid
    fid = conn.execute("SELECT id FROM feeds WHERE url = 'f'").fetchone()[0]
    return conn.execute(
        "INSERT INTO articles(feed_id, guid, title, content, collected_at) VALUES (?, ?, ?, ?, ?)",
        (fid, title, title, content, utcnow()),
    ).lastrowid


def _result(**kw):
    base = {
        "summary": "요약입니다.", "key_points": ["a", "b", "c", "d"],
        "topics": [{"name": "AI 반도체", "description": "AI 칩 동향", "is_new": True}],
        "importance": 4, "skip": False, "skip_reason": "",
    }
    base.update(kw)
    return base


def test_done_creates_topics_and_links(conn, config):
    aid = _article(conn)
    fake = FakeAnthropic(_result(topics=[
        {"name": "AI 반도체", "description": "AI 칩", "is_new": True},
        {"name": "엔비디아", "description": "엔비디아 소식", "is_new": True},
    ]))
    assert process_article(conn, LLMClient(conn, config, fake), aid, config) == "done"
    a = conn.execute("SELECT * FROM articles WHERE id = ?", (aid,)).fetchone()
    assert a["status"] == "done" and a["importance"] == 4 and len(json.loads(a["key_points"])) == 3
    links = conn.execute(
        "SELECT t.name, at.is_primary FROM article_topics at JOIN topics t ON t.id = at.topic_id ORDER BY at.is_primary DESC"
    ).fetchall()
    assert [(r["name"], r["is_primary"]) for r in links] == [("AI 반도체", 1), ("엔비디아", 0)]
    assert fake.calls[0]["model"] == "claude-haiku-5-5"


def test_existing_topic_reused_and_listed_in_prompt(conn, config):
    process_article(conn, LLMClient(conn, config, FakeAnthropic(_result())), _article(conn, "a"), config)
    fake = FakeAnthropic(_result(topics=[{"name": "ai반도체", "description": "", "is_new": False}]))
    process_article(conn, LLMClient(conn, config, fake), _article(conn, "b"), config)
    assert conn.execute("SELECT count(*) FROM topics").fetchone()[0] == 1
    assert "- AI 반도체: AI 칩 동향" in fake.calls[0]["messages"][0]["content"]


def test_archived_topic_reactivated(conn, config):
    process_article(conn, LLMClient(conn, config, FakeAnthropic(_result())), _article(conn, "a"), config)
    conn.execute("UPDATE topics SET status = 'archived'")
    process_article(conn, LLMClient(conn, config, FakeAnthropic(_result())), _article(conn, "b"), config)
    assert conn.execute("SELECT status FROM topics").fetchone()[0] == "active"
    assert conn.execute("SELECT type FROM topic_changes").fetchone()[0] == "unarchive"


def test_skip(conn, config):
    aid = _article(conn)
    assert process_article(conn, LLMClient(conn, config, FakeAnthropic(_result(skip=True, skip_reason="광고"))), aid, config) == "skipped"
    assert conn.execute("SELECT count(*) FROM article_topics").fetchone()[0] == 0


def test_importance_clamped_and_empty_topics_fallback(conn, config):
    aid = _article(conn)
    process_article(conn, LLMClient(conn, config, FakeAnthropic(_result(importance=9, topics=[]))), aid, config)
    assert conn.execute("SELECT importance FROM articles").fetchone()[0] == 5
    assert conn.execute("SELECT name FROM topics").fetchone()[0] == "기타"


def test_failure_keeps_pending_then_failed(conn, config):
    aid = _article(conn)
    llm = LLMClient(conn, config, FakeAnthropic("broken json"))
    assert process_article(conn, llm, aid, config) == "pending"
    assert process_article(conn, llm, aid, config) == "pending"
    assert process_article(conn, llm, aid, config) == "failed"
    assert conn.execute("SELECT retry_count FROM articles").fetchone()[0] == 3


def test_budget_exceeded_propagates(conn, config):
    set_setting(conn, "daily_budget_usd", "0")
    aid = _article(conn)
    with pytest.raises(BudgetExceeded):
        process_article(conn, LLMClient(conn, config, FakeAnthropic(_result())), aid, config)
    assert conn.execute("SELECT status, retry_count FROM articles").fetchone()[:] == ("pending", 0)


def test_content_truncated(conn, config):
    aid = _article(conn, content="가" * 20000)
    fake = FakeAnthropic(_result())
    process_article(conn, LLMClient(conn, config, fake), aid, config)
    assert fake.calls[0]["messages"][0]["content"].count("가") == config.max_content_chars
