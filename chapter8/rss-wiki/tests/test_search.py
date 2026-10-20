from rss_wiki.db import utcnow
from rss_wiki.search import search
from rss_wiki.wiki import save_revision
from tests.fakes import seed_topic_articles


def _article(conn, feed_url, title, content, published="2026-10-05T00:00:00+00:00", status="done"):
    conn.execute("INSERT OR IGNORE INTO feeds(url, title, created_at) VALUES (?, ?, ?)", (feed_url, feed_url, utcnow()))
    fid = conn.execute("SELECT id FROM feeds WHERE url = ?", (feed_url,)).fetchone()[0]
    return conn.execute(
        "INSERT INTO articles(feed_id, guid, title, content, status, published_at, collected_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (fid, title, title, content, status, published, utcnow()),
    ).lastrowid, fid


def test_fts_articles_and_wiki(conn):
    a1, _ = _article(conn, "f1", "메모리 반도체 가격", "D램 가격이 <b>상승</b>했다")
    _article(conn, "f1", "날씨 소식", "맑음")
    tid, _ = seed_topic_articles(conn, "반도체", n=0)
    save_revision(conn, tid, "## 개요\n\n메모리 반도체 시장 정리", [], [], None)
    res = search(conn, "메모리 반도체")
    assert [a["id"] for a in res.articles] == [a1]
    assert "<mark>" in res.articles[0]["snippet"]
    assert [w["topic_id"] for w in res.wiki] == [tid]


def test_snippet_html_escaped(conn):
    _article(conn, "f1", "제목입니다", "본문 <script>alert(1)</script> 키워드를 포함")
    snip = search(conn, "키워드를").articles[0]["snippet"]
    assert "<script>" not in snip and "&lt;script&gt;" in snip and "<mark>키워드를</mark>" in snip


def test_short_terms_fall_back_to_like(conn):
    a1, _ = _article(conn, "f1", "AI 칩 경쟁", "엔비디아와 AMD")
    res = search(conn, "AI")
    assert [a["id"] for a in res.articles] == [a1] and "<mark>AI</mark>" in res.articles[0]["snippet"]
    tid, _ = seed_topic_articles(conn, "칩", n=0)
    save_revision(conn, tid, "AI 칩 정리", [], [], None)
    assert [w["topic_id"] for w in search(conn, "칩").wiki] == [tid]


def test_filters(conn):
    a1, f1 = _article(conn, "f1", "반도체 뉴스 하나", "본문", published="2026-10-01T00:00:00+00:00")
    a2, f2 = _article(conn, "f2", "반도체 뉴스 둘", "본문", published="2026-10-10T00:00:00+00:00")
    _article(conn, "f2", "반도체 뉴스 셋", "본문", status="duplicate")
    assert sorted(a["id"] for a in search(conn, "반도체").articles) == [a1, a2]
    assert [a["id"] for a in search(conn, "반도체", feed_id=f2).articles] == [a2]
    assert [a["id"] for a in search(conn, "반도체", since="2026-10-05").articles] == [a2]
    assert [a["id"] for a in search(conn, "반도체", until="2026-10-05").articles] == [a1]
    tid, _ = seed_topic_articles(conn, "T", n=0)
    conn.execute("INSERT INTO article_topics(article_id, topic_id) VALUES (?, ?)", (a1, tid))
    assert [a["id"] for a in search(conn, "반도체", topic_id=tid).articles] == [a1]


def test_hidden_topics_excluded_and_empty_query(conn):
    tid, _ = seed_topic_articles(conn, "숨김", n=0)
    save_revision(conn, tid, "비밀 내용입니다", [], [], None)
    conn.execute("UPDATE topics SET status = 'hidden' WHERE id = ?", (tid,))
    assert search(conn, "비밀 내용").wiki == []
    assert search(conn, "   ").articles == []


def test_quotes_in_query_are_safe(conn):
    _article(conn, "f1", '따옴표 "테스트" 제목', "본문")
    assert len(search(conn, '"테스트"').articles) == 1


def test_d10_wiki_snippet_hides_markdown_syntax(conn):
    tid, _ = seed_topic_articles(conn, "반도체", n=0)
    save_revision(conn, tid, "## 개요\n\n메모리 가격 반등[^14][^13]\n\n## 주요 흐름\n\n- 메모리 가격 상승[^2]", [], [], None)
    snip = search(conn, "메모리 가격").wiki[0]["snippet"]
    assert "[^" not in snip and "##" not in snip and "<mark>메모리</mark>" in snip
