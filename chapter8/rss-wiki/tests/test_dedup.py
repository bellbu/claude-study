from rss_wiki.db import utcnow
from rss_wiki.dedup import content_hash, normalize_url, store_entries

LONG = "인공지능 반도체 시장이 빠르게 성장하고 있으며 주요 기업들이 신제품을 연이어 발표하고 있다. " * 2


def _feed(conn, url):
    return conn.execute("INSERT INTO feeds(url, created_at) VALUES (?, ?)", (url, utcnow())).lastrowid


def _entry(**kw):
    base = {"guid": "g", "url": "https://ex.com/a", "title": "제목", "published_at": "2026-10-01T00:00:00+00:00", "rss_content": "짧음"}
    base.update(kw)
    return base


def test_normalize_url_strips_tracking():
    assert normalize_url("http://www.Ex.com/post/?utm_source=x&b=2&a=1&fbclid=z#frag") == "https://ex.com/post?a=1&b=2"
    assert normalize_url("https://ex.com") == "https://ex.com/"
    assert normalize_url(None) is None


def test_content_hash_ignores_markup_and_short_text():
    assert content_hash(f"<p>{LONG}</p>") == content_hash(f"  {LONG.upper()}  ")
    assert content_hash("Read more...") is None


def test_same_guid_skipped(conn):
    f = _feed(conn, "f1")
    assert len(store_entries(conn, f, [_entry()])) == 1
    assert store_entries(conn, f, [_entry()]) == []
    assert conn.execute("SELECT count(*) FROM articles").fetchone()[0] == 1


def test_same_feed_changed_guid_same_url_skipped(conn):
    f = _feed(conn, "f1")
    store_entries(conn, f, [_entry()])
    assert store_entries(conn, f, [_entry(guid="g2", url="https://ex.com/a?utm_medium=rss")]) == []
    assert conn.execute("SELECT count(*) FROM articles").fetchone()[0] == 1


def test_cross_feed_same_url_linked_as_duplicate(conn):
    f1, f2 = _feed(conn, "f1"), _feed(conn, "f2")
    [orig] = store_entries(conn, f1, [_entry()])
    assert store_entries(conn, f2, [_entry(guid="other", url="http://www.ex.com/a/")]) == []
    row = conn.execute("SELECT * FROM articles WHERE feed_id = ?", (f2,)).fetchone()
    assert row["duplicate_of"] == orig and row["status"] == "duplicate"


def test_content_hash_duplicate(conn):
    f1, f2 = _feed(conn, "f1"), _feed(conn, "f2")
    [orig] = store_entries(conn, f1, [_entry(rss_content=LONG)])
    store_entries(conn, f2, [_entry(guid="x", url="https://other.com/b", title="완전히 다른 제목", rss_content=f"<div>{LONG}</div>")])
    assert conn.execute("SELECT duplicate_of FROM articles WHERE feed_id = ?", (f2,)).fetchone()[0] == orig


def test_similar_title_cross_feed_within_window(conn):
    f1, f2, f3 = _feed(conn, "f1"), _feed(conn, "f2"), _feed(conn, "f3")
    [orig] = store_entries(conn, f1, [_entry(title="OpenAI announces new reasoning model GPT-9")])
    store_entries(conn, f2, [_entry(guid="b", url="https://b.com/1", title="OpenAI announces new reasoning model: GPT-9")])
    assert conn.execute("SELECT duplicate_of FROM articles WHERE feed_id = ?", (f2,)).fetchone()[0] == orig
    # 기간 밖이면 중복이 아니다
    ids = store_entries(conn, f3, [_entry(guid="c", url="https://c.com/1", title="OpenAI announces new reasoning model GPT-9", published_at="2026-12-01T00:00:00+00:00")])
    assert len(ids) == 1


def test_duplicate_chain_points_to_root(conn):
    f1, f2, f3 = _feed(conn, "f1"), _feed(conn, "f2"), _feed(conn, "f3")
    [orig] = store_entries(conn, f1, [_entry(rss_content=LONG)])
    store_entries(conn, f2, [_entry(guid="b", url="https://b.com/x", title="다른 제목입니다 하나", rss_content=LONG)])
    store_entries(conn, f3, [_entry(guid="c", url="https://b.com/x", title="또 다른 제목입니다 둘")])
    assert conn.execute("SELECT duplicate_of FROM articles WHERE feed_id = ?", (f3,)).fetchone()[0] == orig
