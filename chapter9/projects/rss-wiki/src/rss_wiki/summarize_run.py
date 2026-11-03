"""요약 실행: 대상 선정, 실행 내 재시도, 실패 고정, DB 기록 (PRD 7장).

LLM은 `Summarizer` 프로토콜로만 접근한다. `summaries.attempts`는 누적 실패 횟수(실행 단위)이며
한 실행 안의 재시도는 합쳐서 실패 1회로 센다.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime

from rss_wiki.db import DatabaseError
from rss_wiki.fetch import MAX_STATUS_CHARS
from rss_wiki.summarize import Summarizer, SummarizerError, SummaryResult, SummaryValidationError

logger = logging.getLogger(__name__)


@dataclass
class SummarizeOutcome:
    article_id: int
    ok: bool
    error: str | None = None


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _truncate(message: str) -> str:
    if len(message) > MAX_STATUS_CHARS:
        return message[:MAX_STATUS_CHARS] + "…"
    return message


def _rollback(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("ROLLBACK")
    except sqlite3.Error:
        pass


def select_targets(
    conn: sqlite3.Connection, *, limit: int | None = None, retry_failed: bool = False
) -> list[sqlite3.Row]:
    """요약 대상 글: summaries 행이 없거나 pending (retry_failed면 failed도). id 오름차순."""
    statuses = ("pending", "failed") if retry_failed else ("pending",)
    marks = ", ".join("?" for _ in statuses)
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    return cur.execute(
        "SELECT a.id, a.title, a.url, a.content FROM articles a"
        " LEFT JOIN summaries s ON s.article_id = a.id"
        f" WHERE s.article_id IS NULL OR s.status IN ({marks})"
        " ORDER BY a.id LIMIT ?",
        (*statuses, -1 if limit is None else limit),
    ).fetchall()


def load_tag_names(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT name FROM tags ORDER BY name")]


def _call_with_retry(
    summarizer: Summarizer,
    article,
    existing_tags: list[str],
    max_retries: int,
    sleep: Callable[[float], None],
    backoff_base: float,
) -> SummaryResult:
    """일시적 SummarizerError만 재시도한다(총 1 + max_retries회). 그 외 예외는 그대로 던진다."""
    for i in range(max_retries + 1):
        try:
            return summarizer.summarize(article["title"], article["content"] or "", list(existing_tags))
        except SummarizerError as exc:
            if not exc.transient or i == max_retries:
                raise
            delay = backoff_base * 2**i
            logger.debug(
                "요약 재시도 (article id=%s, %d/%d, 대기 %s초): %s", article["id"], i + 1, max_retries, delay, exc
            )
            sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover


def _store_success(conn: sqlite3.Connection, article_id: int, model: str, result: SummaryResult) -> None:
    conn.execute("BEGIN")
    try:
        conn.execute(
            "INSERT INTO summaries (article_id, status, tldr, key_points, model, attempts, last_error, summarized_at)"
            " VALUES (?, 'done', ?, ?, ?, 0, NULL, ?)"
            " ON CONFLICT(article_id) DO UPDATE SET status = 'done', tldr = excluded.tldr,"
            " key_points = excluded.key_points, model = excluded.model, last_error = NULL,"
            " summarized_at = excluded.summarized_at",
            (article_id, result.tldr, json.dumps(result.key_points, ensure_ascii=False), model, _now()),
        )
        conn.execute("DELETE FROM article_tags WHERE article_id = ?", (article_id,))
        for name in result.tags:
            conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
            tag_id = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()[0]
            conn.execute(
                "INSERT OR IGNORE INTO article_tags (article_id, tag_id) VALUES (?, ?)", (article_id, tag_id)
            )
        conn.execute("COMMIT")
    except BaseException:
        _rollback(conn)
        raise


def _store_failure(conn: sqlite3.Connection, article_id: int, message: str, max_failures: int) -> None:
    conn.execute(
        "INSERT INTO summaries (article_id, status, attempts, last_error)"
        " VALUES (?, CASE WHEN 1 >= ? THEN 'failed' ELSE 'pending' END, 1, ?)"
        " ON CONFLICT(article_id) DO UPDATE SET attempts = attempts + 1, last_error = excluded.last_error,"
        " status = CASE WHEN attempts + 1 >= ? THEN 'failed' ELSE 'pending' END",
        (article_id, max_failures, message, max_failures),
    )


def _record(
    conn: sqlite3.Connection,
    summarizer: Summarizer,
    article,
    existing_tags: list[str],
    result: SummaryResult | None,
    error: Exception | None,
    max_failures: int,
) -> SummarizeOutcome:
    """LLM 호출 결과(성공 result 또는 요약 실패 error)를 DB에 기록한다. 메인 스레드에서만 호출."""
    article_id = article["id"]
    if error is not None:
        message = _truncate(str(error))
        url = article["url"] if "url" in article.keys() else "-"
        logger.warning("요약 실패 (article id=%s, %s): %s", article_id, url, error)
        try:
            _store_failure(conn, article_id, message, max_failures)
        except sqlite3.Error as db_exc:
            raise DatabaseError(f"요약 저장 실패 (article id={article_id}): {db_exc}") from db_exc
        return SummarizeOutcome(article_id, ok=False, error=message)

    assert result is not None
    try:
        _store_success(conn, article_id, summarizer.model, result)
    except sqlite3.Error as exc:
        raise DatabaseError(f"요약 저장 실패 (article id={article_id}): {exc}") from exc
    for tag in result.tags:
        if tag not in existing_tags:
            existing_tags.append(tag)
    logger.info("요약 완료 (article id=%s, 태그 %s)", article_id, ", ".join(result.tags))
    return SummarizeOutcome(article_id, ok=True)


def _call_safely(
    summarizer: Summarizer, article, tags: list[str], max_retries: int, sleep, backoff_base: float
) -> tuple[SummaryResult | None, Exception | None]:
    """LLM 호출부(스레드에서 실행). 요약 실패는 값으로 돌려주고 그 외 예외는 그대로 던진다."""
    try:
        return _call_with_retry(summarizer, article, tags, max_retries, sleep, backoff_base), None
    except (SummarizerError, SummaryValidationError) as exc:
        return None, exc


def summarize_article(
    conn: sqlite3.Connection,
    summarizer: Summarizer,
    article,
    existing_tags: list[str],
    *,
    max_retries: int = 3,
    max_failures: int = 5,
    sleep: Callable[[float], None] = time.sleep,
    backoff_base: float = 1.0,
) -> SummarizeOutcome:
    """글 하나를 요약해 기록한다. 요약 실패는 예외 대신 결과와 DB 기록으로 남기고,
    DB 오류(sqlite3.Error)만 `DatabaseError`로 던진다. 성공하면 새 태그를 existing_tags에 추가한다."""
    result, error = _call_safely(summarizer, article, existing_tags, max_retries, sleep, backoff_base)
    return _record(conn, summarizer, article, existing_tags, result, error, max_failures)


def summarize_pending(
    conn: sqlite3.Connection,
    summarizer: Summarizer,
    *,
    limit: int | None = None,
    retry_failed: bool = False,
    max_retries: int = 3,
    max_failures: int = 5,
    sleep: Callable[[float], None] = time.sleep,
    on_outcome: Callable[[sqlite3.Row, SummarizeOutcome], None] | None = None,
    concurrency: int = 1,
) -> list[SummarizeOutcome]:
    """대상 글을 요약한다. LLM 호출은 스레드풀(concurrency)에서 병렬로 하고,
    DB 기록과 on_outcome은 메인 스레드에서 id 오름차순으로 하나씩 처리한다."""
    if concurrency < 1:
        raise ValueError("concurrency는 1 이상이어야 합니다")
    targets = select_targets(conn, limit=limit, retry_failed=retry_failed)
    tags = load_tag_names(conn)
    outcomes = []
    if concurrency == 1:  # 순차: 앞 글의 새 태그가 다음 글 힌트에 바로 반영됨(기존 동작)
        for a in targets:
            outcome = summarize_article(
                conn, summarizer, a, tags, max_retries=max_retries, max_failures=max_failures, sleep=sleep
            )
            outcomes.append(outcome)
            if on_outcome is not None:
                on_outcome(a, outcome)
        return outcomes
    executor = ThreadPoolExecutor(max_workers=concurrency)
    try:
        futures = [
            executor.submit(_call_safely, summarizer, a, list(tags), max_retries, sleep, 1.0) for a in targets
        ]
        for a, fut in zip(targets, futures):
            result, error = fut.result()
            outcome = _record(conn, summarizer, a, tags, result, error, max_failures)
            outcomes.append(outcome)
            if on_outcome is not None:
                on_outcome(a, outcome)
    except KeyboardInterrupt:  # 실행 중인 호출을 기다리지 않고 바로 종료
        executor.shutdown(wait=False, cancel_futures=True)
        raise
    except BaseException:
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    executor.shutdown(wait=True)
    return outcomes
