import json

from rss_wiki.db import set_setting
from rss_wiki.jobs import run_wiki
from rss_wiki.llm import LLMClient
from rss_wiki.wiki import current_revision
from tests.fakes import FakeAnthropic, seed_topic_articles


def _responder(cite_map):
    """주제 정리 요청에는 빈 계획, 재작성 요청에는 입력의 새 글을 모두 인용한 섹션을 돌려준다."""

    def respond(params):
        if "merges" in params["output_config"]["format"]["schema"]["properties"]:
            return {"merges": [], "renames": []}
        prompt = params["messages"][0]["content"]
        topic = prompt.split("이름: ")[1].split("\n")[0]
        cites = "".join(f"[^{i}]" for i in cite_map[topic])
        return {
            "overview": "개요", "current_status": f"상황 {cites}", "timeline": f"흐름 {cites}",
            "perspectives": "", "todays_changes": f"변화 {cites}", "related_topics": [],
        }

    return respond


def test_rewrites_only_topics_with_new_articles(conn, config):
    a, a_ids = seed_topic_articles(conn, "A", n=3)
    b, b_ids = seed_topic_articles(conn, "B", n=1, start=10)
    fake = FakeAnthropic(_responder({"A": a_ids, "B": b_ids}))
    stats = run_wiki(conn, config, LLMClient(conn, config, fake))
    assert stats["updated"] == [a, b]  # 새 글이 많은 주제부터
    assert stats["topics"]["merged"] == 0
    run = conn.execute("SELECT * FROM job_runs WHERE job_type = 'wiki'").fetchone()
    assert run["status"] == "ok" and json.loads(run["stats"])["updated"] == [a, b]
    assert current_revision(conn, a) and current_revision(conn, b)

    calls = len(fake.calls)
    stats = run_wiki(conn, config, LLMClient(conn, config, fake))
    assert stats["updated"] == [] and len(fake.calls) == calls + 1  # 주제 정리만 호출


def test_failed_topics_recorded(conn, config):
    a, a_ids = seed_topic_articles(conn, "A", n=1)
    b, b_ids = seed_topic_articles(conn, "B", n=1, start=10)
    fake = FakeAnthropic(_responder({"A": a_ids, "B": [9999]}))
    stats = run_wiki(conn, config, LLMClient(conn, config, fake))
    assert stats["updated"] == [a] and str(b) in stats["failed"]
    assert current_revision(conn, b) is None


def test_hidden_topics_skipped(conn, config):
    a, a_ids = seed_topic_articles(conn, "A", n=1)
    conn.execute("UPDATE topics SET status = 'hidden' WHERE id = ?", (a,))
    stats = run_wiki(conn, config, LLMClient(conn, config, FakeAnthropic(_responder({"A": a_ids}))))
    assert stats["updated"] == []


def test_budget_exceeded(conn, config):
    seed_topic_articles(conn, "A", n=1)
    set_setting(conn, "daily_budget_usd", "0")
    stats = run_wiki(conn, config, LLMClient(conn, config, FakeAnthropic({})))
    assert stats["budget_exceeded"]
    assert conn.execute("SELECT status FROM job_runs").fetchone()[0] == "budget_exceeded"
