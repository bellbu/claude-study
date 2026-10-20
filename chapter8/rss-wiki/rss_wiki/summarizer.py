"""글 요약·분류 (Haiku). 실패한 글은 pending으로 두고 3회 실패하면 failed."""

from __future__ import annotations

import json
import logging
import sqlite3

from rss_wiki.config import Config
from rss_wiki.db import utcnow
from rss_wiki.llm import BudgetExceeded, LLMClient, LLMError
from rss_wiki.topics import get_or_create_topic, topic_catalog

log = logging.getLogger(__name__)

MAX_RETRIES = 3
MAX_TOPICS = 3

SYSTEM_PROMPT = """당신은 개인용 RSS 위키의 편집자입니다. 수집된 글 하나를 읽고 요약하고 주제를 분류합니다.
분류된 글은 주제별 위키 페이지에 누적되므로, 주제는 몇 주에 걸쳐 여러 글이 모일 수 있는 단위여야 합니다.

규칙:
- summary: 원문 언어와 관계없이 한국어 3~5문장. 글이 말하는 사실만 쓰고 추측을 덧붙이지 않습니다.
- key_points: 핵심 포인트 3개 이내, 각각 한 문장.
- topics: 1~3개, 가장 관련 깊은 주제를 첫 번째에 둡니다.
  - 기존 주제 목록에 맞는 주제가 있으면 반드시 그 이름을 글자 그대로 쓰고 is_new는 false입니다.
  - 맞는 주제가 하나도 없을 때만 새 주제를 만듭니다(is_new true). 새 주제 이름은 짧은 한국어 명사구로,
    특정 사건 하나가 아니라 관련 소식이 계속 쌓일 수 있는 범위로 정합니다. (예: "GPT-9 출시" 대신 "OpenAI 모델")
  - description은 주제를 한 줄로 설명합니다.
- importance: 1~5. 5는 해당 분야에서 반드시 알아야 할 소식, 1은 사소한 소식입니다.
- skip: 광고, 채용 공고, 이벤트 홍보, 내용이 거의 없는 글이면 true. 이때 skip_reason에 이유를 씁니다."""

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "topics": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "is_new": {"type": "boolean"},
                },
                "required": ["name", "description", "is_new"],
                "additionalProperties": False,
            },
        },
        "importance": {"type": "integer"},
        "skip": {"type": "boolean"},
        "skip_reason": {"type": "string"},
    },
    "required": ["summary", "key_points", "topics", "importance", "skip", "skip_reason"],
    "additionalProperties": False,
}


def build_user_message(conn: sqlite3.Connection, article: sqlite3.Row, max_chars: int) -> str:
    feed = conn.execute("SELECT title, url FROM feeds WHERE id = ?", (article["feed_id"],)).fetchone()
    catalog = topic_catalog(conn)
    topics = "\n".join(f"- {t['name']}: {t['description']}" for t in catalog) or "(아직 없음)"
    body = (article["content"] or article["rss_content"] or "")[:max_chars]
    return (
        f"<existing_topics>\n{topics}\n</existing_topics>\n\n"
        f"<article>\n제목: {article['title']}\n출처: {feed['title'] or feed['url']}\n"
        f"발행: {article['published_at'] or '알 수 없음'}\n\n{body}\n</article>"
    )


def process_article(conn: sqlite3.Connection, llm: LLMClient, article_id: int, config: Config) -> str:
    """글 하나를 요약·분류하고 최종 상태를 반환한다. 비용 상한 초과는 호출자에게 전달."""
    article = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
    try:
        result = llm.complete_json(
            model=config.summary_model,
            purpose="summarize",
            system=SYSTEM_PROMPT,
            user=build_user_message(conn, article, config.max_content_chars),
            schema=SCHEMA,
            max_tokens=2000,
            effort="low",
        )
    except BudgetExceeded:
        raise
    except LLMError as e:
        retries = article["retry_count"] + 1
        status = "failed" if retries >= MAX_RETRIES else "pending"
        log.warning("요약 실패 (%s, %d회): %s", article_id, retries, e)
        conn.execute("UPDATE articles SET retry_count = ?, status = ? WHERE id = ?", (retries, status, article_id))
        conn.commit()
        return status

    now = utcnow()
    importance = min(5, max(1, int(result.get("importance") or 1)))
    key_points = json.dumps(result.get("key_points", [])[:3], ensure_ascii=False)
    if result.get("skip"):
        conn.execute(
            "UPDATE articles SET status = 'skipped', summary = ?, key_points = ?, importance = ?, processed_at = ? "
            "WHERE id = ?",
            (result.get("summary", ""), key_points, importance, now, article_id),
        )
        conn.commit()
        return "skipped"

    topic_ids: list[int] = []
    for t in result.get("topics", []):
        if not t.get("name", "").strip():
            continue
        tid, _ = get_or_create_topic(conn, t["name"], t.get("description", ""))
        if tid not in topic_ids:
            topic_ids.append(tid)
        if len(topic_ids) >= MAX_TOPICS:
            break
    if not topic_ids:
        topic_ids.append(get_or_create_topic(conn, "기타", "다른 주제에 속하지 않는 글")[0])

    for i, tid in enumerate(topic_ids):
        conn.execute(
            "INSERT OR IGNORE INTO article_topics(article_id, topic_id, is_primary) VALUES (?, ?, ?)",
            (article_id, tid, 1 if i == 0 else 0),
        )
        conn.execute("UPDATE topics SET last_article_at = ? WHERE id = ?", (now, tid))
    conn.execute(
        "UPDATE articles SET status = 'done', summary = ?, key_points = ?, importance = ?, processed_at = ? "
        "WHERE id = ?",
        (result["summary"], key_points, importance, now, article_id),
    )
    conn.commit()
    return "done"
