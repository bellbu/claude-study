import httpx
import pytest

from rss_wiki.feeds import (
    FeedError, add_feed, delete_feed, discover_feed_links, export_opml, import_opml,
    list_feeds, set_feed_status,
)
from tests.fakes import make_rss, mock_client

RSS = make_rss([{"title": "hello"}], title="My Blog")


def test_add_feed_direct_url(conn):
    client = mock_client({"https://ex.com/feed.xml": httpx.Response(200, text=RSS)})
    fid = add_feed(conn, "https://ex.com/feed.xml", client)
    row = list_feeds(conn)[0]
    assert row["id"] == fid and row["title"] == "My Blog" and row["status"] == "active"


def test_add_feed_discovers_from_html(conn):
    html = '<html><head><link rel="alternate" type="application/rss+xml" href="/rss"></head></html>'
    client = mock_client({
        "https://blog.ex.com/": httpx.Response(200, text=html, headers={"content-type": "text/html"}),
        "https://blog.ex.com/rss": httpx.Response(200, text=RSS),
    })
    add_feed(conn, "https://blog.ex.com/", client)
    assert list_feeds(conn)[0]["url"] == "https://blog.ex.com/rss"


def test_add_feed_rejects_non_feed_and_duplicates(conn):
    client = mock_client({
        "https://ex.com/page": httpx.Response(200, text="<html>no feed</html>"),
        "https://ex.com/feed.xml": httpx.Response(200, text=RSS),
    })
    with pytest.raises(FeedError):
        add_feed(conn, "https://ex.com/page", client)
    add_feed(conn, "https://ex.com/feed.xml", client)
    with pytest.raises(FeedError):
        add_feed(conn, "https://ex.com/feed.xml", client)
    with pytest.raises(FeedError):
        add_feed(conn, "https://ex.com/missing", client)


def test_discover_resolves_relative_links():
    html = '<link rel="alternate" type="application/atom+xml" href="atom.xml"><link rel="stylesheet" href="x.css">'
    assert discover_feed_links(html, "https://ex.com/blog/") == ["https://ex.com/blog/atom.xml"]


def test_pause_and_delete(conn):
    client = mock_client({"https://ex.com/feed.xml": httpx.Response(200, text=RSS)})
    fid = add_feed(conn, "https://ex.com/feed.xml", client)
    set_feed_status(conn, fid, "paused")
    assert list_feeds(conn)[0]["status"] == "paused"
    with pytest.raises(ValueError):
        set_feed_status(conn, fid, "bogus")
    delete_feed(conn, fid)
    assert list_feeds(conn) == []


def test_opml_roundtrip(conn):
    opml = """<?xml version="1.0"?><opml version="2.0"><body>
      <outline text="Tech"><outline text="A" title="A" xmlUrl="https://a.com/rss" htmlUrl="https://a.com"/></outline>
      <outline text="B" xmlUrl="https://b.com/rss"/>
      <outline text="folder only"/>
    </body></opml>"""
    assert import_opml(conn, opml) == 2
    assert import_opml(conn, opml) == 0  # 중복은 건너뜀
    exported = export_opml(conn)
    assert 'xmlUrl="https://a.com/rss"' in exported and 'htmlUrl="https://a.com"' in exported
    conn.execute("DELETE FROM feeds")
    assert import_opml(conn, exported) == 2


def test_import_invalid_opml(conn):
    with pytest.raises(FeedError):
        import_opml(conn, "<opml><body>")
