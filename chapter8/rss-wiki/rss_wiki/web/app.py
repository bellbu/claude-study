"""로컬 웹 UI (FastAPI + Jinja2). 폼은 POST 후 303 리다이렉트로 동작한다."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import quote

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as StarletteHTTPException

from rss_wiki.config import Config
from rss_wiki.db import connect
from rss_wiki.llm import spent_today
from rss_wiki.topics import TopicError, merge_topics, rename_topic, revert_change, set_topic_status
from rss_wiki.web.render import card_summary, duration, localtime, render_markdown, safe_url
from rss_wiki.wiki import current_revision, list_revisions, revision_diff, set_current_revision

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
TEMPLATES.env.filters["localtime"] = localtime
TEMPLATES.env.filters["fromjson"] = json.loads
TEMPLATES.env.filters["safe_url"] = safe_url
TEMPLATES.env.globals["duration"] = duration
HOME_TOP = 10


def redirect(url: str, msg: str | None = None) -> RedirectResponse:
    if msg:
        url += ("&" if "?" in url else "?") + "msg=" + quote(msg)
    return RedirectResponse(url, status_code=303)


def create_app(config: Config, *, services: dict[str, Callable[[], Any]] | None = None) -> FastAPI:
    """services: 테스트에서 http/anthropic 클라이언트를 바꿔 끼우기 위한 팩토리."""
    app = FastAPI(title="RSS Wiki")
    app.state.config = config
    app.state.services = services or {}

    def get_conn() -> Iterator[sqlite3.Connection]:
        conn = connect(config.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def page(request: Request, name: str, conn: sqlite3.Connection, **ctx: Any) -> HTMLResponse:
        budget = float(conn.execute(
            "SELECT coalesce((SELECT value FROM settings WHERE key = 'daily_budget_usd'), '1.0')"
        ).fetchone()[0])
        ctx.setdefault("msg", request.query_params.get("msg"))
        ctx["budget_exceeded"] = spent_today(conn) >= budget
        return TEMPLATES.TemplateResponse(request, name, ctx)

    app.state.page = page
    app.state.get_conn = get_conn

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request, "error.html", {"status": exc.status_code, "detail": exc.detail}, status_code=exc.status_code
        )

    # ---------- 홈 ----------
    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
        last_wiki = conn.execute(
            "SELECT * FROM job_runs WHERE job_type = 'wiki' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        since = last_wiki["started_at"] if last_wiki else (
            datetime.now(timezone.utc) - timedelta(days=1)
        ).isoformat(timespec="seconds")
        rows = conn.execute(
            "SELECT t.id, t.name, w.content, w.created_at, w.new_article_ids FROM topics t "
            "JOIN wiki_revisions w ON w.topic_id = t.id AND w.is_current = 1 "
            "WHERE w.created_at >= ? AND t.status = 'active' AND t.merged_into IS NULL",
            (since,),
        ).fetchall()
        cards = []
        for r in rows:
            new_ids = json.loads(r["new_article_ids"])
            top_importance, total = 0, 0
            if new_ids:
                marks = ",".join("?" * len(new_ids))
                top_importance, total = conn.execute(
                    f"SELECT coalesce(max(importance), 0), coalesce(sum(importance), 0) FROM articles "
                    f"WHERE id IN ({marks})", new_ids
                ).fetchone()
            cards.append({
                "id": r["id"], "name": r["name"], "new_count": len(new_ids),
                "rank": (top_importance, len(new_ids), total),
                "updated_at": r["created_at"], "changes": card_summary(r["content"]),
            })
        # 꼭 알아야 할 소식(가장 높은 중요도)이 있는 주제를 먼저, 그다음 새 글 수 — 단신이 많다고 앞서지 않게
        cards.sort(key=lambda c: c["rank"], reverse=True)
        failing = conn.execute(
            "SELECT id, title, url, consecutive_failures FROM feeds WHERE consecutive_failures > 0 "
            "ORDER BY consecutive_failures DESC"
        ).fetchall()
        pending = conn.execute("SELECT count(*) FROM articles WHERE status = 'pending'").fetchone()[0]
        return page(
            request, "home.html", conn, top=cards[:HOME_TOP], more=cards[HOME_TOP:], failing=failing,
            pending=pending, last_wiki=last_wiki,
        )

    # ---------- 주제 ----------
    @app.get("/topics", response_class=HTMLResponse)
    def topics_list(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
        topics = conn.execute(
            "SELECT t.*, (SELECT count(*) FROM article_topics WHERE topic_id = t.id) AS article_count, "
            "(SELECT created_at FROM wiki_revisions WHERE topic_id = t.id AND is_current = 1) AS page_updated "
            "FROM topics t WHERE t.merged_into IS NULL ORDER BY t.status, coalesce(t.last_article_at, t.created_at) DESC"
        ).fetchall()
        changes = conn.execute(
            "SELECT c.*, t.name AS topic_name FROM topic_changes c LEFT JOIN topics t ON t.id = c.topic_id "
            "ORDER BY c.id DESC LIMIT 50"
        ).fetchall()
        return page(request, "topics.html", conn, topics=topics, changes=changes)

    def _topic_or_404(conn: sqlite3.Connection, topic_id: int) -> sqlite3.Row:
        topic = conn.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
        if topic is None:
            raise HTTPException(404, "주제가 없습니다")
        return topic

    @app.get("/topics/{topic_id}", response_class=HTMLResponse)
    def topic_page(request: Request, topic_id: int, conn: sqlite3.Connection = Depends(get_conn)):
        topic = _topic_or_404(conn, topic_id)
        if topic["merged_into"]:
            return redirect(f"/topics/{topic['merged_into']}")
        rev = current_revision(conn, topic_id)
        pending_count = conn.execute(
            "SELECT count(*) FROM article_topics at JOIN articles a ON a.id = at.article_id "
            "WHERE at.topic_id = ? AND a.status = 'done'", (topic_id,)
        ).fetchone()[0]
        return page(
            request, "topic.html", conn, topic=topic, rev=rev,
            html=render_markdown(rev["content"]) if rev else None,
            revisions=list_revisions(conn, topic_id), article_count=pending_count,
        )

    @app.get("/topics/{topic_id}/revisions/{revision_id}", response_class=HTMLResponse)
    def revision_page(request: Request, topic_id: int, revision_id: int, conn: sqlite3.Connection = Depends(get_conn)):
        topic = _topic_or_404(conn, topic_id)
        rev = conn.execute(
            "SELECT * FROM wiki_revisions WHERE id = ? AND topic_id = ?", (revision_id, topic_id)
        ).fetchone()
        if rev is None:
            raise HTTPException(404, "리비전이 없습니다")
        diff_lines = revision_diff(conn, revision_id).splitlines()
        return page(
            request, "revision.html", conn, topic=topic, rev=rev, html=render_markdown(rev["content"]),
            diff_lines=diff_lines,
        )

    @app.post("/topics/{topic_id}/revisions/{revision_id}/restore")
    def restore_revision(topic_id: int, revision_id: int, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            set_current_revision(conn, topic_id, revision_id)
        except ValueError as e:
            raise HTTPException(404, str(e))
        return redirect(f"/topics/{topic_id}", "리비전을 되돌렸습니다")

    @app.post("/topics/{topic_id}/rename")
    def rename(topic_id: int, name: str = Form(...), conn: sqlite3.Connection = Depends(get_conn)):
        try:
            rename_topic(conn, topic_id, name, source="user")
        except TopicError as e:
            return redirect("/topics", str(e))
        return redirect("/topics", "이름을 바꿨습니다")

    @app.post("/topics/{topic_id}/merge")
    def merge(topic_id: int, target_id: int = Form(...), conn: sqlite3.Connection = Depends(get_conn)):
        try:
            merge_topics(conn, topic_id, target_id, source="user")
        except TopicError as e:
            return redirect("/topics", str(e))
        return redirect("/topics", "주제를 병합했습니다")

    @app.post("/topics/{topic_id}/status")
    def change_status(topic_id: int, status: str = Form(...), conn: sqlite3.Connection = Depends(get_conn)):
        if status not in ("active", "hidden", "archived"):
            raise HTTPException(400, "잘못된 상태")
        try:
            set_topic_status(conn, topic_id, status, source="user")
        except TopicError as e:
            return redirect("/topics", str(e))
        return redirect("/topics", "상태를 바꿨습니다")

    @app.post("/topics/changes/{change_id}/revert")
    def revert(change_id: int, conn: sqlite3.Connection = Depends(get_conn)):
        try:
            revert_change(conn, change_id)
        except TopicError as e:
            return redirect("/topics", str(e))
        return redirect("/topics", "변경을 되돌렸습니다")

    from rss_wiki.web import routes_more

    routes_more.register(app)
    return app
