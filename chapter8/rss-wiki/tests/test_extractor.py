import httpx

from rss_wiki.dedup import store_entries
from rss_wiki.db import utcnow
from rss_wiki.extractor import extract_article, extract_content
from tests.fakes import mock_client

PARAS = [f"{i}번째 문단입니다. 반도체 업황이 회복되면서 {i}분기 주요 기업의 실적이 개선되고 있다는 분석이 나왔습니다." for i in range(1, 7)]
ARTICLE_HTML = f"""<html><head><title>t</title></head><body>
<nav>메뉴 홈 뉴스 로그인</nav>
<article><h1>반도체 업황 회복</h1>{"".join(f"<p>{p}</p>" for p in PARAS)}</article>
<footer>저작권 푸터</footer></body></html>"""


def _setup(conn, rss_content="<p>RSS 요약입니다</p>", url="https://ex.com/a"):
    fid = conn.execute("INSERT INTO feeds(url, created_at) VALUES (?, ?)", (f"feed:{url}", utcnow())).lastrowid
    [aid] = store_entries(conn, fid, [{"guid": url, "url": url, "title": "반도체", "rss_content": rss_content}])
    return aid


def test_extract_content_drops_boilerplate():
    text = extract_content(ARTICLE_HTML, "https://ex.com/a")
    assert "반도체 업황" in text and "메뉴 홈" not in text


def test_extracted_source(conn, config):
    aid = _setup(conn)
    client = mock_client({"https://ex.com/a": httpx.Response(200, text=ARTICLE_HTML, headers={"content-type": "text/html"})})
    assert extract_article(conn, aid, client, config) == "extracted"
    row = conn.execute("SELECT content, content_source FROM articles WHERE id = ?", (aid,)).fetchone()
    assert "실적이 개선" in row["content"] and row["content_source"] == "extracted"


def test_fallback_when_fetch_fails_or_too_short(conn, config):
    aid = _setup(conn)
    assert extract_article(conn, aid, mock_client({}), config) == "rss_fallback"
    row = conn.execute("SELECT content, content_source FROM articles WHERE id = ?", (aid,)).fetchone()
    assert row["content"] == "RSS 요약입니다" and row["content_source"] == "rss_fallback"

    short = "<html><body><article><p>짧은 글</p></article></body></html>"
    aid2 = _setup(conn, url="https://ex.com/b")
    client = mock_client({"https://ex.com/b": httpx.Response(200, text=short, headers={"content-type": "text/html"})})
    assert extract_article(conn, aid2, client, config) == "rss_fallback"


def test_duplicate_detected_after_extraction(conn, config):
    a1 = _setup(conn, url="https://ex.com/a")
    fid2 = conn.execute("INSERT INTO feeds(url, created_at) VALUES ('f2', ?)", (utcnow(),)).lastrowid
    [a2] = store_entries(conn, fid2, [{"guid": "x", "url": "https://mirror.com/z", "title": "전혀 다른 제목입니다", "rss_content": "요약"}])
    html = {"content-type": "text/html"}
    client = mock_client({
        "https://ex.com/a": httpx.Response(200, text=ARTICLE_HTML, headers=html),
        "https://mirror.com/z": httpx.Response(200, text=ARTICLE_HTML, headers=html),
    })
    extract_article(conn, a1, client, config)
    assert extract_article(conn, a2, client, config) == "duplicate"
    row = conn.execute("SELECT status, duplicate_of FROM articles WHERE id = ?", (a2,)).fetchone()
    assert row["status"] == "duplicate" and row["duplicate_of"] == a1
