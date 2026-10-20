"""위키 재작성 (Sonnet). 전체를 다시 쓰되, 출처 목록은 코드가 만들고 결과를 검증한 뒤에만 저장한다."""

from __future__ import annotations

import difflib
import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field

from rss_wiki.config import Config
from rss_wiki.db import get_setting, utcnow
from rss_wiki.llm import BudgetExceeded, LLMClient, LLMError

log = logging.getLogger(__name__)

SECTIONS = [
    ("overview", "개요"),
    ("current_status", "현재 상황"),
    ("timeline", "주요 흐름"),
    ("perspectives", "쟁점과 관점"),
    ("todays_changes", "오늘 바뀐 점"),
]
REQUIRED = ("overview", "current_status", "timeline", "todays_changes")
SOURCES_HEADING = "## 출처"
RELATED_HEADING = "## 관련 주제"
CITE_MIN_IMPORTANCE = 3
EXCERPT_CHARS = 1500
FOOTNOTE_RE = re.compile(r"\[\^(\d+)\](?!:)")

SYSTEM_PROMPT = """당신은 개인용 주제별 위키의 편집자입니다. 한 주제의 위키 페이지를 새 글을 반영해 처음부터 다시 씁니다.
독자는 매일 이 페이지만 읽고 주제의 흐름을 파악하려 합니다. 원문을 다 읽지 않아도 되도록 정리해 주세요.

작성 규칙:
- 모든 내용은 한국어로 쓰고, Markdown 문단·목록을 사용할 수 있습니다(섹션 제목(#)은 쓰지 마세요).
- 사실을 담은 문장에는 근거 글의 각주를 [^글ID] 형식으로 붙입니다. 글ID는 입력에 주어진 숫자만 사용합니다.
- 기존 페이지의 내용을 근거 없이 지우거나 바꾸지 마세요. 새 글이 기존 내용과 다르면 둘 다 쓰고 차이를 설명합니다.
- 중요도가 3 이상인 새 글은 반드시 한 번 이상 인용합니다.
- 페이지 전체 길이 상한을 지킵니다. 넘칠 것 같으면 오래된 흐름부터 압축합니다.

섹션:
- overview: 이 주제가 무엇인지 1~2문장.
- current_status: 지금 시점의 핵심 정리.
- timeline: 시간 순서로 본 주요 사건과 변화. 날짜를 앞에 쓰고, 오래된 내용일수록 짧게 압축합니다.
- perspectives: 출처마다 시각이 다르면 비교. 비교할 관점이 없으면 빈 문자열.
- todays_changes: 이번에 새로 반영한 내용만 2~4개 항목으로 요약.
- related_topics: 함께 보면 좋은 다른 주제 이름(주어진 주제 목록에서만 고름)."""

SCHEMA = {
    "type": "object",
    "properties": {
        **{key: {"type": "string"} for key, _ in SECTIONS},
        "related_topics": {"type": "array", "items": {"type": "string"}},
    },
    "required": [key for key, _ in SECTIONS] + ["related_topics"],
    "additionalProperties": False,
}


@dataclass
class RewriteResult:
    topic_id: int
    status: str  # updated | no_new | failed
    revision_id: int | None = None
    errors: list[str] = field(default_factory=list)


def current_revision(conn: sqlite3.Connection, topic_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM wiki_revisions WHERE topic_id = ? AND is_current = 1", (topic_id,)
    ).fetchone()


def topic_article_rows(conn: sqlite3.Connection, topic_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT a.*, f.title AS feed_title, f.url AS feed_url FROM articles a "
        "JOIN article_topics at ON at.article_id = a.id JOIN feeds f ON f.id = a.feed_id "
        "WHERE at.topic_id = ? AND a.status = 'done' ORDER BY coalesce(a.published_at, a.collected_at)",
        (topic_id,),
    ).fetchall()


def new_article_ids(conn: sqlite3.Connection, topic_id: int) -> list[int]:
    rev = current_revision(conn, topic_id)
    reflected = set(json.loads(rev["article_ids"])) if rev else set()
    return [r["id"] for r in topic_article_rows(conn, topic_id) if r["id"] not in reflected]


def strip_generated(content: str) -> str:
    """LLM 입력용: 코드가 만든 관련 주제·출처 섹션을 뺀 본문."""
    for heading in (RELATED_HEADING, SOURCES_HEADING):
        idx = content.find("\n" + heading)
        if idx != -1:
            content = content[:idx]
    return content.strip()


def _body_markdown(sections: dict) -> str:
    parts = []
    for key, title in SECTIONS:
        text = (sections.get(key) or "").strip() or "_아직 정리할 내용이 없습니다._"
        parts.append(f"## {title}\n\n{text}")
    return "\n\n".join(parts)


