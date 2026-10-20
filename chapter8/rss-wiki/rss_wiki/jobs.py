"""작업 실행: 수집 작업(1시간)과 위키 배치(하루 1회). 모든 실행은 job_runs에 기록한다."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from typing import Iterator

import httpx

from rss_wiki.config import Config
from rss_wiki.db import utcnow
from rss_wiki.dedup import store_entries
from rss_wiki.extractor import apply_extraction, fetch_and_extract
from rss_wiki.fetcher import fetch_all
from rss_wiki.llm import BudgetExceeded, LLMClient
from rss_wiki.summarizer import process_article
from rss_wiki.topics import auto_maintain
from rss_wiki.wiki import new_article_ids, rewrite_topic

log = logging.getLogger(__name__)

_locks = {"collect": threading.Lock(), "wiki": threading.Lock()}


class JobAlreadyRunning(Exception):
    pass


def is_running(job_type: str) -> bool:
    return _locks[job_type].locked()


@contextmanager
def job_run(conn: sqlite3.Connection, job_type: str) -> Iterator[tuple[int, dict]]:
    """job_runs 레코드를 열고 닫는다. 같은 종류의 작업은 동시에 하나만 실행한다."""
    lock = _locks[job_type]
    if not lock.acquire(blocking=False):
        raise JobAlreadyRunning(job_type)
    run_id = conn.execute(
        "INSERT INTO job_runs(job_type, started_at) VALUES (?, ?)", (job_type, utcnow())
    ).lastrowid
    conn.commit()
    stats: dict = {}
    status = "ok"
    try:
        yield run_id, stats
        status = stats.pop("_status", "ok")
    except Exception as e:
        log.exception("%s 작업 실패", job_type)
        status = "error"
        stats["error"] = f"{type(e).__name__}: {e}"
    finally:
        conn.execute(
            "UPDATE job_runs SET finished_at = ?, status = ?, stats = ? WHERE id = ?",
            (utcnow(), status, json.dumps(stats, ensure_ascii=False), run_id),
        )
        conn.commit()
        lock.release()


def run_collect(conn: sqlite3.Connection, config: Config, http: httpx.Client, llm: LLMClient) -> dict:
    """수집 → 중복 제거 → 본문 추출 → 요약·분류."""
    with job_run(conn, "collect") as (run_id, stats):
        llm.job_run_id = run_id
        by_feed, fetch_stats = fetch_all(conn, http, config)
        stats.update(fetch_stats)
        stats["new_articles"] = sum(len(store_entries(conn, fid, entries)) for fid, entries in by_feed.items())

        # 본문이 없는 대기 글: 원문 요청은 스레드로, DB 반영은 이 스레드에서
        need_body = conn.execute(
            "SELECT id, url FROM articles WHERE status = 'pending' AND content IS NULL ORDER BY id"
        ).fetchall()
        with ThreadPoolExecutor(max_workers=config.fetch_concurrency) as pool:
            texts = list(pool.map(lambda r: fetch_and_extract(r["url"], http), need_body))
        sources = [apply_extraction(conn, r["id"], text, config) for r, text in zip(need_body, texts)]
        stats["extracted"] = sources.count("extracted")
        stats["rss_fallback"] = sources.count("rss_fallback")
        stats["late_duplicates"] = sources.count("duplicate")

        counts = {"done": 0, "skipped": 0, "pending": 0, "failed": 0}
        pending = [r["id"] for r in conn.execute("SELECT id FROM articles WHERE status = 'pending' ORDER BY id")]
        try:
            for aid in pending:
                counts[process_article(conn, llm, aid, config)] += 1
        except BudgetExceeded:
            stats["budget_exceeded"] = True
            stats["_status"] = "budget_exceeded"
        stats.update({f"summarize_{k}": v for k, v in counts.items()})
    return stats


def run_wiki(conn: sqlite3.Connection, config: Config, llm: LLMClient) -> dict:
    """주제 정리 → 새 글이 있는 주제만 재작성 (새 글이 많은 주제부터)."""
    with job_run(conn, "wiki") as (run_id, stats):
        llm.job_run_id = run_id
        try:
            stats["topics"] = auto_maintain(conn, llm, config)
            topics = conn.execute(
                "SELECT id FROM topics WHERE status = 'active' AND merged_into IS NULL"
            ).fetchall()
            queue = sorted(
                ((t["id"], len(new_article_ids(conn, t["id"]))) for t in topics),
                key=lambda x: x[1], reverse=True,
            )
            updated, failed = [], {}
            stats["updated"], stats["failed"] = updated, failed
            for tid, n_new in queue:
                if n_new == 0:
                    continue
                res = rewrite_topic(conn, llm, tid, config)
                if res.status == "updated":
                    updated.append(tid)
                elif res.status == "failed":
                    failed[str(tid)] = res.errors
        except BudgetExceeded:
            stats["budget_exceeded"] = True
            stats["_status"] = "budget_exceeded"
    return stats
