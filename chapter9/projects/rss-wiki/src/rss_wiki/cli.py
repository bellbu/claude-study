"""argparse CLI: subcommands, common options, exit code mapping (0/1/2)."""

import argparse
import logging
import os
import sys
from pathlib import Path

from rss_wiki.config import Config, ConfigError, default_config_toml, load_config
from rss_wiki.db import DatabaseError, connect, init_schema
from rss_wiki.fetch import fetch_feed, load_feeds
from rss_wiki.feeds import FeedError, add_feed, list_feeds, remove_feed
from rss_wiki.http import HttpClient
from rss_wiki.status import collect_status
from rss_wiki.summarize import Summarizer
from rss_wiki.summarize_run import summarize_pending
from rss_wiki.wiki import build_wiki

EXIT_OK = 0
EXIT_PARTIAL = 1
EXIT_FATAL = 2

CONFIG_NAME = "rss-wiki.toml"

log = logging.getLogger("rss_wiki")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rss-wiki",
        description="RSS/Atom 피드를 수집·요약해 주제별 위키로 정리합니다.",
    )
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument("--verbose", action="store_true", help="디버그 로그까지 출력")
    verbosity.add_argument("--quiet", action="store_true", help="경고 이상만 출력")
    parser.add_argument("--data-dir", type=Path, help="데이터 디렉터리 (기본: 현재 디렉터리)")
    parser.add_argument("--config", type=Path, help=f"설정 파일 경로 (기본: <data-dir>/{CONFIG_NAME})")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    sub.add_parser("init", help="데이터 디렉터리, DB, 기본 설정 파일 생성")
    feed = sub.add_parser("feed", help="피드 등록·목록·삭제")
    feed_sub = feed.add_subparsers(dest="feed_command", required=True, metavar="ACTION")
    add = feed_sub.add_parser("add", help="피드 등록 (URL 유효성 확인)")
    add.add_argument("url")
    add.add_argument("--name", help="피드 이름 (기본: 피드 제목)")
    feed_sub.add_parser("list", help="등록된 피드 목록")
    rm = feed_sub.add_parser("remove", help="피드 삭제 (기존 글은 유지)")
    rm.add_argument("target", metavar="ID|URL")
    fetch = sub.add_parser("fetch", help="피드에서 새 글 수집")
    fetch.add_argument("--feed", type=int, metavar="ID", help="이 id의 피드만 수집")
    summarize = sub.add_parser("summarize", help="요약되지 않은 글을 LLM으로 요약")
    summarize.add_argument("--limit", type=_positive_int, metavar="N", help="이번 실행에서 요약할 최대 글 수")
    summarize.add_argument("--retry-failed", action="store_true", help="failed로 고정된 글도 다시 시도")
    sub.add_parser("build", help="주제별 위키 페이지와 인덱스 재생성")
    sub.add_parser("run", help="fetch → summarize → build를 차례로 실행")
    sub.add_parser("status", help="수집/요약 대기·실패 건수 요약")
    serve = sub.add_parser("serve", help="로컬 웹 UI 실행 (127.0.0.1 전용)")
    serve.add_argument("--port", type=int, default=8000, help="포트 (기본 8000)")
    return parser


def _positive_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"양의 정수여야 합니다: {value!r}") from None
    if n <= 0:
        raise argparse.ArgumentTypeError(f"양의 정수여야 합니다: {value!r}")
    return n


def make_summarizer(config: Config) -> Summarizer:
    """설정으로 Summarizer를 만든다(API 키 없으면 ConfigError). 테스트는 이 함수를 대체한다."""
    from rss_wiki.claude import create_claude_summarizer  # anthropic은 요약 때만 import

    return create_claude_summarizer(config)


def make_http_client(config: Config) -> HttpClient:
    """설정값으로 HttpClient를 만든다. 테스트는 이 함수를 대체한다."""
    return HttpClient(timeout=config.http_timeout, max_retries=config.max_retries)


