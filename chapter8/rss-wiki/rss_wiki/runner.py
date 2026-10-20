"""작업 실행 진입점. 스케줄러와 UI의 수동 실행이 함께 쓴다. 작업마다 자체 DB 연결을 연다."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

from rss_wiki.config import Config
from rss_wiki.db import connect
from rss_wiki.fetcher import make_client
from rss_wiki.jobs import JobAlreadyRunning, is_running, run_collect, run_wiki
from rss_wiki.llm import LLMClient

log = logging.getLogger(__name__)

Services = dict[str, Callable[[], Any]]
START_WAIT_SECONDS = 2.0


def run_job(config: Config, job_type: str, services: Services | None = None) -> dict | None:
    services = services or {}
    conn = connect(config.db_path)
    http = services["http"]() if "http" in services else make_client(config)
    anthropic_client = services["anthropic"]() if "anthropic" in services else None
    llm = LLMClient(conn, config, anthropic_client)
    try:
        if job_type == "collect":
            return run_collect(conn, config, http, llm)
        if job_type == "wiki":
            return run_wiki(conn, config, llm)
        raise ValueError(job_type)
    except JobAlreadyRunning:
        log.info("%s 작업이 이미 실행 중입니다", job_type)
        return None
    finally:
        http.close()
        conn.close()


def start_job(config: Config, job_type: str, services: Services | None = None, background: bool = True) -> bool:
    """작업을 시작한다. 이미 실행 중이면 False."""
    if is_running(job_type):
        return False
    if background:
        thread = threading.Thread(target=run_job, args=(config, job_type, services), daemon=True, name=f"job-{job_type}")
        thread.start()
        # 화면이 바로 '실행 중'을 보여주도록 작업이 잠금을 잡을 때까지 잠깐 기다린다
        deadline = time.monotonic() + START_WAIT_SECONDS
        while not is_running(job_type) and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
    else:
        run_job(config, job_type, services)
    return True
