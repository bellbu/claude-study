"""로컬 웹 UI (Flask + Jinja2). 라우트는 기존 기능 함수만 호출한다."""

import logging
import os
import sqlite3
from collections.abc import Callable
from urllib.parse import urlsplit

from flask import Flask, abort, flash, redirect, render_template, request, url_for

from rss_wiki.config import Config
from rss_wiki.db import DatabaseError, connect, init_schema
from rss_wiki.feeds import FeedError, add_feed, list_feeds, remove_feed
from rss_wiki.http import HttpClient
from rss_wiki.status import collect_status

log = logging.getLogger("rss_wiki.web")


def create_app(
    config: Config, *, http_client_factory: Callable[[], HttpClient] | None = None
) -> Flask:
    """Flask 앱을 만든다. http_client_factory는 테스트에서 가짜 HTTP 클라이언트를 주입하는 용도."""
    app = Flask(__name__)
    app.config["RSS_WIKI"] = config
    # flash 메시지용. 로컬 전용이라 프로세스마다 새로 만들고 저장하지 않는다.
    app.secret_key = os.urandom(32)

    if http_client_factory is None:

        def http_client_factory() -> HttpClient:
            return HttpClient(timeout=config.http_timeout, max_retries=config.max_retries)

    @app.before_request
    def block_cross_origin_post():
        origin = request.headers.get("Origin")
        if request.method == "POST" and origin and urlsplit(origin).netloc != request.host:
            abort(403)

    @app.get("/")
    def home():
        conn = connect(config.db_path)  # 요청마다 열고 닫음 (스레드 공유 회피)
        try:
            init_schema(conn)
            counts = collect_status(conn)
        finally:
            conn.close()
        return render_template("home.html", counts=counts, active="home")

    @app.get("/feeds")
    def feeds_page():
        conn = connect(config.db_path)
        try:
            init_schema(conn)
            feeds = list_feeds(conn)
        finally:
            conn.close()
        return render_template("feeds.html", feeds=feeds, active="feeds")

    @app.post("/feeds")
    def feeds_add():
        url = request.form.get("url", "").strip()
        name = request.form.get("name", "").strip() or None
        if not url:
            flash("피드 URL을 입력하세요.", "error")
            return redirect(url_for("feeds_page"), 303)
        conn = connect(config.db_path)
        try:
            init_schema(conn)
            with http_client_factory() as client:
                feed_id = add_feed(conn, client, url, name)
            saved = next((f.name for f in list_feeds(conn) if f.id == feed_id), None)
            flash(f"피드를 등록했습니다 (id={feed_id}): {saved or name or url}", "success")
        except FeedError as exc:
            flash(str(exc), "error")
        finally:
            conn.close()
        return redirect(url_for("feeds_page"), 303)

    @app.post("/feeds/<int:feed_id>/delete")
    def feeds_delete(feed_id: int):
        conn = connect(config.db_path)
        try:
            init_schema(conn)
            remove_feed(conn, str(feed_id))
            flash(f"피드를 삭제했습니다 (id={feed_id}). 기존 글은 유지됩니다.", "success")
        except FeedError as exc:
            flash(str(exc), "error")
        finally:
            conn.close()
        return redirect(url_for("feeds_page"), 303)

    @app.errorhandler(DatabaseError)
    def database_error(exc):
        log.error("웹 요청 중 DB 오류: %s", exc)
        return render_template("error.html", message=str(exc)), 500

    @app.errorhandler(sqlite3.Error)
    def sqlite_error(exc):
        log.error("웹 요청 중 DB 오류: %s", exc)
        return render_template("error.html", message=str(exc)), 500

    return app


def run_server(app: Flask, host: str, port: int) -> None:
    app.run(host=host, port=port)