def _setup_logging(verbose: bool, quiet: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING if quiet else logging.INFO
    logging.basicConfig(level=level, format="%(message)s", force=True)  # stderr
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # trafilatura는 추출 실패를 ERROR로 내므로 WARNING으로는 부족하다 (실패는 fetch가 INFO로 기록)
    logging.getLogger("trafilatura").setLevel(logging.CRITICAL)


def _config_path(args: argparse.Namespace) -> Path:
    if args.config is not None:
        return args.config
    return (args.data_dir if args.data_dir is not None else Path.cwd()) / CONFIG_NAME


def cmd_init(args: argparse.Namespace, config: Config, config_path: Path) -> int:
    """Create data/wiki directories, the DB schema and (if absent) the config file."""
    config.data_dir.mkdir(parents=True, exist_ok=True)
    config.wiki_dir.mkdir(parents=True, exist_ok=True)
    conn = connect(config.db_path)  # also creates the db parent directory
    try:
        init_schema(conn)
    finally:
        conn.close()
    if config_path.exists():
        log.info("설정 파일이 이미 있어 유지합니다: %s", config_path)
    else:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(default_config_toml(), encoding="utf-8")
        log.info("설정 파일을 만들었습니다: %s", config_path)
    log.info("초기화 완료: DB=%s, wiki=%s", config.db_path, config.wiki_dir)
    return EXIT_OK


def cmd_feed(args: argparse.Namespace, config: Config, config_path: Path) -> int:
    """feed add/list/remove. init 전이어도 동작하도록 스키마를 보장한다."""
    conn = connect(config.db_path)
    try:
        init_schema(conn)
        try:
            if args.feed_command == "add":
                with make_http_client(config) as client:
                    feed_id = add_feed(conn, client, args.url, args.name)
                print(f"피드를 등록했습니다 (id={feed_id}): {args.url}")
            elif args.feed_command == "remove":
                remove_feed(conn, args.target)
                print(f"피드를 삭제했습니다: {args.target}")
            else:
                feeds = list_feeds(conn)
                if not feeds:
                    print("등록된 피드가 없습니다")
                for f in feeds:
                    print(
                        f"{f.id}	{f.name or '-'}	{f.url}	"
                        f"{f.last_fetched_at or '-'}	{f.last_status or '-'}"
                    )
        except FeedError as e:
            print(f"오류: {e}", file=sys.stderr)
            return EXIT_PARTIAL
    finally:
        conn.close()
    return EXIT_OK


def _do_fetch(conn, config: Config, feed_id: int | None) -> int:
    """피드를 수집해 결과를 출력하고 실패한 피드 수를 돌려준다. 없는 feed_id면 FeedError."""
    feeds = load_feeds(conn, feed_id)
    if not feeds:
        print("등록된 피드가 없습니다")
        return 0
    results = []
    with make_http_client(config) as client:
        for f in feeds:
            r = fetch_feed(conn, client, f, min_content_chars=config.min_content_chars)
            results.append(r)
            status = f"오류: {r.error}" if r.error else "변경 없음" if r.not_modified else f"새 글 {r.new}건"
            print(f"{f.id}	{f.name or '-'}	{status}")
    failed = sum(1 for r in results if r.error)
    print(f"합계: 새 글 {sum(r.new for r in results)}건, 실패 {failed}건")
    return failed


def _do_summarize(conn, config: Config, summarizer: Summarizer, limit: int | None, retry_failed: bool) -> int:
    """요약 대상 글을 요약해 글마다 결과 줄을 출력하고 실패한 글 수를 돌려준다."""

    def show(article, o) -> None:
        status = "완료" if o.ok else f"실패: {o.error}"
        print(f"{o.article_id}	{article['title'] or '-'}	{status}", flush=True)

    outcomes = summarize_pending(
        conn,
        summarizer,
        limit=limit,
        retry_failed=retry_failed,
        max_retries=config.max_retries,
        max_failures=config.max_failures,
        on_outcome=show,
        concurrency=config.summarize_concurrency,
    )
    if not outcomes:
        print("요약할 글이 없습니다")
        return 0
    failed = sum(1 for o in outcomes if not o.ok)
    print(f"합계: 완료 {len(outcomes) - failed}건, 실패 {failed}건")
    return failed


def cmd_fetch(args: argparse.Namespace, config: Config, config_path: Path) -> int:
    """등록된 피드를 수집한다. 실패한 피드가 있으면 종료 코드 1."""
    conn = connect(config.db_path)
    try:
        init_schema(conn)
        try:
            failed = _do_fetch(conn, config, args.feed)
        except FeedError as e:
            print(f"오류: {e}", file=sys.stderr)
            return EXIT_PARTIAL
        return EXIT_PARTIAL if failed else EXIT_OK
    finally:
        conn.close()


def cmd_summarize(args: argparse.Namespace, config: Config, config_path: Path) -> int:
    """요약 대상 글을 요약한다. 실패한 글이 있으면 종료 코드 1."""
    conn = connect(config.db_path)
    try:
        init_schema(conn)
        summarizer = make_summarizer(config)  # API 키 없으면 ConfigError (대상 유무와 무관)
        failed = _do_summarize(conn, config, summarizer, args.limit, args.retry_failed)
        return EXIT_PARTIAL if failed else EXIT_OK
    finally:
        conn.close()


def cmd_build(args: argparse.Namespace, config: Config, config_path: Path) -> int:
    """DB 기준으로 위키를 재생성한다. 파일 쓰기 OSError는 main이 종료 코드 2로 처리."""
    conn = connect(config.db_path)
    try:
        init_schema(conn)
        r = build_wiki(conn, config.wiki_dir)
    finally:
        conn.close()
    print(f"글 {r.articles}건, 주제 {r.topics}건, 정리 {r.removed}건")
    return EXIT_OK


def cmd_run(args: argparse.Namespace, config: Config, config_path: Path) -> int:
    """fetch → summarize → build. 일부 실패면 1, 단계 중 치명 오류(DatabaseError/OSError)면 2로 중단."""
    conn = connect(config.db_path)
    try:
        init_schema(conn)
        summarizer = make_summarizer(config)  # 수집 전에 API 키부터 확인 (ConfigError → 2)
        print("[fetch]")
        failed = _do_fetch(conn, config, None)
        print("[summarize]")
        failed += _do_summarize(conn, config, summarizer, None, False)
        print("[build]")
        try:
            r = build_wiki(conn, config.wiki_dir)
        except OSError as e:
            print(
                f"오류: 위키 빌드 실패(일부 파일만 갱신됐을 수 있음, 다음 build에서 회복): {e}",
                file=sys.stderr,
            )
            return EXIT_FATAL
        print(f"글 {r.articles}건, 주제 {r.topics}건, 정리 {r.removed}건")
        return EXIT_PARTIAL if failed else EXIT_OK
    finally:
        conn.close()


def cmd_status(args: argparse.Namespace, config: Config, config_path: Path) -> int:
    """수집/요약 상태 건수를 출력한다. 조회에 성공하면 상태와 무관하게 0."""
    conn = connect(config.db_path)
    try:
        init_schema(conn)
        c = collect_status(conn)
    finally:
        conn.close()
    print(f"피드: {c.feeds}개 (오류 {c.feeds_error}, 미수집 {c.feeds_never})")
    print(f"글: {c.articles}건")
    print(f"요약: 완료 {c.done}, 대기 {c.pending} (재시도 대기 {c.pending_retrying}), 실패 {c.failed}")
    if c.failed:
        print("실패 글은 summarize --retry-failed로 다시 시도할 수 있습니다")
    return EXIT_OK


def cmd_serve(args: argparse.Namespace, config: Config, config_path: Path) -> int:
    """로컬 웹 UI를 127.0.0.1에서 실행한다. flask는 이 명령에서만 import한다."""
    from rss_wiki.web import create_app, run_server

    log.info("웹 UI: http://127.0.0.1:%d (종료: Ctrl+C)", args.port)
    run_server(create_app(config), "127.0.0.1", args.port)
    return EXIT_OK


_COMMANDS = {
    "init": cmd_init,
    "feed": cmd_feed,
    "fetch": cmd_fetch,
    "summarize": cmd_summarize,
    "build": cmd_build,
    "run": cmd_run,
    "status": cmd_status,
    "serve": cmd_serve,
}


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return the exit code (0 ok, 1 partial failure, 2 fatal/usage)."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as e:  # argparse: 0 for --help, 2 for usage errors
        return e.code if isinstance(e.code, int) else EXIT_FATAL
    _setup_logging(args.verbose, args.quiet)
    config_path = _config_path(args)
    try:
        config = load_config(config_path, args.data_dir)
        return _COMMANDS[args.command](args, config, config_path)
    except BrokenPipeError:
        # 데이터는 이미 커밋됐고 출력만 잃음 → 부분 실패(1). 종료 시 flush 오류를 막으려 stdout을 devnull로 돌린다.
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        except (OSError, ValueError):
            pass
        return EXIT_PARTIAL
    except (ConfigError, DatabaseError, OSError) as e:
        print(f"오류: {e}", file=sys.stderr)
        return EXIT_FATAL