def render_sources(conn: sqlite3.Connection, cited_ids: list[int]) -> str:
    lines = [SOURCES_HEADING, ""]
    for aid in cited_ids:
        a = conn.execute(
            "SELECT a.*, f.title AS feed_title, f.url AS feed_url FROM articles a JOIN feeds f ON f.id = a.feed_id "
            "WHERE a.id = ?", (aid,)
        ).fetchone()
        if a is None:
            continue
        date = (a["published_at"] or a["collected_at"])[:10]
        link = f"[{a['title'] or a['url']}]({a['url']})" if a["url"] else (a["title"] or str(aid))
        line = f"[^{aid}]: {link} — {a['feed_title'] or a['feed_url']}, {date}"
        dups = conn.execute(
            "SELECT a.url, f.title AS feed_title, f.url AS feed_url FROM articles a JOIN feeds f ON f.id = a.feed_id "
            "WHERE a.duplicate_of = ?", (aid,)
        ).fetchall()
        if dups:
            others = ", ".join(f"[{d['feed_title'] or d['feed_url']}]({d['url']})" for d in dups)
            line += f" (같은 소식: {others})"
        lines.append(line)
    return "\n".join(lines)


def cited_ids(text: str) -> list[int]:
    seen: list[int] = []
    for m in FOOTNOTE_RE.finditer(text):
        aid = int(m.group(1))
        if aid not in seen:
            seen.append(aid)
    return seen


def validate(sections: dict, *, allowed_ids: set[int], must_cite: set[int], max_chars: int) -> list[str]:
    errors = []
    for key in REQUIRED:
        if not (sections.get(key) or "").strip():
            errors.append(f"필수 섹션 '{dict(SECTIONS)[key]}'이(가) 비어 있습니다")
    body = _body_markdown(sections)
    cites = set(cited_ids(body))
    bad = sorted(cites - allowed_ids)
    if bad:
        errors.append(f"존재하지 않는 글ID를 인용했습니다: {bad}")
    missing = sorted(must_cite - cites)
    if missing:
        errors.append(f"새 글 중 인용되지 않은 글이 있습니다: {missing}")
    if len(body) > max_chars:
        errors.append(f"페이지 길이 {len(body)}자가 상한 {max_chars}자를 넘습니다")
    return errors


def _article_block(a: sqlite3.Row, with_excerpt: bool) -> str:
    points = "; ".join(json.loads(a["key_points"] or "[]"))
    text = (
        f"<article id=\"{a['id']}\" importance=\"{a['importance']}\">\n"
        f"제목: {a['title']}\n출처: {a['feed_title'] or a['feed_url']}\n"
        f"날짜: {(a['published_at'] or a['collected_at'])[:10]}\n요약: {a['summary']}\n핵심: {points}"
    )
    if with_excerpt:
        text += f"\n본문 발췌: {(a['content'] or '')[:EXCERPT_CHARS]}"
    return text + "\n</article>"


def build_user_message(
    conn: sqlite3.Connection, topic: sqlite3.Row, rows: list[sqlite3.Row], new_ids: list[int], max_chars: int
) -> str:
    rev = current_revision(conn, topic["id"])
    current = strip_generated(rev["content"]) if rev else "(아직 페이지가 없습니다. 새로 작성하세요.)"
    new_set = set(new_ids)
    old = [r for r in rows if r["id"] not in new_set]
    new = [r for r in rows if r["id"] in new_set]
    others = conn.execute(
        "SELECT name FROM topics WHERE id != ? AND status = 'active' AND merged_into IS NULL ORDER BY name",
        (topic["id"],),
    ).fetchall()
    return (
        f"<topic>\n이름: {topic['name']}\n설명: {topic['description']}\n</topic>\n\n"
        f"<page_limit>{max_chars}자</page_limit>\n\n"
        f"<current_page>\n{current}\n</current_page>\n\n"
        "<previous_articles>\n" + "\n".join(_article_block(r, False) for r in old) + "\n</previous_articles>\n\n"
        "<new_articles>\n" + "\n".join(_article_block(r, True) for r in new) + "\n</new_articles>\n\n"
        "<other_topics>\n" + ", ".join(o["name"] for o in others) + "\n</other_topics>"
    )


def assemble_page(conn: sqlite3.Connection, topic_id: int, sections: dict) -> str:
    body = _body_markdown(sections)
    related = []
    for name in sections.get("related_topics", []):
        row = conn.execute(
            "SELECT id, name FROM topics WHERE name = ? AND id != ? AND merged_into IS NULL", (name.strip(), topic_id)
        ).fetchone()
        if row:
            related.append(f"- [{row['name']}](/topics/{row['id']})")
    page = f"{body}\n\n{RELATED_HEADING}\n\n" + ("\n".join(related) or "_없음_")
    return f"{page}\n\n{render_sources(conn, cited_ids(body))}\n"


