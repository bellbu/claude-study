"""DB 조회만으로 피드·글·요약 상태 건수를 집계한다 (HTTP·LLM 비의존)."""

import sqlite3
from dataclasses import dataclass

from rss_wiki.db import DatabaseError


@dataclass(frozen=True)
class StatusCounts:
    feeds: int
    feeds_error: int
    feeds_never: int
    articles: int
    pending: int
    pending_retrying: int
    done: int
    failed: int


def collect_status(conn: sqlite3.Connection) -> StatusCounts:
    """건수를 집계한다. `pending`은 summarize_run.select_targets 기본 조건(요약 행 없음 또는 pending)과 같다."""
    try:
        feeds, feeds_error, feeds_never = conn.execute(
            "SELECT COUNT(*),"
            " COALESCE(SUM(last_status LIKE 'error:%'), 0),"
            " COALESCE(SUM(last_fetched_at IS NULL), 0)"
            " FROM feeds"
        ).fetchone()
        articles, pending, retrying, done, failed = conn.execute(
            "SELECT COUNT(*),"
            " COALESCE(SUM(s.article_id IS NULL OR s.status = 'pending'), 0),"
            " COALESCE(SUM(s.status = 'pending' AND s.attempts > 0), 0),"
            " COALESCE(SUM(s.status = 'done'), 0),"
            " COALESCE(SUM(s.status = 'failed'), 0)"
            " FROM articles a LEFT JOIN summaries s ON s.article_id = a.id"
        ).fetchone()
    except sqlite3.Error as exc:
        raise DatabaseError(f"상태 조회 실패: {exc}") from exc
    return StatusCounts(feeds, feeds_error, feeds_never, articles, pending, retrying, done, failed)
