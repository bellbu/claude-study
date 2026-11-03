import sqlite3

import pytest

from rss_wiki.cli import main
from rss_wiki.db import DatabaseError, connect, init_schema
from rss_wiki.status import collect_status
from rss_wiki.summarize_run import select_targets


def run(tmp_path, *args):
    return main(["--data-dir", str(tmp_path), *args])


def db_path(tmp_path):
    return tmp_path / "data" / "rss-wiki.db"


def seed(tmp_path):
    """피드 3개(ok·error·미수집), 글 6건(요약 없음·pending 0·pending 2·done 2·failed 1, 마지막은 고아)."""
    conn = connect(db_path(tmp_path))
    init_schema(conn)
    feeds = [
        ("https://a.example/f", "ok", "2026-01-01T00:00:00Z"),
        ("https://b.example/f", "error: x", "2026-01-01T00:00:00Z"),
        ("https://c.example/f", None, None),
    ]
    for url, status, fetched in feeds:
        conn.execute(
            "INSERT INTO feeds (url, name, last_status, last_fetched_at) VALUES (?, 'n', ?, ?)",
            (url, status, fetched),
        )
    # (summaries status, attempts) — None이면 summaries 행 없음
    specs = [(None, 0), ("pending", 0), ("pending", 2), ("done", 0), ("done", 0), ("failed", 5)]
    for n, (status, attempts) in enumerate(specs, 1):
        feed_id = None if n == 6 else 1
        conn.execute(
            "INSERT INTO articles (feed_id, guid, url, title, content, content_source, fetched_at)"
            " VALUES (?, ?, ?, ?, '본문', 'rss', '2026-01-01T00:00:00Z')",
            (feed_id, f"g{n}", f"https://example.com/{n}", f"글{n}"),
        )
        if status:
            conn.execute(
                "INSERT INTO summaries (article_id, status, attempts) VALUES (?, ?, ?)",
                (n, status, attempts),
            )
    return conn


def test_empty_db_before_init(tmp_path, capsys):
    assert run(tmp_path, "status") == 0
    assert capsys.readouterr().out.splitlines() == [
        "피드: 0개 (오류 0, 미수집 0)",
        "글: 0건",
        "요약: 완료 0, 대기 0 (재시도 대기 0), 실패 0",
    ]


def test_counts_and_output(tmp_path, capsys):
    conn = seed(tmp_path)
    c = collect_status(conn)
    assert (c.feeds, c.feeds_error, c.feeds_never) == (3, 1, 1)
    assert c.articles == 6
    assert (c.pending, c.pending_retrying, c.done, c.failed) == (3, 1, 2, 1)
    assert c.pending == len(select_targets(conn))
    conn.close()
    capsys.readouterr()
    assert run(tmp_path, "status") == 0
    assert capsys.readouterr().out.splitlines() == [
        "피드: 3개 (오류 1, 미수집 1)",
        "글: 6건",
        "요약: 완료 2, 대기 3 (재시도 대기 1), 실패 1",
        "실패 글은 summarize --retry-failed로 다시 시도할 수 있습니다",
    ]


def test_missing_schema_raises_database_error(tmp_path):
    conn = sqlite3.connect(tmp_path / "empty.db")
    try:
        with pytest.raises(DatabaseError) as exc:
            collect_status(conn)
    finally:
        conn.close()
    assert "상태 조회 실패" in str(exc.value)
    assert isinstance(exc.value.__cause__, sqlite3.Error)


def test_logs_not_on_stdout(tmp_path, capsys, monkeypatch):
    import logging

    import rss_wiki.cli as cli

    original = cli.collect_status

    def wrapped(conn):
        logging.getLogger("rss_wiki").info("상태-로그")
        return original(conn)

    monkeypatch.setattr(cli, "collect_status", wrapped)
    assert run(tmp_path, "status") == 0
    captured = capsys.readouterr()
    assert "상태-로그" not in captured.out
    assert "상태-로그" in captured.err


def test_quiet_hides_info_logs(tmp_path, capsys, monkeypatch):
    import logging

    import rss_wiki.cli as cli

    original = cli.collect_status

    def wrapped(conn):
        logging.getLogger("rss_wiki").info("상태-로그")
        return original(conn)

    monkeypatch.setattr(cli, "collect_status", wrapped)
    assert run(tmp_path, "--quiet", "status") == 0
    captured = capsys.readouterr()
    assert "상태-로그" not in captured.out
    assert "상태-로그" not in captured.err


def test_corrupt_db_returns_2(tmp_path, capsys):
    path = db_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"this is not a sqlite database" * 20)
    assert run(tmp_path, "status") == 2
    captured = capsys.readouterr()
    assert "오류:" in captured.err
    assert "Traceback" not in captured.err
    assert captured.out == ""


def test_help_exits_0():
    assert main(["status", "--help"]) == 0
