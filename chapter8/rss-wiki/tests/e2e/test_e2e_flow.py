"""E2E 시나리오: 실제 서버 프로세스 + 픽스처 서버(RSS·원문·Mock Claude). docs/qa/TEST_CASES.md의 TC ID를 따른다.

테스트는 파일 순서대로 실행되며 앞 단계의 상태를 이어받는다.
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from tests.e2e import fixture_server

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.e2e


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class E2E:
    def __init__(self, tmp: Path) -> None:
        self.fixture, self.state = fixture_server.start()
        self.fx = self.state.base
        self.port = _free_port()
        self.data_dir = tmp / "data"
        self.log_path = tmp / "server.log"
        self.env = {
            **os.environ,
            "RSS_WIKI_DATA_DIR": str(self.data_dir),
            "RSS_WIKI_PORT": str(self.port),
            "ANTHROPIC_API_KEY": "e2e-dummy-key",
            "ANTHROPIC_BASE_URL": self.fx,
            "PYTHONUTF8": "1",
        }
        self.log = open(self.log_path, "w", encoding="utf-8")
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "rss_wiki", "serve"], cwd=ROOT, env=self.env, stdout=self.log, stderr=subprocess.STDOUT,
        )
        self.http = httpx.Client(base_url=f"http://127.0.0.1:{self.port}", follow_redirects=True, timeout=30)
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                if self.http.get("/").status_code == 200:
                    return
            except httpx.TransportError:
                time.sleep(0.3)
        raise RuntimeError("서버가 시작되지 않았습니다: " + self.log_path.read_text(encoding="utf-8"))

    def close(self) -> None:
        self.http.close()
        self.proc.terminate()
        self.proc.wait(timeout=10)
        self.log.close()
        self.fixture.shutdown()

    # --- 도우미 ---
    def db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.data_dir / "rss_wiki.db")
        conn.row_factory = sqlite3.Row
        return conn

    def q(self, sql: str, *params):
        with self.db() as conn:
            return conn.execute(sql, params).fetchall()

    def one(self, sql: str, *params):
        rows = self.q(sql, *params)
        return rows[0][0] if rows else None

    def run_job(self, job_type: str, timeout: float = 90) -> tuple[str, dict]:
        last = self.one("SELECT coalesce(max(id), 0) FROM job_runs")
        r = self.http.post(f"/jobs/{job_type}")
        assert r.status_code == 200 and "시작했습니다" in r.text
        deadline = time.time() + timeout
        while time.time() < deadline:
            rows = self.q("SELECT status, stats FROM job_runs WHERE id > ? AND finished_at IS NOT NULL", last)
            if rows:
                return rows[0]["status"], json.loads(rows[0]["stats"])
            time.sleep(0.3)
        raise TimeoutError(f"{job_type} 작업이 끝나지 않았습니다")

    def fx_stats(self) -> dict:
        return httpx.get(f"{self.fx}/_stats").json()

    def control(self, **body) -> None:
        httpx.post(f"{self.fx}/_control", json=body).raise_for_status()

    def opml(self, *feeds: str) -> httpx.Response:
        outlines = "".join(f'<outline text="{f}" xmlUrl="{self.fx}/feeds/{f}.xml"/>' for f in feeds)
        doc = f'<?xml version="1.0"?><opml version="2.0"><body>{outlines}</body></opml>'.encode()
        return self.http.post("/feeds/import", files={"file": ("subs.opml", doc, "text/xml")})

    def topic_id(self, name: str) -> int:
        return self.one("SELECT id FROM topics WHERE name = ?", name)

    def article(self, guid: str) -> sqlite3.Row:
        return self.q("SELECT * FROM articles WHERE guid = ?", guid)[0]

    def calls(self, purpose: str | None = None) -> list[dict]:
        return [c for c in self.fx_stats()["claude_calls"] if purpose is None or c["purpose"] == purpose]


@pytest.fixture(scope="module")
def e2e(tmp_path_factory):
    env = E2E(tmp_path_factory.mktemp("e2e"))
    yield env
    env.close()


def test_sec02_server_binds_localhost_only(e2e):
    assert f"Uvicorn running on http://127.0.0.1:{e2e.port}" in e2e.log_path.read_text(encoding="utf-8")


def test_feed01_04_add_feeds(e2e):
    r = e2e.http.post("/feeds", data={"url": f"{e2e.fx}/feeds/tech.xml"})
    assert "피드를 추가했습니다" in r.text and "Tech Feed" in r.text  # TC-FEED-01
    r = e2e.http.post("/feeds", data={"url": f"{e2e.fx}/site/blog.html"})
    assert e2e.one("SELECT url FROM feeds WHERE title = 'Blog Feed'") == f"{e2e.fx}/feeds/blog.xml"  # TC-FEED-02
    r = e2e.http.post("/feeds", data={"url": f"{e2e.fx}/site/plain.html"})
    assert "추가하지 못했습니다: 피드를 찾지 못했습니다" in r.text  # TC-FEED-03
    r = e2e.http.post("/feeds", data={"url": f"{e2e.fx}/feeds/tech.xml"})
    assert "이미 구독 중인 피드입니다" in r.text  # TC-FEED-04
    assert e2e.one("SELECT count(*) FROM feeds") == 2


def test_feed07_09_opml(e2e):
    assert "피드 3개를 가져왔습니다" in e2e.opml("news", "many", "flaky").text  # TC-FEED-07
    assert "피드 0개를 가져왔습니다" in e2e.opml("news").text  # 중복 건너뜀
    exported = e2e.http.get("/feeds/export")
    assert exported.headers["content-type"].startswith("text/x-opml")  # TC-FEED-08
    for name in ("tech", "blog", "news", "many", "flaky"):
        assert f'xmlUrl="{e2e.fx}/feeds/{name}.xml"' in exported.text
    r = e2e.http.post("/feeds/import", files={"file": ("bad.opml", b"<opml><body>", "text/xml")})
    assert r.status_code == 200 and "OPML 파싱 실패" in r.text  # TC-FEED-09


def test_col01_first_collect_pipeline(e2e):
    status, stats = e2e.run_job("collect")
    assert status == "ok" and stats["failed"] == 0  # TC-COL-01
    assert e2e.one("SELECT count(*) FROM articles a JOIN feeds f ON f.id = a.feed_id WHERE f.url LIKE '%/many.xml'") == 10  # TC-COL-03
    assert e2e.fx_stats()["requests"]["/feeds/flaky.xml"] == [429, 200]  # TC-COL-04
    assert e2e.one("SELECT count(*) FROM fetch_logs") == 0

    dup, orig = e2e.article("news-1"), e2e.article("tech-1")
    assert dup["status"] == "duplicate" and dup["duplicate_of"] == orig["id"]  # TC-DUP-01
    assert not any("AI 모델 공개 소식 정리" in c["user"] for c in e2e.calls("summarize"))
    assert orig["content_source"] == "extracted" and "메뉴 홈" not in orig["content"]  # TC-EXT-01
    assert e2e.article("blog-1")["content_source"] == "rss_fallback"  # TC-EXT-02

    assert e2e.article("tech-3")["status"] == "skipped"  # TC-SUM-05
    assert e2e.one("SELECT count(*) FROM article_topics WHERE article_id = ?", e2e.article("tech-3")["id"]) == 0
    names = sorted(r[0] for r in e2e.q("SELECT name FROM topics"))
    assert names == ["AI 모델", "반도체", "보안", "인공지능"]  # TC-SUM-04: 반도체 글 12개가 한 주제로
    assert any("- 반도체: 반도체 관련 소식" in c["user"] for c in e2e.calls("summarize"))

    for c in e2e.calls("summarize"):  # TC-SUM-02, TC-SUM-03
        assert c["model"] == "claude-haiku-5-5" and c["format_type"] == "json_schema"
        assert c["system_cache"] == {"type": "ephemeral"} and c["api_key"] == "e2e-dummy-key"
        assert c["fallbacks"] is None

    page = e2e.http.get(f"/articles/{orig['id']}").text  # TC-SUM-01
    assert "요약 문장입니다" in page and "AI 모델 관련 핵심 1" in page and "원문 추출" in page and "중요도 5" in page


def test_col02_conditional_get(e2e):
    status, stats = e2e.run_job("collect")
    assert status == "ok" and stats["new_articles"] == 0 and stats["not_modified"] == 5
    assert e2e.fx_stats()["requests"]["/feeds/tech.xml"][-1] == 304
    assert e2e.fx_stats()["last_headers"]["/feeds/tech.xml"]["if-none-match"].startswith('"')


def test_wiki01_first_wiki_build(e2e):
    status, stats = e2e.run_job("wiki")
    assert status == "ok" and len(stats["updated"]) == 4 and stats["failed"] == {}
    for c in e2e.calls("wiki") + e2e.calls("maintain"):  # TC-SUM-02, TC-SUM-03
        assert c["model"] == "claude-sonnet-5-5" and c["fallbacks"] == "default"
        assert "server-side-fallback-2026-07-01" in c["beta_header"]
    assert len(e2e.calls("maintain")) == 1

    ai = e2e.topic_id("AI 모델")
    page = e2e.http.get(f"/topics/{ai}").text  # TC-WIKI-01
    for heading in ("개요", "현재 상황", "주요 흐름", "쟁점과 관점", "오늘 바뀐 점", "관련 주제", "출처"):
        assert f"<h2>{heading}</h2>" in page
    assert 'class="footnote"' in page and f"{e2e.fx}/articles/ai-model.html" in page
    assert "같은 소식:" in page and "ai-model.html?utm_source=news" in page  # TC-DUP-03

    home = e2e.http.get("/").text  # TC-WIKI-07
    assert "[^" not in home and "새 언어 모델 공개" in home
    assert home.index("AI 모델") < home.index("인공지능")  # 중요도 5 글이 있는 주제가 먼저


def test_sec01_script_and_javascript_links_neutralized(e2e):
    sec = e2e.article("news-3")
    for path in (f"/articles/{sec['id']}", f"/topics/{e2e.topic_id('보안')}", "/articles"):
        body = e2e.http.get(path).text
        assert "<script>alert" not in body and 'href="javascript:' not in body.lower()


def test_wiki02_05_incremental_update_diff_restore(e2e):
    e2e.control(add_item={"feed": "tech", "guid": "tech-4", "title": "[AI] 후속 모델 발표"})
    e2e.run_job("collect")
    ai = e2e.topic_id("AI 모델")
    before = {r["topic_id"]: r["n"] for r in e2e.q("SELECT topic_id, count(*) n FROM wiki_revisions GROUP BY topic_id")}
    n_wiki_calls = len(e2e.calls("wiki"))
    status, stats = e2e.run_job("wiki")
    assert stats["updated"] == [ai]  # TC-WIKI-02
    after = {r["topic_id"]: r["n"] for r in e2e.q("SELECT topic_id, count(*) n FROM wiki_revisions GROUP BY topic_id")}
    assert after[ai] == before[ai] + 1 and all(after[t] == n for t, n in before.items() if t != ai)

    prompt = e2e.calls("wiki")[n_wiki_calls]["user"]  # TC-WIKI-03
    current = prompt.split("<current_page>")[1].split("</current_page>")[0]
    assert current.strip().startswith("## 개요") and "## 출처" not in current and "후속 모델 발표" in prompt

    first, second = [r[0] for r in e2e.q("SELECT id FROM wiki_revisions WHERE topic_id = ? ORDER BY id", ai)]
    rev_page = e2e.http.get(f"/topics/{ai}/revisions/{second}").text  # TC-WIKI-05
    assert '<span class="add">+' in rev_page and '<span class="del">-' in rev_page
    r = e2e.http.post(f"/topics/{ai}/revisions/{first}/restore")
    assert "리비전을 되돌렸습니다" in r.text
    assert e2e.one("SELECT id FROM wiki_revisions WHERE topic_id = ? AND is_current = 1", ai) == first
    e2e.http.post(f"/topics/{ai}/revisions/{second}/restore")


def test_wiki04_validation_failure_keeps_previous(e2e):
    e2e.control(add_item={"feed": "many", "guid": "many-new", "title": "[반도체] 신규 공장 착공"}, wiki_bad_cite_topics=["반도체"])
    e2e.run_job("collect")
    chip = e2e.topic_id("반도체")
    revs_before = e2e.one("SELECT count(*) FROM wiki_revisions WHERE topic_id = ?", chip)
    n_calls = len(e2e.calls("wiki"))
    status, stats = e2e.run_job("wiki")
    assert status == "ok" and str(chip) in stats["failed"]
    assert any("존재하지 않는 글ID" in e for e in stats["failed"][str(chip)])
    chip_calls = [c for c in e2e.calls("wiki")[n_calls:] if "이름: 반도체" in c["user"]]
    assert len(chip_calls) == 2 and "<previous_attempt_errors>" in chip_calls[1]["user"]
    assert e2e.one("SELECT count(*) FROM wiki_revisions WHERE topic_id = ?", chip) == revs_before
    e2e.control(wiki_bad_cite_topics=[])
    status, stats = e2e.run_job("wiki")  # 정상으로 돌아오면 다시 반영된다
    assert stats["updated"] == [chip]


def test_top01_auto_merge_and_revert(e2e):
    ai, ai2 = e2e.topic_id("AI 모델"), e2e.topic_id("인공지능")
    e2e.control(merge_plan=[["인공지능", "AI 모델"]])
    status, stats = e2e.run_job("wiki")
    assert stats["topics"]["merged"] == 1
    assert e2e.one("SELECT merged_into FROM topics WHERE id = ?", ai2) == ai
    assert e2e.http.get(f"/topics/{ai2}").url.path == f"/topics/{ai}"
    assert ai in stats["updated"]  # 옮겨 온 글 때문에 대상 주제가 재작성된다
    page = e2e.http.get("/topics").text
    assert "자동" in page and "병합" in page
    e2e.control(merge_plan=[])
    cid = e2e.one("SELECT id FROM topic_changes WHERE type = 'merge'")
    assert "변경을 되돌렸습니다" in e2e.http.post(f"/topics/changes/{cid}/revert").text
    assert e2e.one("SELECT merged_into FROM topics WHERE id = ?", ai2) is None
    assert e2e.one("SELECT count(*) FROM article_topics WHERE topic_id = ?", ai2) == 1


def test_top02_03_user_rename_and_hide(e2e):
    sec = e2e.topic_id("보안")
    e2e.http.post(f"/topics/{sec}/rename", data={"name": "정보 보안"})
    assert e2e.q("SELECT name, user_locked FROM topics WHERE id = ?", sec)[0][:] == ("정보 보안", 1)  # TC-TOP-02
    assert "고정" in e2e.http.get("/topics").text
    e2e.http.post(f"/topics/{sec}/status", data={"status": "hidden"})  # TC-TOP-03
    assert "정보 보안" not in e2e.http.get("/").text
    assert "/topics/%d" % sec not in e2e.http.get("/search", params={"q": "소식을 모은"}).text
    e2e.http.post(f"/topics/{sec}/status", data={"status": "active"})


def test_col05_08_fetch_failures(e2e):
    e2e.opml("broken", "gone")
    status, stats = e2e.run_job("collect")
    assert status == "ok" and stats["failed"] == 2 and stats["ok"] + stats["not_modified"] == 5  # TC-COL-08
    req = e2e.fx_stats()["requests"]
    assert req["/feeds/broken.xml"] == [503] * 4  # TC-COL-05
    assert req["/feeds/gone.xml"] == [404]  # TC-COL-06
    logs = {r["url"].rsplit("/", 1)[1]: r for r in e2e.q(
        "SELECT f.url, l.error_type, l.attempt_no, l.http_status FROM fetch_logs l JOIN feeds f ON f.id = l.feed_id")}
    assert (logs["broken.xml"]["error_type"], logs["broken.xml"]["attempt_no"]) == ("server_error", 4)
    assert (logs["gone.xml"]["error_type"], logs["gone.xml"]["attempt_no"]) == ("client_error", 1)

    e2e.run_job("collect")  # TC-COL-07
    assert e2e.q("SELECT consecutive_failures, status FROM feeds WHERE url LIKE '%broken.xml'")[0][:] == (2, "active")
    assert "연속 2회 실패" in e2e.http.get("/").text
    assert "server_error (503)" in e2e.http.get("/feeds").text

    for name in ("broken", "gone"):  # TC-FEED-05
        fid = e2e.one("SELECT id FROM feeds WHERE url LIKE ?", f"%/{name}.xml")
        e2e.http.post(f"/feeds/{fid}/status", data={"status": "paused"})
    e2e.run_job("collect")
    assert e2e.fx_stats()["requests"]["/feeds/broken.xml"] == [503] * 8


def test_sum06_llm_error_pending_then_failed(e2e):
    e2e.opml("llmfail")
    states = []
    for _ in range(3):
        e2e.run_job("collect")
        a = e2e.article("llmfail-1")
        states.append((a["status"], a["retry_count"]))
    assert states == [("pending", 1), ("pending", 2), ("failed", 3)]
    aid = e2e.article("llmfail-1")["id"]
    assert "다시 처리" in e2e.http.get(f"/articles/{aid}").text
    e2e.http.post(f"/articles/{aid}/retry")
    assert e2e.q("SELECT status, retry_count FROM articles WHERE id = ?", aid)[0][:] == ("pending", 0)
    fid = e2e.one("SELECT feed_id FROM articles WHERE id = ?", aid)
    e2e.http.post(f"/feeds/{fid}/delete")  # 이후 단계에 영향이 없도록 정리 (TC-FEED-06)
    assert e2e.one("SELECT count(*) FROM articles WHERE id = ?", aid) == 0


SETTINGS = {"collect_interval_minutes": "60", "wiki_hour": "6", "wiki_minute": "0", "daily_budget_usd": "1.0",
            "page_max_chars": "4000", "archive_after_days": "30"}


def test_set01_02_and_sum07_08_budget(e2e):
    r = e2e.http.post("/settings", data={**SETTINGS, "wiki_hour": "24", "page_max_chars": "많이"})  # TC-SET-02
    assert "0~23 범위" in r.text and "숫자가 아닙니다" in r.text
    assert e2e.one("SELECT count(*) FROM settings") == 0
    r = e2e.http.post("/settings", data={**SETTINGS, "daily_budget_usd": "0.00001"})  # TC-SET-01
    assert "설정을 저장했습니다" in r.text and 'value="1e-05"' in r.text
    assert "비용 상한에 도달했습니다" in e2e.http.get("/").text  # TC-SUM-07 배너

    e2e.control(add_item={"feed": "tech", "guid": "tech-5", "title": "[AI] 상한 이후 들어온 글"})
    n_calls = len(e2e.calls())
    status, stats = e2e.run_job("collect")
    assert status == "budget_exceeded" and stats["budget_exceeded"] is True
    assert len(e2e.calls()) == n_calls and e2e.article("tech-5")["status"] == "pending"
    jobs = e2e.http.get("/jobs").text
    assert "비용 상한" in jobs and "claude-haiku-5-5" in jobs and "claude-sonnet-5-5" in jobs  # TC-SUM-08

    e2e.http.post("/settings", data=SETTINGS)
    status, stats = e2e.run_job("collect")
    assert status == "ok" and e2e.article("tech-5")["status"] == "done"


def test_srch01_02_search(e2e):
    r = e2e.http.get("/search", params={"q": "메모리 가격"})  # TC-SRCH-01
    assert "<mark>메모리</mark>" in r.text and "메모리 가격 반등" in r.text
    wiki = e2e.http.get("/search", params={"q": "소식을 모은"}).text
    assert "위키 페이지 (4)" in wiki
    short = e2e.http.get("/search", params={"q": "AI"}).text  # TC-SRCH-02
    assert "<mark>AI</mark>" in short
    # 브라우저 폼은 비어 있는 select 값도 그대로 보낸다 (D-01 회귀 방지)
    form = e2e.http.get("/search", params={"q": "메모리 가격", "feed_id": "", "topic_id": "", "since": "", "until": ""})
    assert form.status_code == 200 and "<mark>메모리</mark>" in form.text
    assert e2e.http.get("/articles", params={"status": "", "feed_id": "", "topic_id": ""}).status_code == 200


def test_ops01_markdown_export(e2e, tmp_path):
    out = tmp_path / "export"
    proc = subprocess.run(
        [sys.executable, "-m", "rss_wiki", "export", "--out", str(out)], cwd=ROOT, env=e2e.env,
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    files = sorted(p.name for p in out.glob("*.md"))
    assert files == ["AI-모델.md", "index.md", "반도체.md", "인공지능.md", "정보-보안.md"]
    text = (out / "AI-모델.md").read_text(encoding="utf-8")
    assert "/topics/" not in text and text.startswith("# AI 모델")
