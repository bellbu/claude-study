import json
import logging
import sqlite3
import threading
import time

import pytest

import rss_wiki.summarize_run as run_mod
from rss_wiki.db import DatabaseError, connect, init_schema
from rss_wiki.summarize import SummarizerError, SummaryResult, SummaryValidationError, validate_summary
from rss_wiki.summarize_run import select_targets, summarize_article, summarize_pending


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    init_schema(c)
    yield c
    c.close()


def add_article(conn, n, title="제목"):
    conn.execute(
        "INSERT INTO articles (guid, url, title, content, content_source, fetched_at)"
        " VALUES (?, ?, ?, ?, 'rss', '2026-01-01T00:00:00Z')",
        (f"g{n}", f"https://example.com/{n}", f"{title}{n}", f"본문{n}"),
    )
    return conn.execute("SELECT id FROM articles WHERE guid = ?", (f"g{n}",)).fetchone()[0]


def ok_result(tags=("python",)):
    return SummaryResult(tldr="요약", key_points=["하나", "둘", "셋"], tags=list(tags))


class FakeSummarizer:
    """responses: 호출 순서대로 SummaryResult 또는 던질 예외."""

    model = "fake-model"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def summarize(self, title, content, existing_tags):
        self.calls.append((title, content, list(existing_tags)))
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(r, Exception):
            raise r
        return r


def transient(msg="요약 호출 실패 (model=fake, HTTP 429)"):
    return SummarizerError(msg, transient=True)


def summary_row(conn, article_id):
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    return cur.execute("SELECT * FROM summaries WHERE article_id = ?", (article_id,)).fetchone()


def run_one(conn, summarizer, aid, tags=None, **kw):
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    art = cur.execute("SELECT id, title, url, content FROM articles WHERE id = ?", (aid,)).fetchone()
    kw.setdefault("sleep", lambda s: None)
    return summarize_article(conn, summarizer, art, [] if tags is None else tags, **kw)


def test_success_records_summary_and_tags(conn):
    a = add_article(conn, 1)
    b = add_article(conn, 2)
    fake = FakeSummarizer([ok_result(["python", "ai"]), ok_result(["python"])])
    outcomes = summarize_pending(conn, fake, sleep=lambda s: None)
    assert [o.ok for o in outcomes] == [True, True]

    row = summary_row(conn, a)
    assert row["status"] == "done"
    assert row["model"] == "fake-model"
    assert row["last_error"] is None and row["summarized_at"].endswith("Z")
    assert row["key_points"] == '["하나", "둘", "셋"]'
    assert json.loads(row["key_points"]) == ["하나", "둘", "셋"]
    assert conn.execute("SELECT count(*) FROM tags").fetchone()[0] == 2
    assert conn.execute("SELECT count(*) FROM article_tags").fetchone()[0] == 3
    assert summary_row(conn, b)["status"] == "done"
    # 두 번째 글의 existing_tags에 첫 글의 태그가 들어 있음
    assert set(fake.calls[1][2]) == {"python", "ai"}
    assert fake.calls[0][2] == []


def test_transient_then_success(conn):
    a = add_article(conn, 1)
    sleeps = []
    fake = FakeSummarizer([transient(), transient(), ok_result()])
    out = run_one(conn, fake, a, sleep=sleeps.append)
    assert out.ok
    assert sleeps == [1.0, 2.0]
    assert len(fake.calls) == 3
    row = summary_row(conn, a)
    assert row["status"] == "done" and row["attempts"] == 0


def test_transient_forever_counts_one_failure(conn):
    a = add_article(conn, 1)
    sleeps = []
    fake = FakeSummarizer([transient()])
    out = run_one(conn, fake, a, sleep=sleeps.append)
    assert not out.ok
    assert len(fake.calls) == 4
    assert sleeps == [1.0, 2.0, 4.0]
    row = summary_row(conn, a)
    assert row["attempts"] == 1 and row["status"] == "pending"
    assert "HTTP 429" in row["last_error"]


def test_validation_error_is_one_failure_without_retry(conn):
    a = add_article(conn, 1)
    sleeps = []

    class BadShape(FakeSummarizer):
        def summarize(self, title, content, existing_tags):
            self.calls.append(1)
            # 키는 모두 있지만 key_points가 2개라 validate_summary에서 실패
            return validate_summary({"tldr": "x", "key_points": ["a", "b"], "tags": ["t"]})

    fake = BadShape([])
    out = run_one(conn, fake, a, sleep=sleeps.append)
    assert not out.ok and "key_points" in out.error
    assert len(fake.calls) == 1 and sleeps == []
    assert summary_row(conn, a)["attempts"] == 1


