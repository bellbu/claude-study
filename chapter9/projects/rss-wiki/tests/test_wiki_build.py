import json
import sqlite3

import pytest

from rss_wiki.cli import main
from rss_wiki.db import DatabaseError, connect, init_schema
from rss_wiki.wiki import build_wiki, topic_filenames


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    init_schema(c)
    c.execute("INSERT INTO feeds (id, url, name) VALUES (1, 'https://e.com/f', '블로그')")
    yield c
    c.close()


def add(conn, id, *, tags, published, status="done", title=None):
    conn.execute(
        "INSERT INTO articles (id, feed_id, guid, url, title, published_at, content,"
        " content_source, fetched_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (id, 1, f"g{id}", f"https://e.com/{id}", title or f"글 {id}", published, "본문", "rss",
         "2026-10-01T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO summaries (article_id, status, tldr, key_points, model, summarized_at)"
        " VALUES (?,?,?,?,?,?)",
        (id, status, f"요약 {id}\n둘째 문단", json.dumps(["a"]), "m", "2026-10-02T00:00:00Z"),
    )
    for t in tags:
        conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (t,))
        conn.execute("INSERT INTO article_tags SELECT ?, id FROM tags WHERE name = ?", (id, t))


def seed(conn):
    # done: 1, 2 (python), 3 (ai); 4 is pending, so its tag must not get a page
    add(conn, 1, tags=["python"], published="2026-08-01T00:00:00Z")
    add(conn, 2, tags=["python"], published="2026-09-15T00:00:00Z")
    add(conn, 3, tags=["ai"], published="2026-09-20T00:00:00Z")
    add(conn, 4, tags=["pending-only"], published="2026-09-21T00:00:00Z", status="pending")


def snapshot(root):
    snap = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            st = p.stat()
            snap[p.relative_to(root).as_posix()] = (p.read_bytes(), st.st_mtime_ns)
    return snap


def test_topic_and_index(conn, tmp_path):
    seed(conn)
    wiki = tmp_path / "wiki"
    r = build_wiki(conn, wiki)
    assert (r.articles, r.topics, r.removed) == (3, 2, 0)
    topic = (wiki / "topics" / "python.md").read_text(encoding="utf-8")
    lines = [l for l in topic.splitlines() if l.startswith("- ")]
    assert [l.split("](")[0] for l in lines] == ["- [글 2", "- [글 1"]
    assert "요약 2 둘째 문단" in lines[0]
    for l in lines:
        rel = l.split("(<")[1].split(">)")[0]
        assert (wiki / "topics" / rel).resolve().is_file()
    assert not (wiki / "topics" / "pending-only.md").exists()
    index = (wiki / "index.md").read_text(encoding="utf-8")
    index_lines = index.splitlines()
    assert index_lines.index("- [python](<topics/python.md>) (2)") < index_lines.index(
        "- [ai](<topics/ai.md>) (1)"
    )
    recent = index.split("## 최근 요약")[1]
    assert recent.index("글 3") < recent.index("글 2") < recent.index("글 1")


def test_idempotent_build(conn, tmp_path):
    seed(conn)
    wiki = tmp_path / "wiki"
    build_wiki(conn, wiki)
    first = snapshot(wiki)
    build_wiki(conn, wiki)
    assert snapshot(wiki) == first


def test_prune_stale(conn, tmp_path):
    seed(conn)
    wiki = tmp_path / "wiki"
    build_wiki(conn, wiki)
    (wiki / "notes.txt").write_text("keep", encoding="utf-8")
    conn.execute("UPDATE summaries SET status='pending' WHERE article_id = 3")
    r = build_wiki(conn, wiki)
    assert r.articles == 2 and r.removed == 2  # article 3 file + ai topic page (now 0 articles)
    assert not (wiki / "topics" / "ai.md").exists()
    assert [p.name for p in (wiki / "articles" / "2026" / "09").iterdir()] == ["글-2-2.md"]
    assert (wiki / "notes.txt").exists()
    # remove the last 2026/09 article too: month dir must vanish
    conn.execute("UPDATE summaries SET status='pending' WHERE article_id = 2")
    build_wiki(conn, wiki)
    assert not (wiki / "articles" / "2026" / "09").exists()


