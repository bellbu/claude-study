"""주제 조회·생성, 자동 정리(병합·이름 변경·보관)와 되돌리기."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from rss_wiki.db import get_setting, utcnow

if TYPE_CHECKING:
    from rss_wiki.config import Config
    from rss_wiki.llm import LLMClient

log = logging.getLogger(__name__)


class TopicError(Exception):
    pass


def norm_name(name: str) -> str:
    return re.sub(r"\s+", "", name).lower()


def resolve_topic(conn: sqlite3.Connection, topic_id: int) -> int:
    """병합된 주제는 최종 병합 대상 id로 따라간다."""
    seen = set()
    while topic_id not in seen:
        seen.add(topic_id)
        row = conn.execute("SELECT merged_into FROM topics WHERE id = ?", (topic_id,)).fetchone()
        if row is None or row["merged_into"] is None:
            return topic_id
        topic_id = row["merged_into"]
    return topic_id


def find_topic(conn: sqlite3.Connection, name: str) -> int | None:
    key = norm_name(name)
    for row in conn.execute("SELECT id, name FROM topics"):
        if norm_name(row["name"]) == key:
            return resolve_topic(conn, row["id"])
    return None


def _log_change(conn: sqlite3.Connection, type_: str, topic_id: int, before, after, source: str) -> int:
    return conn.execute(
        "INSERT INTO topic_changes(type, topic_id, before, after, source, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (type_, topic_id, json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False), source, utcnow()),
    ).lastrowid


def get_or_create_topic(conn: sqlite3.Connection, name: str, description: str = "") -> tuple[int, bool]:
    """(topic_id, 새로 만들었는지)를 반환한다. 보관된 주제에 새 글이 오면 다시 활성화한다."""
    name = name.strip()
    tid = find_topic(conn, name)
    if tid is not None:
        row = conn.execute("SELECT status FROM topics WHERE id = ?", (tid,)).fetchone()
        if row["status"] == "archived":
            conn.execute("UPDATE topics SET status = 'active' WHERE id = ?", (tid,))
            _log_change(conn, "unarchive", tid, "archived", "active", "auto")
        return tid, False
    cur = conn.execute(
        "INSERT INTO topics(name, description, created_at) VALUES (?, ?, ?)", (name, description.strip(), utcnow())
    )
    return cur.lastrowid, True


def topic_catalog(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """분류 프롬프트에 넣을 주제 목록 (병합·숨김 제외)."""
    return conn.execute(
        "SELECT id, name, description FROM topics WHERE merged_into IS NULL AND status IN ('active', 'archived') "
        "ORDER BY coalesce(last_article_at, created_at) DESC"
    ).fetchall()


def _live(conn: sqlite3.Connection, topic_id: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
    if row is None or row["merged_into"] is not None:
        raise TopicError(f"주제 {topic_id}을(를) 찾을 수 없습니다")
    return row


def merge_topics(conn: sqlite3.Connection, source_id: int, target_id: int, source: str = "auto") -> int:
    """source 주제의 글을 target으로 옮기고 source를 target에 병합한다. 변경 로그 id 반환."""
    if source_id == target_id:
        raise TopicError("같은 주제끼리는 병합할 수 없습니다")
    src = _live(conn, source_id)
    _live(conn, target_id)
    links = conn.execute(
        "SELECT article_id, is_primary FROM article_topics WHERE topic_id = ?", (source_id,)
    ).fetchall()
    existing = {r[0] for r in conn.execute("SELECT article_id FROM article_topics WHERE topic_id = ?", (target_id,))}
    added = []
    for link in links:
        if link["article_id"] not in existing:
            conn.execute(
                "INSERT INTO article_topics(article_id, topic_id, is_primary) VALUES (?, ?, ?)",
                (link["article_id"], target_id, link["is_primary"]),
            )
            added.append(link["article_id"])
    conn.execute("DELETE FROM article_topics WHERE topic_id = ?", (source_id,))
    conn.execute("UPDATE topics SET merged_into = ? WHERE id = ?", (target_id, source_id))
    if src["last_article_at"]:
        conn.execute(
            "UPDATE topics SET last_article_at = ? WHERE id = ? AND (last_article_at IS NULL OR last_article_at < ?)",
            (src["last_article_at"], target_id, src["last_article_at"]),
        )
    before = {"name": src["name"], "links": [[r["article_id"], r["is_primary"]] for r in links], "added": added}
    cid = _log_change(conn, "merge", source_id, before, {"target_id": target_id}, source)
    conn.commit()
    return cid


def rename_topic(conn: sqlite3.Connection, topic_id: int, new_name: str, source: str = "user") -> int | None:
    """이름 변경. 사용자가 바꾼 주제는 고정되어 자동 정리가 이름을 바꾸지 않는다."""
    row = _live(conn, topic_id)
    new_name = new_name.strip()
    if not new_name or new_name == row["name"]:
        return None
    if source == "auto" and row["user_locked"]:
        return None
    other = find_topic(conn, new_name)
    if other is not None and other != topic_id:
        raise TopicError(f"이미 있는 주제 이름입니다: {new_name}")
    locked = 1 if source == "user" else row["user_locked"]
    conn.execute("UPDATE topics SET name = ?, user_locked = ? WHERE id = ?", (new_name, locked, topic_id))
    cid = _log_change(conn, "rename", topic_id, row["name"], new_name, source)
    conn.commit()
    return cid


def set_topic_status(conn: sqlite3.Connection, topic_id: int, status: str, source: str = "user") -> int | None:
    row = _live(conn, topic_id)
    if row["status"] == status:
        return None
    type_ = {"hidden": "hide", "archived": "archive", "active": "unarchive"}[status]
    conn.execute("UPDATE topics SET status = ? WHERE id = ?", (status, topic_id))
    cid = _log_change(conn, type_, topic_id, row["status"], status, source)
    conn.commit()
    return cid


def archive_inactive(conn: sqlite3.Connection, days: int | None = None) -> list[int]:
    days = days if days is not None else int(get_setting(conn, "archive_after_days"))
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
    rows = conn.execute(
        "SELECT id FROM topics WHERE status = 'active' AND merged_into IS NULL "
        "AND coalesce(last_article_at, created_at) < ?", (cutoff,)
    ).fetchall()
    for r in rows:
        set_topic_status(conn, r["id"], "archived", source="auto")
    return [r["id"] for r in rows]


def revert_change(conn: sqlite3.Connection, change_id: int) -> None:
    ch = conn.execute("SELECT * FROM topic_changes WHERE id = ?", (change_id,)).fetchone()
    if ch is None or ch["reverted"]:
        raise TopicError("되돌릴 수 없는 변경입니다")
    before, after = json.loads(ch["before"]), json.loads(ch["after"])
    tid = ch["topic_id"]
    if ch["type"] == "merge":
        target = after["target_id"]
        conn.execute("UPDATE topics SET merged_into = NULL WHERE id = ?", (tid,))
        for aid, primary in before["links"]:
            conn.execute(
                "INSERT OR IGNORE INTO article_topics(article_id, topic_id, is_primary) VALUES (?, ?, ?)",
                (aid, tid, primary),
            )
        if before["added"]:
            marks = ",".join("?" * len(before["added"]))
            conn.execute(
                f"DELETE FROM article_topics WHERE topic_id = ? AND article_id IN ({marks})", (target, *before["added"])
            )
    elif ch["type"] == "rename":
        conn.execute("UPDATE topics SET name = ? WHERE id = ?", (before, tid))
    else:
        conn.execute("UPDATE topics SET status = ? WHERE id = ?", (before, tid))
    conn.execute("UPDATE topic_changes SET reverted = 1 WHERE id = ?", (change_id,))
    conn.commit()


MAINTAIN_SYSTEM = """당신은 개인용 주제별 위키의 편집장입니다. 자동으로 만들어진 주제 목록을 점검해 정리합니다.
- merges: 사실상 같은 범위를 다루는 주제 쌍만 병합합니다. 글이 적거나 범위가 좁은 쪽을 source, 남길 쪽을 target으로 둡니다.
  관련은 있지만 범위가 다른 주제(예: "엔비디아"와 "AI 반도체")는 병합하지 않습니다.