def test_non_transient_error_no_retry(conn):
    a = add_article(conn, 1)
    sleeps = []
    fake = FakeSummarizer([SummarizerError("요약 호출 실패 (HTTP 401)", transient=False)])
    out = run_one(conn, fake, a, sleep=sleeps.append)
    assert not out.ok
    assert len(fake.calls) == 1 and sleeps == []
    assert summary_row(conn, a)["attempts"] == 1


def test_fifth_failure_fixes_failed_and_retry_failed_selects(conn):
    a = add_article(conn, 1)
    conn.execute("INSERT INTO summaries (article_id, status, attempts) VALUES (?, 'pending', 4)", (a,))
    fake = FakeSummarizer([SummaryValidationError("tldr가 비어 있습니다")])
    run_one(conn, fake, a)
    row = summary_row(conn, a)
    assert row["attempts"] == 5 and row["status"] == "failed"
    assert select_targets(conn) == []
    assert [r["id"] for r in select_targets(conn, retry_failed=True)] == [a]


def test_fourth_failure_stays_pending(conn):
    a = add_article(conn, 1)
    conn.execute("INSERT INTO summaries (article_id, status, attempts) VALUES (?, 'pending', 3)", (a,))
    run_one(conn, FakeSummarizer([SummaryValidationError("x")]), a)
    row = summary_row(conn, a)
    assert row["attempts"] == 4 and row["status"] == "pending"


def test_retry_failed_success_marks_done(conn):
    a = add_article(conn, 1)
    conn.execute("INSERT INTO summaries (article_id, status, attempts, last_error) VALUES (?, 'failed', 5, 'e')", (a,))
    summarize_pending(conn, FakeSummarizer([ok_result()]), retry_failed=True)
    row = summary_row(conn, a)
    assert row["status"] == "done" and row["last_error"] is None


def test_select_targets_excludes_done_orders_and_limits(conn):
    ids = [add_article(conn, n) for n in (1, 2, 3, 4)]
    conn.execute("INSERT INTO summaries (article_id, status) VALUES (?, 'done')", (ids[0],))
    conn.execute("INSERT INTO summaries (article_id, status) VALUES (?, 'pending')", (ids[2],))
    assert [r["id"] for r in select_targets(conn)] == [ids[1], ids[2], ids[3]]
    assert [r["id"] for r in select_targets(conn, limit=1)] == [ids[1]]
    row = select_targets(conn)[0]
    assert row["title"] and row["content"]


def test_orphan_article_is_targeted(conn):
    a = add_article(conn, 1)  # feed_id NULL
    assert [r["id"] for r in select_targets(conn)] == [a]


def test_failure_does_not_block_next_and_logs_id(conn, caplog):
    a = add_article(conn, 1)
    b = add_article(conn, 2)
    fake = FakeSummarizer([SummarizerError("실패", transient=False), ok_result()])
    with caplog.at_level(logging.WARNING, logger="rss_wiki.summarize_run"):
        outcomes = summarize_pending(conn, fake, sleep=lambda s: None)
    assert [o.ok for o in outcomes] == [False, True]
    assert summary_row(conn, a)["status"] == "pending"
    assert summary_row(conn, b)["status"] == "done"
    assert any(r.levelno == logging.WARNING and f"id={a}" in r.getMessage() for r in caplog.records)


def test_last_error_truncated(conn):
    a = add_article(conn, 1)
    long = "가" * 1000
    out = run_one(conn, FakeSummarizer([SummarizerError(long, transient=False)]), a)
    row = summary_row(conn, a)
    assert len(row["last_error"]) == 201 and row["last_error"].endswith("…")
    assert out.error == row["last_error"]


def test_resummarize_replaces_article_tags(conn):
    a = add_article(conn, 1)
    conn.execute("INSERT INTO summaries (article_id, status, attempts) VALUES (?, 'failed', 5)", (a,))
    conn.execute("INSERT INTO tags (name) VALUES ('old')")
    old_id = conn.execute("SELECT id FROM tags WHERE name = 'old'").fetchone()[0]
    conn.execute("INSERT INTO article_tags (article_id, tag_id) VALUES (?, ?)", (a, old_id))
    summarize_pending(conn, FakeSummarizer([ok_result(["new"])]), retry_failed=True)
    names = [
        r[0]
        for r in conn.execute(
            "SELECT t.name FROM article_tags at JOIN tags t ON t.id = at.tag_id WHERE at.article_id = ?", (a,)
        )
    ]
    assert names == ["new"]


def test_success_keeps_attempts(conn):
    a = add_article(conn, 1)
    conn.execute("INSERT INTO summaries (article_id, status, attempts) VALUES (?, 'failed', 5)", (a,))
    summarize_pending(conn, FakeSummarizer([ok_result()]), retry_failed=True)
    row = summary_row(conn, a)
    assert row["attempts"] == 5 and row["status"] == "done"


