import sqlite3

import pytest

from rss_wiki.db import DatabaseError, connect, init_schema

TABLES = {"feeds", "articles", "summaries", "tags", "article_tags"}


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "sub" / "dir" / "test.db")
    init_schema(c)
    yield c
    c.close()


def _feed(conn, url="https://example.com/feed.xml"):
    return conn.execute("INSERT INTO feeds (url, name) VALUES (?, 'f')", (url,)).lastrowid


def _article(conn, feed_id, guid="g1"):
    return conn.execute(
        "INSERT INTO articles (feed_id, guid, url, title, fetched_at) VALUES (?, ?, 'u', 't', 'now')",
        (feed_id, guid),
    ).lastrowid


def test_connect_creates_parent_dirs_and_enables_fk(tmp_path):
    path = tmp_path / "a" / "b" / "x.db"
    c = connect(path)
    try:
        assert path.parent.is_dir()
        assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        c.close()


def test_init_schema_idempotent_and_tables(conn):
    init_schema(conn)
    init_schema(conn)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert TABLES <= names


def test_feed_url_unique(conn):
    _feed(conn)
    with pytest.raises(sqlite3.IntegrityError):
        _feed(conn)


def test_article_guid_unique_per_feed(conn):
    f1 = _feed(conn)
    f2 = _feed(conn, "https://example.com/other.xml")
    _article(conn, f1)
    _article(conn, f2)  # same guid, different feed: ok
    with pytest.raises(sqlite3.IntegrityError):
        _article(conn, f1)


def test_summary_status_check(conn):
    a = _article(conn, _feed(conn))
    for status in ("pending", "done", "failed"):
        conn.execute("DELETE FROM summaries")
        conn.execute("INSERT INTO summaries (article_id, status) VALUES (?, ?)", (a, status))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE summaries SET status='bogus' WHERE article_id=?", (a,))


def test_summary_article_id_is_pk(conn):
    a = _article(conn, _feed(conn))
    conn.execute("INSERT INTO summaries (article_id, status) VALUES (?, 'pending')", (a,))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO summaries (article_id, status) VALUES (?, 'done')", (a,))


def test_tags_unique_and_article_tags_pk(conn):
    a = _article(conn, _feed(conn))
    t = conn.execute("INSERT INTO tags (name) VALUES ('ai')").lastrowid
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO tags (name) VALUES ('ai')")
    conn.execute("INSERT INTO article_tags (article_id, tag_id) VALUES (?, ?)", (a, t))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO article_tags (article_id, tag_id) VALUES (?, ?)", (a, t))


def test_feed_removal_keeps_articles(conn):
    f = _feed(conn)
    _article(conn, f)
    conn.execute("DELETE FROM feeds WHERE id=?", (f,))
    assert conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 1


def test_utf8_roundtrip(conn):
    conn.execute("INSERT INTO tags (name) VALUES ('한글')")
    assert conn.execute("SELECT name FROM tags").fetchone()[0] == "한글"


def test_directory_as_db_raises_database_error(tmp_path):
    with pytest.raises(DatabaseError):
        connect(tmp_path)


def test_corrupt_file_raises_database_error(tmp_path):
    path = tmp_path / "corrupt.db"
    path.write_bytes(b"this is definitely not a sqlite database" * 100)
    with pytest.raises(DatabaseError):
        connect(path)


def test_init_schema_on_closed_connection_raises_database_error(tmp_path):
    c = connect(tmp_path / "closed.db")
    c.close()
    with pytest.raises(DatabaseError):
        init_schema(c)


def test_content_source_check(conn):
    f = _feed(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO articles (feed_id, guid, url, fetched_at, content_source)"
            " VALUES (?, 'g', 'u', 'now', 'bogus')",
            (f,),
        )


def test_article_delete_cascades(conn):
    a = _article(conn, _feed(conn))
    t = conn.execute("INSERT INTO tags (name) VALUES ('ai')").lastrowid
    conn.execute("INSERT INTO summaries (article_id, status) VALUES (?, 'pending')", (a,))
    conn.execute("INSERT INTO article_tags (article_id, tag_id) VALUES (?, ?)", (a, t))
    conn.execute("DELETE FROM articles WHERE id=?", (a,))
    assert conn.execute("SELECT COUNT(*) FROM summaries").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM article_tags").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0] == 1


def test_connect_closes_connection_on_failure(tmp_path, monkeypatch):
    opened = []
    real_connect = sqlite3.connect

    class Spy:
        def __init__(self, conn):
            self._conn = conn
            self.closed = False

        def execute(self, *a, **k):
            raise sqlite3.DatabaseError("boom")

        def close(self):
            self.closed = True
            self._conn.close()

    def fake_connect(*a, **k):
        spy = Spy(real_connect(*a, **k))
        opened.append(spy)
        return spy

    monkeypatch.setattr(sqlite3, "connect", fake_connect)
    with pytest.raises(DatabaseError):
        connect(tmp_path / "x.db")
    assert len(opened) == 1 and opened[0].closed
