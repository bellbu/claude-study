import logging
from pathlib import Path

import trafilatura

from rss_wiki.extract import extract_article, html_to_text

ARTICLE = (Path(__file__).parent / "fixtures" / "article.html").read_text(encoding="utf-8")


def test_html_to_text_strips_tags_scripts_and_entities():
    assert html_to_text("<p>Tom &amp; Jerry</p><script>x()</script>  <b>굵게</b>") == "Tom & Jerry 굵게"


def test_html_to_text_empty():
    assert html_to_text("") == ""


def test_html_to_text_skips_style_and_collapses_whitespace():
    assert html_to_text("<style>p{}</style>\n<p>a \n\n b</p>") == "a b"


def test_extract_article_returns_body_only():
    text = extract_article(ARTICLE, url="https://example.com/post")
    assert text is not None
    assert len(text) >= 500
    assert "빌림 검사기는 하나의 가변 참조" in text
    assert "SCRIPT-ONLY-TEXT" not in text
    assert "FOOTER" not in text


def test_html_to_text_inline_tag_inserts_space():
    # 길이 판정 전용 동작 고정: 인라인 태그 경계에도 공백이 들어간다. 저장·요약 입력에는 쓰지 않는다.
    assert html_to_text("un<b>bold</b>") == "un bold"


def test_extract_article_accepts_bytes():
    text = extract_article(ARTICLE.encode("utf-8"))
    assert text is not None
    assert "빌림 검사기는 하나의 가변 참조" in text


def test_extract_article_without_body_returns_none():
    assert extract_article("<html><body></body></html>") is None
    assert extract_article("") is None


def test_extract_article_swallows_exceptions(monkeypatch, caplog):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(trafilatura, "extract", boom)
    with caplog.at_level(logging.DEBUG, logger="rss_wiki.extract"):
        assert extract_article(ARTICLE, url="https://example.com/x") is None
    assert any("https://example.com/x" in r.getMessage() for r in caplog.records)
