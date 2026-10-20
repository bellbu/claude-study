"""APScheduler: 수집은 N분마다, 위키 갱신은 매일 지정 시각. 주기는 settings 테이블에서 읽는다."""

from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from rss_wiki.config import Config
from rss_wiki.db import connect, get_all_settings
from rss_wiki.runner import Services, start_job


def _triggers(config: Config) -> tuple[IntervalTrigger, CronTrigger]:
    conn = connect(config.db_path)
    try:
        s = get_all_settings(conn)
    finally:
        conn.close()
    return (
        IntervalTrigger(minutes=int(s["collect_interval_minutes"])),
        CronTrigger(hour=int(s["wiki_hour"]), minute=int(s["wiki_minute"])),
    )


def build_scheduler(config: Config, services: Services | None = None) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600})
    collect, wiki = _triggers(config)
    scheduler.add_job(start_job, collect, id="collect", args=[config, "collect", services], kwargs={"background": False})
    scheduler.add_job(start_job, wiki, id="wiki", args=[config, "wiki", services], kwargs={"background": False})
    return scheduler


def reschedule(scheduler: BackgroundScheduler, config: Config) -> None:
    """설정 화면에서 주기를 바꾸면 호출된다."""
    collect, wiki = _triggers(config)
    scheduler.reschedule_job("collect", trigger=collect)
    scheduler.reschedule_job("wiki", trigger=wiki)
