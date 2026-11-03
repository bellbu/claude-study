import builtins
from pathlib import Path

import httpx
import pytest

from rss_wiki import cli
from rss_wiki.cli import main
from rss_wiki.config import ConfigError
from rss_wiki.db import DatabaseError, connect
from rss_wiki.http import HttpClient
from rss_wiki.summarize import SummarizerError, SummaryResult

FIXTURES = Path(__file__).parent / "fixtures"
RSS = (FIXTURES / "rss2.xml").read_bytes()
URL = "https://example.com/feed.xml"
URL2 = "https://example.org/other.xml"


class FakeSummarizer:
    model = "fake-model"

    def __init__(self, fail_titles=()):
        self.fail_titles = set(fail_titles)

    def summarize(self, title, content, existing_tags):
        if title in self.fail_titles:
            raise SummarizerError("요약 호출 실패 (HTTP 400)", transient=False)
        return SummaryResult(tldr="요약", key_points=["하나", "둘", "셋"], tags=["python"])


@pytest.fixture
def env(monkeypatch):
    state = {"requests": [], "routes": {}, "summarizer": FakeSummarizer()}

    def handler(request: httpx.Request) -> httpx.Response:
        state["requests"].append(request)
        return state["routes"].get(str(request.url), lambda r: httpx.Response(404))(request)

    monkeypatch.setattr(
        cli,
        "make_http_client",
        lambda config: HttpClient(transport=httpx.MockTransport(handler), sleep=lambda s: None),
    )
    monkeypatch.setattr(cli, "make_summarizer", lambda config: state["summarizer"])
    state["routes"][URL] = lambda r: httpx.Response(200, content=RSS)
    return state


def run(tmp_path, *args):
    return main(["--data-dir", str(tmp_path), *args])


def rows(tmp_path, sql):
    conn = connect(tmp_path / "data" / "rss-wiki.db")
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def add(tmp_path, url=URL):
    assert run(tmp_path, "feed", "add", url) == 0


def tree(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_run_end_to_end(tmp_path, env, capsys):
    add(tmp_path)
    capsys.readouterr()
    assert run(tmp_path, "run") == 0
    out = capsys.readouterr().out
    assert out.index("[fetch]") < out.index("[summarize]") < out.index("[build]")
    assert len(rows(tmp_path, "SELECT id FROM articles")) == 3
    assert rows(tmp_path, "SELECT COUNT(*) FROM summaries WHERE status = 'done'") == [(3,)]
    assert (tmp_path / "wiki" / "index.md").is_file()


def test_run_twice_is_idempotent(tmp_path, env):
    add(tmp_path)
    assert run(tmp_path, "run") == 0
    before = tree(tmp_path / "wiki")
    assert run(tmp_path, "run") == 0
    assert len(rows(tmp_path, "SELECT id FROM articles")) == 3
    assert tree(tmp_path / "wiki") == before


def test_run_without_feeds_continues(tmp_path, env, capsys):
    assert run(tmp_path, "run") == 0
    out = capsys.readouterr().out
    assert "등록된 피드가 없습니다" in out and "[build]" in out


def test_failed_feed_returns_1_but_others_processed(tmp_path, env):
    env["routes"][URL2] = lambda r: httpx.Response(200, content=RSS)
    add(tmp_path)
    add(tmp_path, URL2)
    env["routes"][URL] = lambda r: httpx.Response(503)
    assert run(tmp_path, "run") == 1
    assert len(rows(tmp_path, "SELECT id FROM articles WHERE feed_id = 2")) == 3
    assert rows(tmp_path, "SELECT COUNT(*) FROM summaries WHERE status = 'done'") == [(3,)]
    assert (tmp_path / "wiki" / "index.md").is_file()


def test_summarize_failure_returns_1(tmp_path, env):
    env["summarizer"] = FakeSummarizer(fail_titles={"첫 번째 글: 파이썬 3.14 소개"})
    add(tmp_path)
    assert run(tmp_path, "run") == 1
    assert rows(tmp_path, "SELECT COUNT(*) FROM summaries WHERE status = 'done'") == [(2,)]


def test_missing_api_key_stops_before_fetch(tmp_path, env, monkeypatch):
    add(tmp_path)
    env["requests"].clear()

    def boom(config):
        raise ConfigError("ANTHROPIC_API_KEY가 설정되지 않았습니다")

    monkeypatch.setattr(cli, "make_summarizer", boom)
    assert run(tmp_path, "run") == 2
    assert env["requests"] == []
    assert rows(tmp_path, "SELECT id FROM articles") == []


def test_build_database_error_returns_2(tmp_path, env, monkeypatch, capsys):
    add(tmp_path)

    def boom(conn, wiki_dir):
        raise DatabaseError("위키 조회 실패: boom")

    monkeypatch.setattr(cli, "build_wiki", boom)
    capsys.readouterr()
    assert run(tmp_path, "run") == 2
    err = capsys.readouterr().err
    assert "위키 조회 실패" in err and "Traceback" not in err


def test_fetch_database_error_skips_later_stages(tmp_path, env, monkeypatch, capsys):
    add(tmp_path)

    def boom(conn, config, feed_id):
        raise DatabaseError("글 저장 실패: boom")

    monkeypatch.setattr(cli, "_do_fetch", boom)
    capsys.readouterr()
    assert run(tmp_path, "run") == 2
    cap = capsys.readouterr()
    assert "[summarize]" not in cap.out
    assert "글 저장 실패" in cap.err and "Traceback" not in cap.err


def test_wiki_path_is_file_returns_2(tmp_path, env, capsys):
    add(tmp_path)
    (tmp_path / "wiki").write_text("not a dir", encoding="utf-8")
    capsys.readouterr()
    assert run(tmp_path, "run") == 2
    err = capsys.readouterr().err
    assert "위키 빌드 실패" in err and "wiki" in err and "Traceback" not in err


def test_verbose_hides_http_request_logs(tmp_path, env, capfd):
    add(tmp_path)
    capfd.readouterr()
    assert run(tmp_path, "--verbose", "run") == 0
    assert "HTTP Request:" not in capfd.readouterr().err


def test_broken_pipe_on_summarize_output_returns_1(tmp_path, env, monkeypatch, capsys):
    add(tmp_path)
    real_print = builtins.print

    def flaky(*args, **kwargs):
        if args and isinstance(args[0], str) and args[0].endswith("\t완료"):
            raise BrokenPipeError()
        return real_print(*args, **kwargs)

    monkeypatch.setattr(builtins, "print", flaky)
    assert run(tmp_path, "run") == 1
    monkeypatch.undo()
    assert "Traceback" not in capsys.readouterr().err
    assert rows(tmp_path, "SELECT COUNT(*) FROM summaries WHERE status = 'done'")[0][0] >= 1