def test_topic_filename_collisions():
    names = topic_filenames(["c++", "c", "con", "", "!!"])
    assert names["c"] == "c.md" and names["c++"] == "c-2.md"
    assert names["con"] == "con-2.md"
    assert len(set(names.values())) == len(names)
    assert topic_filenames(["c++", "c"]) == topic_filenames(["c", "c++"])


def test_empty_db_index(conn, tmp_path):
    r = build_wiki(conn, tmp_path / "wiki")
    assert (r.articles, r.topics, r.removed) == (0, 0, 0)
    assert (tmp_path / "wiki" / "index.md").read_text(encoding="utf-8").count("(없음)") == 2


def test_cli_build(tmp_path, capsys):
    data = tmp_path / "d"
    assert main(["--data-dir", str(data), "init"]) == 0
    c = connect(data / "data" / "rss-wiki.db")
    c.execute("INSERT INTO feeds (id, url, name) VALUES (1, 'https://e.com/f', '블로그')")
    for i in (1, 2, 3):
        add(c, i, tags=["python"], published=f"2026-09-0{i}T00:00:00Z")
    c.close()
    capsys.readouterr()
    assert main(["--data-dir", str(data), "build"]) == 0
    assert "글 3건" in capsys.readouterr().out


def test_cli_build_wiki_is_file(tmp_path, capsys):
    data = tmp_path / "d"
    assert main(["--data-dir", str(data), "init"]) == 0
    c = connect(data / "data" / "rss-wiki.db")
    c.execute("INSERT INTO feeds (id, url, name) VALUES (1, 'https://e.com/f', '블로그')")
    add(c, 1, tags=["python"], published="2026-09-01T00:00:00Z")
    c.close()
    wiki = data / "wiki"
    wiki.rmdir()
    wiki.write_text("x", encoding="utf-8")
    capsys.readouterr()
    assert main(["--data-dir", str(data), "build"]) == 2
    err = capsys.readouterr().err
    assert "wiki" in err and "Traceback" not in err


def test_title_brackets_escaped(conn, tmp_path):
    add(conn, 1, tags=["x"], published="2026-09-01T00:00:00Z", title="a [b] c")
    build_wiki(conn, tmp_path / "wiki")
    topic = (tmp_path / "wiki" / "topics" / "x.md").read_text(encoding="utf-8")
    assert r"- [a \[b\] c](<../articles/" in topic


def test_missing_schema_raises_database_error(tmp_path):
    c = connect(tmp_path / "empty.db")  # init_schema deliberately skipped
    try:
        with pytest.raises(DatabaseError, match="위키 조회 실패") as exc:
            build_wiki(c, tmp_path / "wiki")
    finally:
        c.close()
    assert isinstance(exc.value.__cause__, sqlite3.Error)


def test_index_recent_limited_to_20(conn, tmp_path):
    for i in range(1, 22):
        add(conn, i, tags=["x"], published=f"2026-09-{i:02d}T00:00:00Z")
    wiki = tmp_path / "wiki"
    build_wiki(conn, wiki)
    index = (wiki / "index.md").read_text(encoding="utf-8")
    items = index.split("## 최근 요약")[1].splitlines()
    items = [l for l in items if l.startswith("- ")]
    assert len(items) == 20
    assert not any(l.startswith("- [글 1](") for l in items)  # oldest dropped
    assert items[0].startswith("- [글 21](")
    for l in items:
        rel = l.split("(<")[1].split(">)")[0]
        assert rel.startswith("articles/")
        assert (wiki / rel).is_file()
