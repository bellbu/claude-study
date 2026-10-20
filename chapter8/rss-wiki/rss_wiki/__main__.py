"""명령행 진입점: `uv run rss-wiki [serve|collect|wiki|export]`."""

from __future__ import annotations

import argparse
import json
import logging
import sys

from rss_wiki.config import load_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rss-wiki", description="RSS 피드를 LLM으로 정리하는 주제별 위키")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("serve", help="웹 UI와 스케줄러 실행 (기본값)")
    sub.add_parser("collect", help="수집·요약·분류를 한 번 실행")
    sub.add_parser("wiki", help="주제 정리와 위키 갱신을 한 번 실행")
    exp = sub.add_parser("export", help="현재 위키를 Markdown 파일로 내보내기")
    exp.add_argument("--out", default="wiki-export", help="내보낼 폴더 (기본: wiki-export)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = load_config()
    command = args.command or "serve"

    if command in ("collect", "wiki"):
        from rss_wiki.runner import run_job

        stats = run_job(config, command)
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return 0
    if command == "export":
        from rss_wiki.db import connect
        from rss_wiki.export import export_markdown

        conn = connect(config.db_path)
        try:
            paths = export_markdown(conn, args.out)
        finally:
            conn.close()
        print(f"{len(paths)}개 페이지를 {args.out}에 내보냈습니다")
        return 0

    import uvicorn

    from rss_wiki.scheduler import build_scheduler, reschedule
    from rss_wiki.web.app import create_app

    if not config.anthropic_api_key:
        print("경고: ANTHROPIC_API_KEY가 없습니다. 요약·위키 갱신이 실패합니다 (.env에 추가하세요).", file=sys.stderr)
    app = create_app(config)
    scheduler = build_scheduler(config)
    app.state.on_settings_changed = lambda: reschedule(scheduler, config)
    scheduler.start()
    try:
        uvicorn.run(app, host=config.host, port=config.port)
    finally:
        scheduler.shutdown(wait=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
