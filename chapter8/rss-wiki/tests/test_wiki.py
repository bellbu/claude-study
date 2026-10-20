import json

from rss_wiki.db import set_setting, utcnow
from rss_wiki.llm import LLMClient
from rss_wiki.wiki import (
    current_revision, list_revisions, new_article_ids, revision_diff, rewrite_topic, set_current_revision,
    strip_generated, validate,
)
from tests.fakes import FakeAnthropic, seed_topic_articles


def _sections(ids, **kw):
    cites = "".join(f"[^{i}]" for i in ids)
    base = {
        "overview": "AI 주제입니다.", "current_status": f"현재 상황 {cites}", "timeline": f"- 10-01 사건 {cites}",
        "perspectives": "", "todays_changes": f"- 새 소식 {cites}", "related_topics": [],
    }
    base.update(kw)
    return base


def test_creates_first_revision_with_code_generated_sources(conn, config):
    tid, ids = seed_topic_articles(conn, n=2)
    seed_topic_articles(conn, topic="반도체", n=1, start=10)
    fake = FakeAnthropic(_sections(ids, related_topics=["반도체", "없는주제"]))
    res = rewrite_topic(conn, LLMClient(conn, config, fake), tid, config)
    assert res.status == "updated"
    rev = current_revision(conn, tid)
    content = rev["content"]
    for heading in ("## 개요", "## 현재 상황", "## 주요 흐름", "## 쟁점과 관점", "## 오늘 바뀐 점", "## 관련 주제", "## 출처"):
        assert heading in content
    assert f"[^{ids[0]}]: [AI 글 0](https://ex.com/AI/0) — Ex, 2026-10-01" in content
    assert "(/topics/" in content and "없는주제" not in content
    assert json.loads(rev["article_ids"]) == ids and json.loads(rev["new_article_ids"]) == ids
    assert fake.calls[0]["model"] == "claude-sonnet-5-5"
    assert "새로 작성하세요" in fake.calls[0]["messages"][0]["content"]


def test_only_new_articles_trigger_rewrite_and_prompt_has_current_page(conn, config):
    tid, ids = seed_topic_articles(conn, n=1)
    rewrite_topic(conn, LLMClient(conn, config, FakeAnthropic(_sections(ids))), tid, config)
    assert new_article_ids(conn, tid) == []
    assert rewrite_topic(conn, LLMClient(conn, config, FakeAnthropic({})), tid, config).status == "no_new"

    _, new = seed_topic_articles(conn, n=1, start=5)
    fake = FakeAnthropic(_sections(ids + new))
    assert rewrite_topic(conn, LLMClient(conn, config, fake), tid, config).status == "updated"
    prompt = fake.calls[0]["messages"][0]["content"]
    assert "<current_page>\n## 개요" in prompt and "## 출처" not in prompt
    assert f'<article id="{new[0]}"' in prompt.split("<new_articles>")[1]
    assert len(list_revisions(conn, tid)) == 2


def test_validation_failure_retries_with_errors_then_succeeds(conn, config):
    tid, ids = seed_topic_articles(conn, n=2)
    answers = [_sections([ids[0], 9999]), _sections(ids)]
    fake = FakeAnthropic(lambda p: answers.pop(0))
    assert rewrite_topic(conn, LLMClient(conn, config, fake), tid, config).status == "updated"
    retry_prompt = fake.calls[1]["messages"][0]["content"]
    assert "존재하지 않는 글ID" in retry_prompt and str(ids[1]) in retry_prompt


def test_double_failure_keeps_previous_revision(conn, config):
    tid, ids = seed_topic_articles(conn, n=1)
    rewrite_topic(conn, LLMClient(conn, config, FakeAnthropic(_sections(ids))), tid, config)
    before = current_revision(conn, tid)["id"]
    seed_topic_articles(conn, n=1, start=5)
    res = rewrite_topic(conn, LLMClient(conn, config, FakeAnthropic(_sections(ids, overview=""))), tid, config)
    assert res.status == "failed" and res.errors
    assert current_revision(conn, tid)["id"] == before
    res = rewrite_topic(conn, LLMClient(conn, config, FakeAnthropic("bad json")), tid, config)
    assert res.status == "failed" and "LLM 호출 실패" in res.errors[0]


def test_validate_rules():
    ok = _sections([1, 2])
    assert validate(ok, allowed_ids={1, 2}, must_cite={1, 2}, max_chars=4000) == []
    errs = validate(_sections([1]), allowed_ids={1, 2}, must_cite={2}, max_chars=4000)
    assert any("인용되지 않은" in e for e in errs)
    assert any("상한" in e for e in validate(ok, allowed_ids={1, 2}, must_cite=set(), max_chars=50))
    assert any("비어" in e for e in validate(_sections([1], timeline=" "), allowed_ids={1}, must_cite=set(), max_chars=4000))


def test_low_importance_new_articles_need_not_be_cited(conn, config):
    tid, ids = seed_topic_articles(conn, n=1, importance=4)
    _, low = seed_topic_articles(conn, n=1, importance=1, start=3)
    res = rewrite_topic(conn, LLMClient(conn, config, FakeAnthropic(_sections(ids))), tid, config)
    assert res.status == "updated" and new_article_ids(conn, tid) == []


def test_sources_include_duplicates(conn, config):
    tid, ids = seed_topic_articles(conn, n=1)
    conn.execute("INSERT INTO feeds(url, title, created_at) VALUES ('m', 'Mirror', ?)", (utcnow(),))
    mid = conn.execute("SELECT id FROM feeds WHERE url = 'm'").fetchone()[0]
    conn.execute(
        "INSERT INTO articles(feed_id, guid, url, title, status, duplicate_of, collected_at) VALUES (?, 'd', 'https://m.com/x', 't', 'duplicate', ?, ?)",
        (mid, ids[0], utcnow()),
    )
    rewrite_topic(conn, LLMClient(conn, config, FakeAnthropic(_sections(ids))), tid, config)
    assert "(같은 소식: [Mirror](https://m.com/x))" in current_revision(conn, tid)["content"]


def test_rollback_and_diff(conn, config):
    tid, ids = seed_topic_articles(conn, n=1)
    rewrite_topic(conn, LLMClient(conn, config, FakeAnthropic(_sections(ids))), tid, config)
    first = current_revision(conn, tid)["id"]
    _, new = seed_topic_articles(conn, n=1, start=5)
    rewrite_topic(conn, LLMClient(conn, config, FakeAnthropic(_sections(ids + new, overview="바뀐 개요"))), tid, config)
    second = current_revision(conn, tid)["id"]
    diff = revision_diff(conn, second)
    assert "-AI 주제입니다." in diff and "+바뀐 개요" in diff
    set_current_revision(conn, tid, first)
    assert current_revision(conn, tid)["id"] == first
    assert new_article_ids(conn, tid) == new  # 되돌리면 이후 글이 다시 새 글이 된다
    import pytest
    with pytest.raises(ValueError):
        set_current_revision(conn, tid + 100, first)


def test_strip_generated():
    assert strip_generated("## 개요\n\n본문\n\n## 관련 주제\n\n- x\n\n## 출처\n\n[^1]: y") == "## 개요\n\n본문"
