import pytest
from fastapi.testclient import TestClient

from rss_wiki.db import connect
from rss_wiki.web.app import create_app
from rss_wiki.web.render import card_summary, render_markdown
from rss_wiki.wiki import current_revision, save_revision
from tests.fakes import seed_topic_articles

PAGE = """## 개요

AI 주제[^{a}].

## 현재 상황

현재 상황입니다[^{a}].

## 주요 흐름

- 흐름

## 쟁점과 관점

_아직 정리할 내용이 없습니다._

## 오늘 바뀐 점

- 새 칩 발표[^{a}]

## 관련 주제

_없음_

## 출처

[^{a}]: [AI 글 0](https://ex.com/AI/0) — Ex, 2026-10-01
"""


@pytest.fixture
def db(config):
    c = connect(config.db_path)
    yield c
    c.close()


@pytest.fixture
def client(config):
    return TestClient(create_app(config))


def _seed_page(db, name="AI", importance=4, start=0):
    tid, ids = seed_topic_articles(db, name, n=1, importance=importance, start=start)
    rid = save_revision(db, tid, PAGE.format(a=ids[0]), ids, ids, "claude-sonnet-5-5")
    return tid, ids, rid


def test_home_shows_updated_topics_sorted(client, db):
    low, _, _ = _seed_page(db, "낮은 중요도", importance=1)
    high, _, _ = _seed_page(db, "높은 중요도", importance=5, start=10)
    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    assert body.index("높은 중요도") < body.index("낮은 중요도")
    assert "새 칩 발표" in body and "[^" not in body


def test_home_empty_state(client):
    assert "오늘 갱신된 주제가 없습니다" in client.get("/").text


def test_topic_page_renders_footnotes_and_revisions(client, db):
    tid, ids, rid = _seed_page(db)
    r = client.get(f"/topics/{tid}")
    assert r.status_code == 200
    assert 'class="footnote"' in r.text and "https://ex.com/AI/0" in r.text
    assert f"/topics/{tid}/revisions/{rid}" in r.text
    assert client.get("/topics/999").status_code == 404


def test_revision_diff_and_restore(client, db):
    tid, ids, first = _seed_page(db)
    second = save_revision(db, tid, PAGE.format(a=ids[0]).replace("현재 상황입니다", "바뀐 상황"), ids, [], "m")
    r = client.get(f"/topics/{tid}/revisions/{second}")
    assert "-현재 상황입니다" in r.text and "+바뀐 상황" in r.text
    r = client.post(f"/topics/{tid}/revisions/{first}/restore", follow_redirects=False)
    assert r.status_code == 303
    assert current_revision(db, tid)["id"] == first
    assert client.post(f"/topics/{tid}/revisions/99999/restore").status_code == 404


def test_topic_management_rename_merge_hide_revert(client, db):
    a, _ = seed_topic_articles(db, "A", n=1)
    b, _ = seed_topic_articles(db, "B", n=1, start=5)
    client.post(f"/topics/{a}/rename", data={"name": "에이"})
    assert db.execute("SELECT name, user_locked FROM topics WHERE id = ?", (a,)).fetchone()[:] == ("에이", 1)
    r = client.post(f"/topics/{a}/rename", data={"name": "B"})
    assert "이미 있는 주제" in r.text
    client.post(f"/topics/{b}/status", data={"status": "hidden"})
    assert db.execute("SELECT status FROM topics WHERE id = ?", (b,)).fetchone()[0] == "hidden"
    client.post(f"/topics/{b}/merge", data={"target_id": a})
    assert db.execute("SELECT merged_into FROM topics WHERE id = ?", (b,)).fetchone()[0] == a
    assert client.get(f"/topics/{b}", follow_redirects=False).headers["location"] == f"/topics/{a}"

    page = client.get("/topics").text
    assert "병합" in page and "되돌리기" in page
    cid = db.execute("SELECT id FROM topic_changes WHERE type = 'merge'").fetchone()[0]
    client.post(f"/topics/changes/{cid}/revert")
    assert db.execute("SELECT merged_into FROM topics WHERE id = ?", (b,)).fetchone()[0] is None
    assert client.post(f"/topics/{a}/status", data={"status": "bogus"}).status_code == 400


def test_render_markdown_neutralizes_html_and_js_links():
    html = render_markdown('<script>alert(1)</script>\n\n[x](javascript:alert(1)) 그리고 A & B')
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "javascript:" not in html and "A &amp; B" in html


def test_card_summary_extracts_section():
    assert "새 칩 발표" in card_summary(PAGE.format(a=1)) and "현재 상황" not in card_summary(PAGE.format(a=1))


def test_d02_home_ranks_must_know_news_above_volume(client, db):
    """D-02: 중요도 3 단신 11개 주제보다 중요도 5 소식이 있는 주제가 먼저 나온다."""
    chip, chip_ids = seed_topic_articles(db, "반도체", n=11, importance=3)
    save_revision(db, chip, PAGE.format(a=chip_ids[0]), chip_ids, chip_ids, "m")
    ai, ai_ids = seed_topic_articles(db, "AI", n=1, importance=5, start=20)
    save_revision(db, ai, PAGE.format(a=ai_ids[0]), ai_ids, ai_ids, "m")
    body = client.get("/").text
    assert body.index(">AI<") < body.index(">반도체<")
