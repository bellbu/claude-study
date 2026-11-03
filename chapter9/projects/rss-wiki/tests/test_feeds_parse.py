import logging
from pathlib import Path

import pytest

from rss_wiki.feeds import FeedParseError, parse_feed

FIX = Path(__file__).parent / "fixtures"


def load(name: str) -> bytes:
    return (FIX / name).read_bytes()


def test_rss2_basic():
    feed = parse_feed(load("rss2.xml"), "https://example.com/feed.xml")
    assert feed.title == "한국어 테크 블로그"
    assert len(feed.entries) == 3
    e = feed.entries[0]
    assert e.guid == "post-1"
    assert e.url == "https://example.com/posts/1"
    assert e.title == "첫 번째 글: 파이썬 3.14 소개"
    assert e.published_at == "2025-10-29T00:30:00Z"
    assert "<p>" in e.content and "파이썬 3.14" in e.content


def test_rss_missing_guid_uses_link():
    feed = parse_feed(load("rss2.xml"), "https://example.com/feed.xml")
    e = feed.entries[1]
    assert e.guid == e.url == "https://example.com/posts/2"
    assert e.published_at == "2025-10-28T00:00:00Z"


def test_entry_without_guid_and_link_skipped(caplog):
    with caplog.at_level(logging.WARNING, logger="rss_wiki.feeds"):
        feed = parse_feed(load("rss2.xml"), "https://example.com/feed.xml")
    assert all("세 번째" not in (e.title or "") for e in feed.entries)
    assert any("건너뜁니다" in r.message for r in caplog.records)


def test_missing_date_and_content():
    feed = parse_feed(load("rss2.xml"), "https://example.com/feed.xml")
    e = feed.entries[2]
    assert e.published_at is None
    assert e.content == ""


def test_atom_prefers_content_and_id():
    feed = parse_feed(load("atom.xml"), "https://example.org/atom.xml")
    assert feed.title == "Atom 예제 피드"
    first, second = feed.entries
    assert first.guid == "urn:uuid:entry-1"
    assert first.url == "https://example.org/a/1"
    assert first.content == "<p>전체 본문입니다.</p>"
    assert first.published_at == "2025-10-28T12:00:00Z"
    assert second.content == "요약만 있음"
    assert second.published_at == "2025-10-27T00:00:00Z"  # updated 폴백


def test_html_document_raises():
    with pytest.raises(FeedParseError) as exc:
        parse_feed(load("not_feed.html"), "https://example.com/")
    assert "https://example.com/" in str(exc.value)


def test_bozo_feed_still_parsed(caplog):
    with caplog.at_level(logging.DEBUG, logger="rss_wiki.feeds"):
        feed = parse_feed(load("rss2_bozo.xml"), "https://example.com/feed.xml")
    assert feed.title == "Bozo 피드"
    assert len(feed.entries) == 1
    e = feed.entries[0]
    assert e.guid == "https://example.com/bozo-1"
    assert e.url == "https://example.com/posts/bozo-1"
    # feedparser 느슨한 파서 동작 고정: 깨진 피드에서 `Q&A`가 `Q&A;`로 바뀜 (보정하지 않음)
    assert e.title == "Q&A; 시간"
    assert "Tom & Jerry" in e.content
    # 픽스처가 실제 bozo 경로를 탄다는 전제 고정
    assert any(
        r.name == "rss_wiki.feeds"
        and "피드 문법 경고" in r.getMessage()
        and "not well-formed" in r.getMessage()
        for r in caplog.records
    )


def test_relative_guid_and_link_resolved_against_base_url():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>t</title>
<item><title>x</title><link>/rel/1</link><guid>post-1</guid></item>
</channel></rss>""".encode()
    feed = parse_feed(xml, "https://example.com/feed.xml")
    e = feed.entries[0]
    assert e.guid == "https://example.com/post-1"
    assert e.url == "https://example.com/rel/1"


def test_korean_not_garbled():
    feed = parse_feed(load("rss2.xml"), "https://example.com/feed.xml")
    assert "한국어" in feed.title
    assert "파이썬" in feed.entries[0].title
