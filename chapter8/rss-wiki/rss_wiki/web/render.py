"""위키 Markdown 렌더링과 홈 카드용 추출."""

from __future__ import annotations

import re
from datetime import datetime

import markdown

FOOTNOTE_REF = re.compile(r"\[\^\d+\]")
JS_HREF = re.compile(r'href="\s*javascript:[^"]*"', re.I)


def render_markdown(text: str) -> str:
    """LLM이 쓴 Markdown을 HTML로. 원문에서 온 HTML이 실행되지 않도록 '<'를 먼저 이스케이프한다."""
    safe = text.replace("&", "&amp;").replace("<", "&lt;")
    html = markdown.markdown(
        safe,
        extensions=["footnotes", "sane_lists"],
        extension_configs={"footnotes": {"BACKLINK_TITLE": "본문 %d번 각주로 돌아가기"}},
    )
    return JS_HREF.sub('href="#"', html)


def extract_section(content: str, title: str) -> str:
    m = re.search(rf"^## {re.escape(title)}\s*\n(.*?)(?=^## |\Z)", content, re.S | re.M)
    return m.group(1).strip() if m else ""


def card_summary(content: str) -> str:
    """홈 카드용 '오늘 바뀐 점' (각주 표시 제거)."""
    return render_markdown(FOOTNOTE_REF.sub("", extract_section(content, "오늘 바뀐 점")))


def localtime(value: str | None, fmt: str = "%Y-%m-%d %H:%M") -> str:
    if not value:
        return "-"
    try:
        return datetime.fromisoformat(value).astimezone().strftime(fmt)
    except ValueError:
        return value


def safe_url(url: str | None) -> str:
    """피드에서 온 URL은 http(s)만 링크로 쓴다."""
    if url and url.strip().lower().startswith(("http://", "https://")):
        return url.strip()
    return "#"


def duration(started: str | None, finished: str | None) -> str:
    """작업 소요 시간 (끝나지 않았으면 '실행 중')."""
    if not started or not finished:
        return "실행 중"
    seconds = int((datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds())
    return f"{seconds // 60}분 {seconds % 60}초" if seconds >= 60 else f"{seconds}초"
