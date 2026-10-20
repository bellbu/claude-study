from datetime import datetime, timedelta, timezone

import pytest

from rss_wiki.llm import LLMClient
from rss_wiki.topics import (
    TopicError, archive_inactive, auto_maintain, find_topic, merge_topics, rename_topic, revert_change,
    set_topic_status, topic_catalog,
)
from tests.fakes import FakeAnthropic, seed_topic_articles


def _links(conn, tid):
    return sorted(r[0] for r in conn.execute("SELECT article_id FROM article_topics WHERE topic_id = ?", (tid,)))


def _topic(conn, tid):
    return conn.execute("SELECT * FROM topics WHERE id = ?", (tid,)).fetchone()


def test_merge_moves_articles_and_revert_restores(conn):
    a, a_ids = seed_topic_articles(conn, "AI 모델", n=2)
    b, b_ids = seed_topic_articles(conn, "인공지능 모델", n=1, start=10)
    conn.execute("INSERT INTO article_topics(article_id, topic_id) VALUES (?, ?)", (a_ids[0], b))  # 양쪽에 걸친 글
    cid = merge_topics(conn, b, a, source="auto")
    assert _links(conn, a) == sorted(a_ids + b_ids) and _links(conn, b) == []
    assert _topic(conn, b)["merged_into"] == a
    assert find_topic(conn, "인공지능 모델") == a  # 병합된 이름으로 분류되어도 대상 주제로 간다
    assert b not in [t["id"] for t in topic_catalog(conn)]

    revert_change(conn, cid)
    assert _links(conn, a) == sorted(a_ids) and _links(conn, b) == sorted([a_ids[0]] + b_ids)
    assert _topic(conn, b)["merged_into"] is None
    with pytest.raises(TopicError):
        revert_change(conn, cid)  # 두 번 되돌릴 수 없다


def test_merge_invalid(conn):
    a, _ = seed_topic_articles(conn, "A", n=1)
    with pytest.raises(TopicError):
        merge_topics(conn, a, a)
    with pytest.raises(TopicError):
        merge_topics(conn, a, 999)


def test_user_rename_locks_topic(conn):
    a, _ = seed_topic_articles(conn, "AI", n=1)
    seed_topic_articles(conn, "반도체", n=1, start=5)
    cid = rename_topic(conn, a, "인공지능", source="user")
    assert _topic(conn, a)["name"] == "인공지능" and _topic(conn, a)["user_locked"] == 1
    assert rename_topic(conn, a, "다른 이름", source="auto") is None
    with pytest.raises(TopicError):
        rename_topic(conn, a, "반도체")
    revert_change(conn, cid)
    assert _topic(conn, a)["name"] == "AI"


def test_status_change_and_revert(conn):
    a, _ = seed_topic_articles(conn, "AI", n=1)
    cid = set_topic_status(conn, a, "hidden")
    assert _topic(conn, a)["status"] == "hidden"
    revert_change(conn, cid)
    assert _topic(conn, a)["status"] == "active"


def test_archive_inactive(conn):
    old, _ = seed_topic_articles(conn, "오래된 주제", n=1)
    new, _ = seed_topic_articles(conn, "새 주제", n=1, start=5)
    long_ago = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat(timespec="seconds")
    conn.execute("UPDATE topics SET last_article_at = ?, created_at = ? WHERE id = ?", (long_ago, long_ago, old))
    assert archive_inactive(conn) == [old]
    assert _topic(conn, old)["status"] == "archived" and _topic(conn, new)["status"] == "active"
    change = conn.execute("SELECT * FROM topic_changes").fetchone()
    assert change["type"] == "archive" and change["source"] == "auto"


def test_auto_maintain_applies_plan_and_respects_lock(conn, config):
    a, _ = seed_topic_articles(conn, "AI 모델", n=2)
    b, _ = seed_topic_articles(conn, "AI 모델들", n=1, start=10)
    c, _ = seed_topic_articles(conn, "GPT-9 출시", n=1, start=20)
    d, _ = seed_topic_articles(conn, "고정 주제", n=1, start=30)
    conn.execute("UPDATE topics SET user_locked = 1 WHERE id = ?", (d,))
    plan = {
        "merges": [
            {"source_id": b, "target_id": a, "reason": "같음"},
            {"source_id": d, "target_id": a, "reason": "잠긴 주제"},
            {"source_id": 999, "target_id": a, "reason": "없는 id"},
        ],
        "renames": [{"topic_id": c, "new_name": "OpenAI 모델", "reason": "너무 좁음"}],
    }
    fake = FakeAnthropic(plan)
    stats = auto_maintain(conn, LLMClient(conn, config, fake), config)
    assert stats == {"merged": 1, "renamed": 1, "archived": 0}
    assert _topic(conn, b)["merged_into"] == a and _topic(conn, d)["merged_into"] is None
    assert _topic(conn, c)["name"] == "OpenAI 모델"
    assert fake.calls[0]["model"] == "claude-sonnet-5-5"
    assert f'<topic id="{a}" articles="2">' in fake.calls[0]["messages"][0]["content"]
    sources = {r[0] for r in conn.execute("SELECT source FROM topic_changes")}
    assert sources == {"auto"}


def test_auto_maintain_llm_error_still_archives(conn, config):
    seed_topic_articles(conn, "A", n=1)
    seed_topic_articles(conn, "B", n=1, start=5)
    stats = auto_maintain(conn, LLMClient(conn, config, FakeAnthropic("oops")), config)
    assert stats["merged"] == 0 and "error" in stats


def test_auto_maintain_skips_llm_with_single_topic(conn, config):
    seed_topic_articles(conn, "A", n=1)
    fake = FakeAnthropic({"merges": [], "renames": []})
    auto_maintain(conn, LLMClient(conn, config, fake), config)
    assert fake.calls == []
