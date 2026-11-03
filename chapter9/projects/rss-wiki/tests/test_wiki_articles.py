import json
import sqlite3
import subprocess
import sys

import pytest

from rss_wiki.db import connect, init_schema
from rss_wiki.wiki import (
    article_relpath,
    load_done_articles,
    render_article,
    slugify,
    write_articles,
)


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "t.db")
    init_schema(c)
    c.execute("INSERT INTO feeds (id, url, name) VALUES (1, 'https://e.com/f', '내 블로그')")
    yield c
    c.close()


_DEFAULT = object()


def add_article(conn, id, *, title="제목", published="2026-09-15T00:00:00Z", feed_id=1,
                status="done", tags=(), url=_DEFAULT, fetched="2026-10-01T00:00:00Z",
                tldr="요약입니다", key_points=_DEFAULT):
    if url is _DEFAULT:
        url = f"https://e.com/{id}"
    if key_points is _DEFAULT:
        key_points = json.dumps(["하나", "둘", "셋"], ensure_ascii=False)
    conn.execute(
        "INSERT INTO articles (id, feed_id, guid, url, title, published_at, content,"
        " content_source, fetched_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (id, feed_id, f"g{id}", url, title, published, "본문", "rss", fetched),
    )
    conn.execute(
        "INSERT INTO summaries (article_id, status, tldr, key_points, model, summarized_at)"
        " VALUES (?,?,?,?,?,?)",
        (id, status, tldr, key_points, "claude-haiku-5-5", "2026-10-02T00:00:00Z"),
    )
    for t in tags:
        conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (t,))
        conn.execute(
            "INSERT INTO article_tags SELECT ?, id FROM tags WHERE name = ?", (id, t)
        )


def first(conn):
    return load_done_articles(conn)[0]


def test_slugify():
    assert slugify("Hello, World!", 3) == "hello-world-3"
    assert slugify("파이썬 3.14 출시", 7) == "파이썬-3-14-출시-7"
    assert slugify(None, 5) == "article-5"
    assert slugify("???", 2) == "article-2"
    slug = slugify("a" * 200, 9)
    assert slug.endswith("-9") and len(slug[: -len("-9")]) <= 60


def test_relpath_uses_published_then_fetched(conn):
    add_article(conn, 1)
    add_article(conn, 2, published=None)
    rows = load_done_articles(conn)
    assert str(article_relpath(rows[0])).startswith("articles/2026/09/")
    assert str(article_relpath(rows[1])).startswith("articles/2026/10/")


def test_render_article(conn):
    add_article(conn, 1, title='제목: "따옴표"', tags=["b", "a"])
    out = render_article(first(conn), ["b", "a"])
    assert out.startswith("---\n")
    lines = out.split("\n")
    end = lines.index("---", 1)
    keys = [l.split(":", 1)[0] for l in lines[1:end]]
    assert keys == ["title", "url", "feed", "published", "summarized", "model", "tags"]
    assert json.loads(lines[1].split(": ", 1)[1]) == '제목: "따옴표"'
    assert json.loads(lines[end - 1].split(": ", 1)[1]) == ["a", "b"]
    assert "## TL;DR\n\n요약입니다" in out
    assert "- 하나\n- 둘\n- 셋" in out
    assert "[https://e.com/1](<https://e.com/1>)" in out
    assert out.endswith(")\n") and not out.endswith("\n\n")


def test_orphan_has_null_feed(conn):
    add_article(conn, 1, feed_id=None)
    assert "\nfeed: null\n" in render_article(first(conn), [])


def test_write_articles(conn, tmp_path):
    add_article(conn, 1, tags=["x"])
    add_article(conn, 2, status="pending")
    add_article(conn, 3, status="failed")
    add_article(conn, 4, title="한국어 글")
    wiki = tmp_path / "wiki"
    paths = write_articles(conn, wiki)
    assert len(paths) == 2 and paths[0].name.endswith("-1.md") and paths[1].name.endswith("-4.md")
    assert len(list(wiki.rglob("*.md"))) == 2
    snapshot = [p.read_bytes() for p in paths]
    assert all(b"\r\n" not in b for b in snapshot)
    snapshot[1].decode("utf-8")
    assert [p.read_bytes() for p in write_articles(conn, wiki)] == snapshot


def test_multiline_title_is_one_line_in_body_only(conn):
    add_article(conn, 1, title="line1\nline2")
    out = render_article(first(conn), [])
    assert "\n# line1 line2\n" in out
    assert json.loads(out.split("\n")[1].split(": ", 1)[1]) == "line1\nline2"


def test_carriage_returns_removed(conn, tmp_path):
    add_article(conn, 1, tldr="a\r\nb\rc",
                key_points=json.dumps(["x\r\ny", "  "], ensure_ascii=False))
    out = render_article(first(conn), [])
    assert "\r" not in out
    assert "## TL;DR\n\na\nb\nc\n" in out
    assert "- x y\n" in out and "- \n" not in out
    (path,) = write_articles(conn, tmp_path / "wiki")
    assert b"\r" not in path.read_bytes()


def test_source_link_escaping(conn):
    add_article(conn, 1, url="https://e.com/a_(b) c")
    add_article(conn, 2, url="https://e.com/[x]")
    add_article(conn, 3, url="https://e.com/<a>\nb")
    rows = load_done_articles(conn)
    assert "\n[https://e.com/a_(b) c](<https://e.com/a_(b)%20c>)\n" in render_article(rows[0], [])
    assert "\n[https://e.com/\\[x\\]](<https://e.com/[x]>)\n" in render_article(rows[1], [])
    assert "(<https://e.com/%3Ca%3E%20b>)" in render_article(rows[2], [])


def test_null_url_renders_dash(conn):
    add_article(conn, 1)
    row = dict(first(conn), url=None)
    assert render_article(row, []).endswith("## 원문\n\n-\n")


def test_unknown_month_fallback(conn):
    add_article(conn, 1, published="garbage", fetched="garbage")
    add_article(conn, 2, published="Mon, 01 Sep")
    rows = load_done_articles(conn)
    assert str(article_relpath(rows[0])).startswith("articles/unknown/")
    assert str(article_relpath(rows[0])).count("/") == 2
    assert str(article_relpath(rows[1])).startswith("articles/2026/10/")


def test_written_tags_sorted_and_mtime_stable(conn, tmp_path):
    add_article(conn, 1, tags=["zeta", "alpha", "mid"])
    paths = write_articles(conn, tmp_path / "wiki")
    front = paths[0].read_text(encoding="utf-8").split("\n")
    tags_line = next(l for l in front if l.startswith("tags: "))
    assert json.loads(tags_line[len("tags: "):]) == ["alpha", "mid", "zeta"]
    before = [p.stat().st_mtime_ns for p in paths]
    write_articles(conn, tmp_path / "wiki")
    assert [p.stat().st_mtime_ns for p in paths] == before


def test_null_key_points_and_title(conn):
    add_article(conn, 1, title=None, key_points=None)
    out = render_article(first(conn), [])
    assert "# (제목 없음)" in out
    assert "## 핵심 포인트\n\n\n## 원문" in out


def test_no_heavy_imports():
    code = "import sys, rss_wiki.wiki; print(any(m in sys.modules for m in ('rss_wiki.fetch','rss_wiki.extract','rss_wiki.claude')))"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.stdout.strip() == "False"