- renames: 이름이 너무 좁거나(특정 사건 하나) 모호한 주제만 더 적절한 짧은 한국어 명사구로 바꿉니다.
- 확신이 없으면 아무것도 하지 않습니다. 빈 목록도 정상적인 답입니다.
- 주제 id는 입력에 있는 숫자만 사용합니다."""

MAINTAIN_SCHEMA = {
    "type": "object",
    "properties": {
        "merges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source_id": {"type": "integer"}, "target_id": {"type": "integer"}, "reason": {"type": "string"},
                },
                "required": ["source_id", "target_id", "reason"],
                "additionalProperties": False,
            },
        },
        "renames": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "topic_id": {"type": "integer"}, "new_name": {"type": "string"}, "reason": {"type": "string"},
                },
                "required": ["topic_id", "new_name", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["merges", "renames"],
    "additionalProperties": False,
}


def _maintain_prompt(conn: sqlite3.Connection, topics: list[sqlite3.Row]) -> str:
    blocks = []
    for t in topics:
        titles = [r[0] for r in conn.execute(
            "SELECT a.title FROM articles a JOIN article_topics at ON at.article_id = a.id "
            "WHERE at.topic_id = ? ORDER BY a.id DESC LIMIT 3", (t["id"],)
        )]
        count = conn.execute("SELECT count(*) FROM article_topics WHERE topic_id = ?", (t["id"],)).fetchone()[0]
        blocks.append(
            f'<topic id="{t["id"]}" articles="{count}">\n'
            f'이름: {t["name"]}\n설명: {t["description"]}\n최근 글: {" / ".join(titles)}\n</topic>'
        )
    return "\n".join(blocks)


def auto_maintain(conn: sqlite3.Connection, llm: LLMClient, config: Config) -> dict:
    """LLM 판단으로 병합·이름 변경을 적용하고, 오래 조용한 주제를 보관한다."""
    from rss_wiki.llm import BudgetExceeded, LLMError

    stats: dict = {"merged": 0, "renamed": 0, "archived": 0}
    topics = conn.execute(
        "SELECT * FROM topics WHERE status = 'active' AND merged_into IS NULL ORDER BY id"
    ).fetchall()
    if len(topics) >= 2:
        try:
            plan = llm.complete_json(
                model=config.wiki_model, purpose="topic_maintenance", system=MAINTAIN_SYSTEM,
                user=_maintain_prompt(conn, topics), schema=MAINTAIN_SCHEMA, max_tokens=4000, effort="medium",
            )
        except BudgetExceeded:
            raise
        except LLMError as e:
            log.warning("주제 정리 실패: %s", e)
            stats["error"] = str(e)
            plan = {"merges": [], "renames": []}
        by_id = {t["id"]: t for t in topics}
        for m in plan.get("merges", []):
            src, dst = by_id.get(m["source_id"]), by_id.get(m["target_id"])
            if not src or not dst or src["user_locked"]:
                continue  # 사용자가 고정한 주제는 자동으로 없애지 않는다
            try:
                merge_topics(conn, src["id"], resolve_topic(conn, dst["id"]), source="auto")
                stats["merged"] += 1
            except TopicError as e:
                log.info("병합 건너뜀: %s", e)
        for r in plan.get("renames", []):
            if r["topic_id"] not in by_id:
                continue
            try:
                if rename_topic(conn, r["topic_id"], r["new_name"], source="auto"):
                    stats["renamed"] += 1
            except TopicError as e:
                log.info("이름 변경 건너뜀: %s", e)
    stats["archived"] = len(archive_inactive(conn))
    return stats
