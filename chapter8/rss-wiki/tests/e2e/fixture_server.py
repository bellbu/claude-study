"""E2E용 픽스처 서버: RSS 피드·원문 HTML·사이트와 Mock Claude Messages API를 한 프로세스에서 제공한다.

단독 실행(브라우저 E2E용): python tests/e2e/fixture_server.py --port 8701
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import threading
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

BASE_TIME = datetime(2026, 10, 19, 0, 0, tzinfo=timezone.utc)


def _paragraphs(topic: str, n: int = 6) -> str:
    return "".join(
        f"<p>{topic} 관련 {i}번째 문단입니다. 업계 관계자들은 {i}분기 동안 {topic} 분야의 변화가 이어질 것으로 내다봤습니다.</p>"
        for i in range(1, n + 1)
    )


class State:
    def __init__(self, base_url: str) -> None:
        self.base = base_url
        self.lock = threading.Lock()
        self.requests: dict[str, list[dict]] = {}
        self.claude_calls: list[dict] = []
        self.flaky_hits = 0
        # Mock Claude 동작 제어
        self.wiki_bad_cite_topics: set[str] = set()
        self.merge_plan: list[tuple[str, str]] = []
        self.feeds: dict[str, list[dict]] = {
            "tech": [
                self.item("tech-1", "[AI] 새 언어 모델 공개 !!", "ai-model"),
                self.item("tech-2", "[반도체] 메모리 가격 반등", "memory"),
                self.item("tech-3", "[광고] 이번 주 특가 할인 이벤트", "ad"),
            ],
            "news": [
                # tech-1과 같은 글 (추적 파라미터만 다름) → 중복
                self.item("news-1", "AI 모델 공개 소식 정리", "ai-model", query="?utm_source=news&utm_medium=rss"),
                self.item("news-2", "[인공지능] 국내 연구소 인공지능 투자 확대", "ai-invest"),
                self.item(
                    "news-3", "[보안] <script>alert('x')</script> 보안 점검", "missing-article",
                    link="javascript:alert(1)",
                ),
            ],
            "many": [self.item(f"many-{i}", f"[반도체] 반도체 단신 {i}", f"chip-{i}", hours=i) for i in range(15)],
            "blog": [self.item("blog-1", "[AI] 블로그 글", "missing-blog")],
            "flaky": [self.item("flaky-1", "[반도체] 재시도 끝에 받은 글", "missing-flaky")],
            "llmfail": [self.item("llmfail-1", "[AI] LLM오류 유발 글", "missing-llm")],
        }
        self.articles = {
            "ai-model": ("새 언어 모델 공개", "AI 모델"),
            "memory": ("메모리 가격 반등", "메모리 반도체"),
            "ai-invest": ("인공지능 투자 확대", "인공지능 투자"),
            "ad": ("특가 할인", "할인 이벤트"),
            **{f"chip-{i}": (f"반도체 단신 {i}", f"반도체 단신 {i}") for i in range(15)},
        }

    def item(self, guid: str, title: str, slug: str, query: str = "", link: str | None = None, hours: int = 0) -> dict:
        return {
            "guid": guid, "title": title,
            "link": link or f"{self.base}/articles/{slug}.html{query}",
            "published": BASE_TIME + timedelta(hours=hours),
            "description": f"{title}에 대한 RSS 요약입니다.",
        }

    def record(self, path: str, status: int, headers: dict) -> None:
        with self.lock:
            self.requests.setdefault(path, []).append({"status": status, "headers": headers})


def rss_xml(title: str, items: list[dict]) -> str:
    def esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    body = "".join(
        f"<item><title>{esc(it['title'])}</title><link>{esc(it['link'])}</link>"
        f"<guid isPermaLink=\"false\">{it['guid']}</guid><pubDate>{format_datetime(it['published'])}</pubDate>"
        f"<description>{esc(it['description'])}</description></item>"
        for it in items
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
        f"<title>{title}</title><link>https://example.test/</link><description>e2e</description>{body}</channel></rss>"
    )


# ---------------- Mock Claude ----------------

TOPIC_RULES = [("인공지능", "인공지능"), ("[AI]", "AI 모델"), ("AI 모델", "AI 모델"), ("반도체", "반도체"), ("보안", "보안")]


def mock_summarize(user: str) -> dict:
    title = re.search(r"제목: (.*)", user).group(1)
    existing = re.findall(r"^- ([^:\n]+):", user.split("</existing_topics>")[0], re.M)
    if "광고" in title:
        return {"summary": "광고 글입니다.", "key_points": [], "topics": [], "importance": 1,
                "skip": True, "skip_reason": "광고"}
    name = next((topic for key, topic in TOPIC_RULES if key in title), "기타 소식")
    return {
        "summary": f"{title} — 요약 문장입니다. 핵심 내용을 정리했습니다.",
        "key_points": [f"{name} 관련 핵심 1", f"{name} 관련 핵심 2"],
        "topics": [{"name": name, "description": f"{name} 관련 소식", "is_new": name not in existing}],
        "importance": 5 if "!!" in title else 3,
        "skip": False, "skip_reason": "",
    }


def mock_wiki(user: str, state: State) -> dict:
    topic = re.search(r"이름: (.*)", user).group(1)
    new_part = user.split("<new_articles>")[1].split("</new_articles>")[0]
    old_part = user.split("<previous_articles>")[1].split("</previous_articles>")[0]
    new = re.findall(r'<article id="(\d+)"', new_part)
    old = re.findall(r'<article id="(\d+)"', old_part)
    titles = re.findall(r"제목: (.*)", new_part)
    cite = lambda ids: "".join(f"[^{i}]" for i in ids)  # noqa: E731
    if topic in state.wiki_bad_cite_topics:
        new = ["99999"]
    others = user.split("<other_topics>")[1].split("</other_topics>")[0].strip()
    return {
        "overview": f"{topic}에 관한 소식을 모은 페이지입니다.",
        "current_status": f"{topic} 분야는 최근 {len(new) + len(old)}건의 소식이 있었습니다{cite(new + old)}.",
        "timeline": "\n".join(f"- 10-19 {t}{cite([i])}" for t, i in zip(titles, new)) + (f"\n- 이전 소식{cite(old)}" if old else ""),
        "perspectives": "",
        "todays_changes": "\n".join(f"- {t}{cite([i])}" for t, i in zip(titles, new)),
        "related_topics": [others.split(", ")[0]] if others else [],
    }


def mock_maintain(user: str, state: State) -> dict:
    ids = {name: int(tid) for tid, name in re.findall(r'<topic id="(\d+)"[^>]*>\n이름: (.*)', user)}
    merges = [
        {"source_id": ids[s], "target_id": ids[t], "reason": "같은 범위"}
        for s, t in state.merge_plan if s in ids and t in ids
    ]
    return {"merges": merges, "renames": []}


class Handler(BaseHTTPRequestHandler):
    state: State

    def log_message(self, *args) -> None:  # 조용히
        pass

    def _send(self, status: int, body: str | bytes = b"", ctype: str = "text/plain; charset=utf-8", headers=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)
        path = urlsplit(self.path).path
        if not path.startswith("/_"):
            self.state.record(path, status, {k.lower(): v for k, v in self.headers.items()})

    def do_GET(self) -> None:
        s = self.state
        path = urlsplit(self.path).path
        if path == "/_stats":
            with s.lock:
                payload = {
                    "requests": {p: [r["status"] for r in v] for p, v in s.requests.items()},
                    "last_headers": {p: v[-1]["headers"] for p, v in s.requests.items()},
                    "claude_calls": s.claude_calls,
                }
            self.wfile.flush()
            return self._send(200, json.dumps(payload, ensure_ascii=False, default=str), "application/json")
        if m := re.fullmatch(r"/feeds/(\w+)\.xml", path):
            name = m.group(1)
            if name == "broken":
                return self._send(503, "unavailable")
            if name == "flaky":
                with s.lock:
                    s.flaky_hits += 1
                    hit = s.flaky_hits
                if hit == 1:
                    return self._send(429, "slow down", headers={"Retry-After": "1"})
            if name not in s.feeds:
                return self._send(404, "no feed")
            xml = rss_xml(f"{name.capitalize()} Feed", s.feeds[name])
            etag = '"' + hashlib.md5(xml.encode()).hexdigest() + '"'
            if self.headers.get("If-None-Match") == etag:
                return self._send(304, b"", headers={"ETag": etag})
            return self._send(200, xml, "application/rss+xml; charset=utf-8", {"ETag": etag})
        if path == "/site/blog.html":
            html = f'<html><head><link rel="alternate" type="application/rss+xml" href="{s.base}/feeds/blog.xml"></head><body>blog</body></html>'
            return self._send(200, html, "text/html; charset=utf-8")
        if path == "/site/plain.html":
            return self._send(200, "<html><body>피드 없음</body></html>", "text/html; charset=utf-8")
        if m := re.fullmatch(r"/articles/([\w-]+)\.html", path):
            art = s.articles.get(m.group(1))
            if art is None:
                return self._send(404, "no article")
            heading, topic = art
            html = (
                "<html><head><title>t</title></head><body><nav>메뉴 홈 로그인 구독하기</nav>"
                f"<article><h1>{heading}</h1>{_paragraphs(topic)}</article><footer>푸터 저작권</footer></body></html>"
            )
            return self._send(200, html, "text/html; charset=utf-8")
        return self._send(404, "not found")

    def do_POST(self) -> None:
        s = self.state
        path = urlsplit(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        if path == "/_control":
            with s.lock:
                if "add_item" in body:
                    a = body["add_item"]
                    s.feeds[a["feed"]].insert(0, s.item(a["guid"], a["title"], a.get("slug", f"missing-{a['guid']}"), hours=48))
                if "wiki_bad_cite_topics" in body:
                    s.wiki_bad_cite_topics = set(body["wiki_bad_cite_topics"])
                if "merge_plan" in body:
                    s.merge_plan = [tuple(x) for x in body["merge_plan"]]
            return self._send(200, "{}", "application/json")
        if path == "/v1/messages":
            return self._claude(body)
        return self._send(404, "not found")

    def _claude(self, body: dict) -> None:
        s = self.state
        user = body["messages"][0]["content"]
        schema = body["output_config"]["format"]["schema"]["properties"]
        call = {
            "model": body["model"],
            "purpose": "summarize" if "skip" in schema else ("maintain" if "merges" in schema else "wiki"),
            "format_type": body["output_config"]["format"]["type"],
            "effort": body["output_config"].get("effort"),
            "system_cache": body["system"][0].get("cache_control"),
            "fallbacks": body.get("fallbacks"),
            "beta_header": self.headers.get("anthropic-beta"),
            "api_key": self.headers.get("x-api-key"),
            "user": user,
        }
        with s.lock:
            s.claude_calls.append(call)
        if call["purpose"] == "summarize" and "LLM오류" in user:
            err = {"type": "error", "error": {"type": "api_error", "message": "mock failure"}}
            return self._send(500, json.dumps(err), "application/json", {"x-should-retry": "false"})
        if call["purpose"] == "summarize":
            result = mock_summarize(user)
        elif call["purpose"] == "maintain":
            result = mock_maintain(user, s)
        else:
            result = mock_wiki(user, s)
        text = json.dumps(result, ensure_ascii=False)
        resp = {
            "id": f"msg_e2e_{len(s.claude_calls)}", "type": "message", "role": "assistant", "model": body["model"],
            "content": [{"type": "text", "text": text}], "stop_reason": "end_turn", "stop_sequence": None,
            "usage": {"input_tokens": len(json.dumps(body)) // 4, "output_tokens": len(text) // 4,
                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
        }
        self._send(200, json.dumps(resp, ensure_ascii=False), "application/json")


def start(port: int = 0) -> tuple[ThreadingHTTPServer, State]:
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    state = State(f"http://127.0.0.1:{server.server_address[1]}")
    Handler.state = state
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, state


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8701)
    args = parser.parse_args()
    srv, st = start(args.port)
    print(f"fixture server on {st.base}", flush=True)
    threading.Event().wait()
