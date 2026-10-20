"""글·피드·검색·작업·설정 화면."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response

from rss_wiki.config import DEFAULT_SETTINGS
from rss_wiki.db import get_all_settings, set_setting
from rss_wiki.feeds import FeedError, add_feed, delete_feed, export_opml, import_opml, list_feeds, set_feed_status
from rss_wiki.fetcher import make_client
from rss_wiki.jobs import is_running
from rss_wiki.llm import spent_today, usage_summary
from rss_wiki.runner import start_job
from rss_wiki.search import search

PAGE_SIZE = 50
STATUSES = ("pending", "done", "skipped", "failed", "duplicate")

# 설정 키: (표시 이름, 최소, 최대, 정수 여부)
SETTING_RULES = {
    "collect_interval_minutes": ("수집 주기(분)", 10, 1440, True),
    "wiki_hour": ("위키 갱신 시각(시)", 0, 23, True),
    "wiki_minute": ("위키 갱신 시각(분)", 0, 59, True),
    "daily_budget_usd": ("일일 비용 상한(USD)", 0, 1000, False),
    "page_max_chars": ("페이지 길이 상한(자)", 1000, 20000, True),
    "archive_after_days": ("보관 기준일(일)", 1, 365, True),
}


def opt_int(value: str | None) -> int | None:
    """폼의 빈 select 값("")은 필터 없음으로 본다."""
    try:
        return int(value) if value not in (None, "") else None
    except ValueError:
        return None


def register(app: FastAPI) -> None:
    from rss_wiki.web.app import redirect

    get_conn = app.state.get_conn
    page = app.state.page
    config = app.state.config
    services = app.state.services

    # ---------- 글 ----------
    @app.get("/articles", response_class=HTMLResponse)
    def articles(
        request: Request,
        status: str | None = None,
        feed_id: str | None = None,
        topic_id: str | None = None,
        page_no: str | None = None,
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        feed_id, topic_id = opt_int(feed_id), opt_int(topic_id)
        page_no = opt_int(page_no) or 1
        where, params = [], []
        if status in STATUSES:
            where.append("a.status = ?")
            params.append(status)
        if feed_id:
            where.append("a.feed_id = ?")
            params.append(feed_id)
        if topic_id:
            where.append("a.id IN (SELECT article_id FROM article_topics WHERE topic_id = ?)")
            params.append(topic_id)
        clause = ("WHERE " + " AND ".join(where)) if where else ""
        page_no = max(1, page_no)
        rows = conn.execute(
            "SELECT a.id, a.title, a.url, a.status, a.importance, a.published_at, a.collected_at, a.content_source, "
            "f.title AS feed_title, f.url AS feed_url, "
            "(SELECT group_concat(t.name, ', ') FROM article_topics at JOIN topics t ON t.id = at.topic_id "
            " WHERE at.article_id = a.id) AS topic_names "
            f"FROM articles a JOIN feeds f ON f.id = a.feed_id {clause} "
            "ORDER BY coalesce(a.published_at, a.collected_at) DESC LIMIT ? OFFSET ?",
            [*params, PAGE_SIZE + 1, (page_no - 1) * PAGE_SIZE],
        ).fetchall()
        counts = dict(conn.execute("SELECT status, count(*) FROM articles GROUP BY status").fetchall())
        return page(
            request, "articles.html", conn, rows=rows[:PAGE_SIZE], has_next=len(rows) > PAGE_SIZE,
            page_no=page_no, status=status, feed_id=feed_id, topic_id=topic_id, counts=counts,
            statuses=STATUSES, feeds=list_feeds(conn),
            topics=conn.execute("SELECT id, name FROM topics WHERE merged_into IS NULL ORDER BY name").fetchall(),
        )

    @app.get("/articles/{article_id}", response_class=HTMLResponse)
    def article_detail(request: Request, article_id: int, conn: sqlite3.Connection = Depends(get_conn)):
        a = conn.execute(
            "SELECT a.*, f.title AS feed_title, f.url AS feed_url FROM articles a JOIN feeds f ON f.id = a.feed_id "
            "WHERE a.id = ?", (article_id,)
        ).fetchone()
        if a is None:
            raise HTTPException(404, "글이 없습니다")
        topics = conn.execute(
            "SELECT t.id, t.name, at.is_primary FROM article_topics at JOIN topics t ON t.id = at.topic_id "
            "WHERE at.article_id = ? ORDER BY at.is_primary DESC", (article_id,)
        ).fetchall()
        dups = conn.execute(
            "SELECT a.id, a.title, a.url, f.title AS feed_title FROM articles a JOIN feeds f ON f.id = a.feed_id "
            "WHERE a.duplicate_of = ?", (article_id,)
        ).fetchall()
        original = conn.execute("SELECT id, title FROM articles WHERE id = ?", (a["duplicate_of"],)).fetchone() \
            if a["duplicate_of"] else None
        return page(
            request, "article.html", conn, a=a, topics=topics, dups=dups, original=original,
            key_points=json.loads(a["key_points"] or "[]"),
        )

    @app.post("/articles/{article_id}/retry")
    def article_retry(article_id: int, conn: sqlite3.Connection = Depends(get_conn)):
        conn.execute(
            "UPDATE articles SET status = 'pending', retry_count = 0 WHERE id = ? AND status = 'failed'", (article_id,)
        )
        conn.commit()
        return redirect(f"/articles/{article_id}", "다음 수집 때 다시 처리합니다")

    # ---------- 피드 ----------
    @app.get("/feeds", response_class=HTMLResponse)
    def feeds(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
        rows = conn.execute(
            "SELECT f.*, (SELECT count(*) FROM articles WHERE feed_id = f.id) AS article_count FROM feeds f "
            "ORDER BY coalesce(f.title, f.url)"
        ).fetchall()
        logs = conn.execute(
            "SELECT l.*, f.title AS feed_title, f.url AS feed_url FROM fetch_logs l JOIN feeds f ON f.id = l.feed_id "
            "ORDER BY l.id DESC LIMIT 30"
        ).fetchall()
        return page(request, "feeds.html", conn, feeds=rows, logs=logs)

    @app.post("/feeds")
    def feeds_add(url: str = Form(...), conn: sqlite3.Connection = Depends(get_conn)):
        http = services["http"]() if "http" in services else make_client(config)
        try:
            add_feed(conn, url, http)
        except FeedError as e:
            return redirect("/feeds", f"추가하지 못했습니다: {e}")
        finally:
            http.close()
        return redirect("/feeds", "피드를 추가했습니다. 다음 수집 때 글을 가져옵니다")

    @app.post("/feeds/{feed_id}/delete")
    def feeds_delete(feed_id: int, conn: sqlite3.Connection = Depends(get_conn)):
        delete_feed(conn, feed_id)
        return redirect("/feeds", "피드를 삭제했습니다")

    @app.post("/feeds/{feed_id}/status")
    def feeds_status(feed_id: int, status: str = Form(...), conn: sqlite3.Connection = Depends(get_conn)):
        try:
            set_feed_status(conn, feed_id, status)
        except ValueError:
            raise HTTPException(400, "잘못된 상태")
        return redirect("/feeds")

    @app.post("/feeds/import")
    async def feeds_import(file: UploadFile = File(...), conn: sqlite3.Connection = Depends(get_conn)):
        try:
            added = import_opml(conn, await file.read())
        except FeedError as e:
            return redirect("/feeds", str(e))
        return redirect("/feeds", f"피드 {added}개를 가져왔습니다")

    @app.get("/feeds/export")
    def feeds_export(conn: sqlite3.Connection = Depends(get_conn)):
        return Response(
            export_opml(conn), media_type="text/x-opml",
            headers={"Content-Disposition": 'attachment; filename="rss-wiki.opml"'},
        )

    # ---------- 검색 ----------
    @app.get("/search", response_class=HTMLResponse)
    def search_page(
        request: Request,
        q: str = "",
        feed_id: str | None = None,
        topic_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        conn: sqlite3.Connection = Depends(get_conn),
    ):
        feed_id, topic_id = opt_int(feed_id), opt_int(topic_id)
        results = search(conn, q, feed_id=feed_id, topic_id=topic_id, since=since or None, until=until or None)
        return page(
            request, "search.html", conn, q=q, results=results, feed_id=feed_id, topic_id=topic_id,
            since=since or "", until=until or "", feeds=list_feeds(conn),
            topics=conn.execute("SELECT id, name FROM topics WHERE merged_into IS NULL ORDER BY name").fetchall(),
        )

    # ---------- 작업 ----------
    @app.get("/jobs", response_class=HTMLResponse)
    def jobs(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
        runs = conn.execute("SELECT * FROM job_runs ORDER BY id DESC LIMIT 30").fetchall()
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="seconds")
        week_cost = conn.execute(
            "SELECT coalesce(sum(cost_usd), 0) FROM llm_usage WHERE created_at >= ?", (week_ago,)
        ).fetchone()[0]
        return page(
            request, "jobs.html", conn, runs=runs, usage=usage_summary(conn), spent=spent_today(conn),
            week_cost=week_cost, budget=float(get_all_settings(conn)["daily_budget_usd"]),
            running={t: is_running(t) for t in ("collect", "wiki")},
        )

    @app.post("/jobs/{job_type}")
    def jobs_start(job_type: str):
        if job_type not in ("collect", "wiki"):
            raise HTTPException(404)
        background = not services.get("sync_jobs")
        if not start_job(config, job_type, services, background=background):
            return redirect("/jobs", "이미 실행 중인 작업입니다")
        label = "수집" if job_type == "collect" else "위키 갱신"
        return redirect("/jobs", f"{label}을(를) 시작했습니다" if background else f"{label}을(를) 마쳤습니다")

    # ---------- 설정 ----------
    @app.get("/settings", response_class=HTMLResponse)
    def settings(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
        return page(
            request, "settings.html", conn, values=get_all_settings(conn), rules=SETTING_RULES,
            api_key_set=bool(config.anthropic_api_key), config=config,
        )

    @app.post("/settings")
    async def settings_save(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
        form = await request.form()
        errors = []
        updates = {}
        for key, (label, lo, hi, is_int) in SETTING_RULES.items():
            raw = str(form.get(key, DEFAULT_SETTINGS[key])).strip()
            try:
                value = int(raw) if is_int else float(raw)
            except ValueError:
                errors.append(f"{label}: 숫자가 아닙니다")
                continue
            if not lo <= value <= hi:
                errors.append(f"{label}: {lo}~{hi} 범위여야 합니다")
                continue
            updates[key] = str(value)
        if errors:
            return redirect("/settings", " / ".join(errors))
        for key, value in updates.items():
            set_setting(conn, key, value)
        if hasattr(app.state, "on_settings_changed"):
            app.state.on_settings_changed()
        return redirect("/settings", "설정을 저장했습니다")
