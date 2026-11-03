"""본문 텍스트 변환·추출 (HTTP·DB 비의존, 문자열만 다룸)."""

from __future__ import annotations

import logging
import re
from html.parser import HTMLParser

import trafilatura

logger = logging.getLogger(__name__)

_SKIP_TAGS = {"script", "style"}


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    """HTML 조각을 평문으로 바꾼다 (태그·script·style 제거, 엔티티 해제, 공백 정리)."""
    if not html:
        return ""
    parser = _TextParser()
    parser.feed(html)
    parser.close()
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def extract_article(html: str | bytes, url: str | None = None) -> str | None:
    """원문 페이지에서 본문 텍스트를 추출한다. 실패하거나 본문이 없으면 None."""
    try:
        text = trafilatura.extract(html, url=url)
    except Exception as exc:  # noqa: BLE001 - 호출 측은 "추출 실패"만 알면 됨
        logger.debug("본문 추출 예외 (%s): %s", url, exc)
        return None
    if not text or not text.strip():
        return None
    return text