def save_revision(
    conn: sqlite3.Connection, topic_id: int, content: str, article_ids: list[int], new_ids: list[int], model: str | None
) -> int:
    conn.execute("UPDATE wiki_revisions SET is_current = 0 WHERE topic_id = ?", (topic_id,))
    rid = conn.execute(
        "INSERT INTO wiki_revisions(topic_id, content, article_ids, new_article_ids, model, created_at, is_current) "
        "VALUES (?, ?, ?, ?, ?, ?, 1)",
        (topic_id, content, json.dumps(sorted(article_ids)), json.dumps(sorted(new_ids)), model, utcnow()),
    ).lastrowid
    conn.commit()
    return rid


def rewrite_topic(conn: sqlite3.Connection, llm: LLMClient, topic_id: int, config: Config) -> RewriteResult:
    topic = conn.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
    new_ids = new_article_ids(conn, topic_id)
    if not new_ids:
        return RewriteResult(topic_id, "no_new")

    rows = topic_article_rows(conn, topic_id)
    by_id = {r["id"]: r for r in rows}
    allowed = set(by_id)
    must_cite = {i for i in new_ids if (by_id[i]["importance"] or 0) >= CITE_MIN_IMPORTANCE}
    max_chars = int(get_setting(conn, "page_max_chars"))
    user = build_user_message(conn, topic, rows, new_ids, max_chars)

    errors: list[str] = []
    for attempt in range(2):  # 검증 실패 시 사유를 알려주고 1회 재시도
        prompt = user
        if errors:
            prompt += "\n\n<previous_attempt_errors>\n" + "\n".join(f"- {e}" for e in errors) + \
                "\n위 문제를 고쳐서 다시 작성하세요.\n</previous_attempt_errors>"
        try:
            sections = llm.complete_json(
                model=config.wiki_model, purpose="wiki_rewrite", system=SYSTEM_PROMPT, user=prompt,
                schema=SCHEMA, max_tokens=8000, effort="medium",
            )
        except BudgetExceeded:
            raise
        except LLMError as e:
            errors = [f"LLM 호출 실패: {e}"]
            continue
        errors = validate(sections, allowed_ids=allowed, must_cite=must_cite, max_chars=max_chars)
        if not errors:
            content = assemble_page(conn, topic_id, sections)
            rev = current_revision(conn, topic_id)
            reflected = set(json.loads(rev["article_ids"])) if rev else set()
            rid = save_revision(conn, topic_id, content, sorted(reflected | set(new_ids)), new_ids, config.wiki_model)
            return RewriteResult(topic_id, "updated", rid)
    log.warning("위키 재작성 실패 (topic %s): %s", topic_id, errors)
    return RewriteResult(topic_id, "failed", errors=errors)


def list_revisions(conn: sqlite3.Connection, topic_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, created_at, model, is_current, new_article_ids FROM wiki_revisions WHERE topic_id = ? "
        "ORDER BY id DESC", (topic_id,)
    ).fetchall()


def set_current_revision(conn: sqlite3.Connection, topic_id: int, revision_id: int) -> None:
    """특정 리비전으로 되돌린다. 이후 배치에서는 그 리비전 이후의 글이 다시 새 글로 반영된다."""
    row = conn.execute(
        "SELECT id FROM wiki_revisions WHERE id = ? AND topic_id = ?", (revision_id, topic_id)
    ).fetchone()
    if row is None:
        raise ValueError("해당 주제의 리비전이 아닙니다")
    conn.execute("UPDATE wiki_revisions SET is_current = 0 WHERE topic_id = ?", (topic_id,))
    conn.execute("UPDATE wiki_revisions SET is_current = 1 WHERE id = ?", (revision_id,))
    conn.commit()


def revision_diff(conn: sqlite3.Connection, revision_id: int) -> str:
    """직전 리비전과의 unified diff."""
    rev = conn.execute("SELECT * FROM wiki_revisions WHERE id = ?", (revision_id,)).fetchone()
    if rev is None:
        raise ValueError("리비전이 없습니다")
    prev = conn.execute(
        "SELECT * FROM wiki_revisions WHERE topic_id = ? AND id < ? ORDER BY id DESC LIMIT 1",
        (rev["topic_id"], revision_id),
    ).fetchone()
    before = prev["content"].splitlines() if prev else []
    return "\n".join(difflib.unified_diff(
        before, rev["content"].splitlines(),
        fromfile=f"rev {prev['id']}" if prev else "(없음)", tofile=f"rev {rev['id']}", lineterm="",
    ))