@pytest.mark.parametrize("kind", ["dict", "row"])
def test_failure_without_url_key_does_not_crash(conn, caplog, kind):
    conn.execute(
        "INSERT INTO articles (id, guid, url, title, content, content_source, fetched_at)"
        " VALUES (7, 'g7', 'u', 't', 'c', 'rss', '2026-01-01T00:00:00Z')"
    )
    if kind == "dict":
        article = {"id": 7, "title": "t", "content": "c"}
    else:
        cur = conn.cursor()
        cur.row_factory = sqlite3.Row
        article = cur.execute("SELECT id, title, content FROM articles WHERE id = 7").fetchone()
    fake = FakeSummarizer([SummarizerError("실패", transient=False)])
    with caplog.at_level(logging.WARNING, logger="rss_wiki.summarize_run"):
        out = summarize_article(conn, fake, article, [], sleep=lambda s: None)
    assert out.ok is False
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "id=7" in warnings[0].getMessage() and ", -)" in warnings[0].getMessage()


def test_retry_and_success_are_logged(conn, caplog):
    a = add_article(conn, 1)
    fake = FakeSummarizer([transient(), ok_result(["python"])])
    with caplog.at_level(logging.DEBUG, logger="rss_wiki.summarize_run"):
        run_one(conn, fake, a)
    retries = [r for r in caplog.records if r.levelno == logging.DEBUG and "요약 재시도" in r.getMessage()]
    assert len(retries) == 1
    assert "1/3" in retries[0].getMessage() and "HTTP 429" in retries[0].getMessage()
    done = [r for r in caplog.records if r.levelno == logging.INFO and "요약 완료" in r.getMessage()]
    assert len(done) == 1 and f"id={a}" in done[0].getMessage()
    assert "python" in done[0].getMessage()


def test_store_failure_rolls_back_and_raises_database_error(conn):
    a = add_article(conn, 1)
    real = conn.execute

    class Wrapped:
        """article_tags INSERT에서 실패시켜 앞선 summaries 쓰기가 롤백되는지 본다."""

        def __init__(self, c):
            self._c = c

        def execute(self, sql, *args):
            if sql.startswith("INSERT OR IGNORE INTO article_tags"):
                raise sqlite3.OperationalError("disk I/O error")
            return self._c.execute(sql, *args)

    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    art = cur.execute("SELECT id, title, url, content FROM articles WHERE id = ?", (a,)).fetchone()
    with pytest.raises(DatabaseError) as exc:
        summarize_article(Wrapped(conn), FakeSummarizer([ok_result()]), art, [], sleep=lambda s: None)
    assert isinstance(exc.value.__cause__, sqlite3.OperationalError)
    assert str(a) in str(exc.value)
    assert real("SELECT count(*) FROM summaries").fetchone()[0] == 0
    assert real("SELECT count(*) FROM article_tags").fetchone()[0] == 0
    assert real("SELECT count(*) FROM tags").fetchone()[0] == 0
    assert not conn.in_transaction


def test_failure_store_error_is_database_error(conn):
    a = add_article(conn, 1)
    conn.execute("DROP TABLE summaries")
    with pytest.raises(DatabaseError) as exc:
        run_one(conn, FakeSummarizer([SummarizerError("x", transient=False)]), a)
    assert isinstance(exc.value.__cause__, sqlite3.Error)


def test_on_outcome_called_per_article_in_id_order(conn):
    ids = [add_article(conn, n) for n in (1, 2, 3)]
    seen = []
    outcomes = summarize_pending(
        conn,
        FakeSummarizer([ok_result(), SummarizerError("x", transient=False), ok_result()]),
        sleep=lambda s: None,
        on_outcome=lambda row, o: seen.append((row["id"], row["title"], o)),
    )
    assert [s[0] for s in seen] == ids
    assert [s[1] for s in seen] == ["제목1", "제목2", "제목3"]
    assert [s[2] for s in seen] == outcomes
    assert [o.ok for o in outcomes] == [True, False, True]


# --- T16: 병렬 실행 ---


class ThreadFake:
    """스레드 안전한 가짜 Summarizer. behavior(title)로 결과/예외를 정함."""

    model = "fake-model"

    def __init__(self, behavior=None, hold=None):
        self.behavior = behavior or (lambda title: ok_result())
        self.hold = hold
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def summarize(self, title, content, existing_tags):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if self.hold:
                self.hold()
            r = self.behavior(title)
            if isinstance(r, Exception):
                raise r
            return r
        finally:
            with self.lock:
                self.active -= 1


