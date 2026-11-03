import pytest

from rss_wiki import cli
from rss_wiki.cli import main
from rss_wiki.db import connect
from rss_wiki.summarize import SummarizerError, SummaryResult


class FakeSummarizer:
    """실패 대상 제목(fail_titles)이면 SummarizerError, 아니면 성공."""

    model = "fake-model"

    def __init__(self, fail_titles=()):
        self.fail_titles = set(fail_titles)
        self.titles = []

    def summarize(self, title, content, existing_tags):
        self.titles.append(title)
        if title in self.fail_titles:
            raise SummarizerError("요약 호출 실패 (model=fake, HTTP 400)", transient=False)
        return SummaryResult(tldr="요약", key_points=["하나", "둘", "셋"], tags=["python"])


@pytest.fixture
def fake(monkeypatch):
    f = FakeSummarizer()
    monkeypatch.setattr(cli, "make_summarizer", lambda config: f)
    return f


def run(tmp_path, *args):
    return main(["--data-dir", str(tmp_path), *args])


def add_articles(tmp_path, *titles):
    assert run(tmp_path, "init") == 0
    conn = connect(tmp_path / "data" / "rss-wiki.db")
    try:
        for n, title in enumerate(titles, 1):
            conn.execute(
                "INSERT INTO articles (guid, url, title, content, content_source, fetched_at)"
                " VALUES (?, ?, ?, '본문', 'rss', '2026-01-01T00:00:00Z')",
                (f"g{n}", f"https://example.com/{n}", title),
            )
    finally:
        conn.close()


def query(tmp_path, sql):
    conn = connect(tmp_path / "data" / "rss-wiki.db")
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_all_success_returns_0(tmp_path, fake, capsys):
    add_articles(tmp_path, "글1", "글2")
    capsys.readouterr()
    assert run(tmp_path, "summarize") == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines == ["1\t글1\t완료", "2\t글2\t완료", "합계: 완료 2건, 실패 0건"]
    assert query(tmp_path, "SELECT COUNT(*) FROM summaries WHERE status = 'done'")[0][0] == 2


def test_partial_failure_returns_1(tmp_path, monkeypatch, capsys):
    f = FakeSummarizer(fail_titles={"글1"})
    monkeypatch.setattr(cli, "make_summarizer", lambda config: f)
    add_articles(tmp_path, "글1", "글2")
    capsys.readouterr()
    assert run(tmp_path, "summarize") == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("1\t글1\t실패: ") and "HTTP 400" in lines[0]
    assert lines[1] == "2\t글2\t완료"
    assert lines[2] == "합계: 완료 1건, 실패 1건"


def test_no_targets_returns_0(tmp_path, fake, capsys):
    add_articles(tmp_path)
    capsys.readouterr()
    assert run(tmp_path, "summarize") == 0
    assert "요약할 글이 없습니다" in capsys.readouterr().out
    assert fake.titles == []


def test_missing_api_key_returns_2(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    add_articles(tmp_path)  # 대상이 없어도 키를 먼저 확인
    capsys.readouterr()
    assert run(tmp_path, "summarize") == 2
    err = capsys.readouterr().err
    assert "ANTHROPIC_API_KEY" in err and "Traceback" not in err


def test_limit_processes_only_n(tmp_path, fake, capsys):
    add_articles(tmp_path, "글1", "글2", "글3")
    capsys.readouterr()
    assert run(tmp_path, "summarize", "--limit", "1") == 0
    assert fake.titles == ["글1"]
    assert "합계: 완료 1건, 실패 0건" in capsys.readouterr().out


@pytest.mark.parametrize("value", ["0", "-1"])
def test_non_positive_limit_returns_2(tmp_path, fake, capsys, value):
    add_articles(tmp_path, "글1")
    capsys.readouterr()
    assert run(tmp_path, "summarize", "--limit", value) == 2
    assert "usage:" in capsys.readouterr().err
    assert fake.titles == []


def test_failed_excluded_unless_retry_failed(tmp_path, fake, capsys):
    add_articles(tmp_path, "글1", "글2")
    conn = connect(tmp_path / "data" / "rss-wiki.db")
    conn.execute("INSERT INTO summaries (article_id, status, attempts) VALUES (1, 'failed', 5)")
    conn.close()
    capsys.readouterr()
    assert run(tmp_path, "summarize") == 0
    assert fake.titles == ["글2"]
    assert run(tmp_path, "summarize", "--retry-failed") == 0
    assert fake.titles == ["글2", "글1"]
    assert query(tmp_path, "SELECT status FROM summaries WHERE article_id = 1")[0][0] == "done"


def test_stdout_has_only_result_lines_and_logs_go_to_stderr(tmp_path, fake, capsys):
    add_articles(tmp_path, "글1")
    capsys.readouterr()
    assert run(tmp_path, "summarize") == 0
    cap = capsys.readouterr()
    assert cap.out.splitlines() == ["1\t글1\t완료", "합계: 완료 1건, 실패 0건"]
    assert "요약 완료" not in cap.out
    assert "요약 완료" in cap.err


def test_quiet_hides_info_log(tmp_path, fake, capsys):
    add_articles(tmp_path, "글1")
    capsys.readouterr()
    assert run(tmp_path, "--quiet", "summarize") == 0
    assert "요약 완료" not in capsys.readouterr().err


def test_untitled_article_shows_dash(tmp_path, fake, capsys):
    add_articles(tmp_path, "글1")
    conn = connect(tmp_path / "data" / "rss-wiki.db")
    conn.execute("UPDATE articles SET title = NULL")
    conn.close()
    capsys.readouterr()
    assert run(tmp_path, "summarize") == 0
    assert "1\t-\t완료" in capsys.readouterr().out


def test_database_error_keeps_printed_lines_and_skips_total(tmp_path, fake, monkeypatch, capsys):
    import sqlite3

    import rss_wiki.summarize_run as run_mod

    add_articles(tmp_path, "글1", "글2")
    real = run_mod._store_success
    calls = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise sqlite3.OperationalError("disk I/O error")
        return real(*args, **kwargs)

    monkeypatch.setattr(run_mod, "_store_success", flaky)
    capsys.readouterr()
    assert run(tmp_path, "summarize") == 2
    cap = capsys.readouterr()
    assert "1\t글1\t완료" in cap.out.splitlines()
    assert "합계:" not in cap.out
    assert "요약 저장 실패" in cap.err and "Traceback" not in cap.err


def test_import_cli_does_not_load_anthropic():
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, "-c", "import sys, rss_wiki.cli; print('anthropic' in sys.modules)"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert out.strip() == "False"


def test_non_numeric_limit_returns_2(tmp_path, fake, capsys):
    add_articles(tmp_path, "글1")
    capsys.readouterr()
    assert run(tmp_path, "summarize", "--limit", "abc") == 2
    assert "usage:" in capsys.readouterr().err
    assert fake.titles == []