def test_parallel_calls_really_run_concurrently(conn):
    for n in (1, 2):
        add_article(conn, n)
    barrier = threading.Barrier(2, timeout=5)
    fake = ThreadFake(hold=barrier.wait)
    outcomes = summarize_pending(conn, fake, concurrency=2, sleep=lambda s: None)
    assert [o.ok for o in outcomes] == [True, True]


def test_concurrency_upper_bound(conn):
    for n in range(1, 9):
        add_article(conn, n)
    fake = ThreadFake(hold=lambda: time.sleep(0.05))
    outcomes = summarize_pending(conn, fake, concurrency=3, sleep=lambda s: None)
    assert all(o.ok for o in outcomes)
    assert 2 <= fake.max_active <= 3


def test_parallel_failure_isolated_and_ordered(conn):
    ids = [add_article(conn, n) for n in (1, 2, 3, 4)]
    fake = ThreadFake(lambda t: SummarizerError("x", transient=False) if t == "제목2" else ok_result())
    seen = []
    outcomes = summarize_pending(
        conn, fake, concurrency=4, sleep=lambda s: None, on_outcome=lambda row, o: seen.append(row["id"])
    )
    assert [o.article_id for o in outcomes] == ids
    assert seen == ids
    assert [o.ok for o in outcomes] == [True, False, True, True]
    assert summary_row(conn, ids[1])["attempts"] == 1
    for i in (0, 2, 3):
        assert summary_row(conn, ids[i])["status"] == "done"
        assert summary_row(conn, ids[i])["attempts"] == 0


def test_on_outcome_runs_on_main_thread(conn):
    for n in (1, 2, 3):
        add_article(conn, n)
    threads = []
    summarize_pending(
        conn, ThreadFake(), concurrency=3, sleep=lambda s: None,
        on_outcome=lambda row, o: threads.append(threading.current_thread()),
    )
    assert threads and all(t is threading.main_thread() for t in threads)


def test_concurrency_zero_is_value_error(conn):
    with pytest.raises(ValueError):
        summarize_pending(conn, ThreadFake(), concurrency=0)


def test_parallel_transient_retry_absorbed(conn):
    ids = [add_article(conn, n) for n in (1, 2)]
    first = {"done": False}

    def behavior(title):
        if title == "제목1" and not first["done"]:
            first["done"] = True
            return transient()
        return ok_result()

    sleeps = []
    outcomes = summarize_pending(conn, ThreadFake(behavior), concurrency=2, sleep=sleeps.append)
    assert [o.ok for o in outcomes] == [True, True]
    assert len(sleeps) == 1
    assert summary_row(conn, ids[0])["status"] == "done"
    assert summary_row(conn, ids[1])["status"] == "done"
    assert summary_row(conn, ids[1])["attempts"] == 0


def test_parallel_unexpected_exception_is_reraised(conn):
    for n in (1, 2):
        add_article(conn, n)
    fake = ThreadFake(lambda t: RuntimeError("boom") if t == "제목1" else ok_result())
    with pytest.raises(RuntimeError, match="boom"):
        summarize_pending(conn, fake, concurrency=2, sleep=lambda s: None)


def test_parallel_database_error_cancels_pending(conn, monkeypatch):
    ids = [add_article(conn, n) for n in range(1, 7)]
    fake = ThreadFake(hold=lambda: time.sleep(0.05))
    real = run_mod._store_success
    count = {"n": 0}

    def flaky(c, article_id, model, result):
        count["n"] += 1
        if count["n"] == 2:
            raise sqlite3.OperationalError("database is locked")
        return real(c, article_id, model, result)

    monkeypatch.setattr(run_mod, "_store_success", flaky)
    calls = {"n": 0}
    orig = fake.summarize

    def counting(title, content, tags):
        calls["n"] += 1
        return orig(title, content, tags)

    fake.summarize = counting
    with pytest.raises(DatabaseError):
        summarize_pending(conn, fake, concurrency=2, sleep=lambda s: None)
    assert summary_row(conn, ids[0])["status"] == "done"
    for i in ids[1:]:
        row = summary_row(conn, i)
        assert row is None or row["status"] != "done"
    assert calls["n"] < 6
    assert calls["n"] <= 2 + 2


def test_parallel_keyboard_interrupt_exits_quickly(conn):
    for n in (1, 2):
        add_article(conn, n)
    release = threading.Event()

    def behavior(title):
        if title == "제목2":
            release.wait(5)
        return ok_result()

    def interrupt(row, outcome):
        raise KeyboardInterrupt

    start = time.monotonic()
    try:
        with pytest.raises(KeyboardInterrupt):
            summarize_pending(conn, ThreadFake(behavior), concurrency=2, sleep=lambda s: None, on_outcome=interrupt)
        assert time.monotonic() - start < 2
    finally:
        release.set()
