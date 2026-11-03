"""요약 공급자 인터페이스(`Summarizer`), 응답 스키마 검증, 입력 절단, 프롬프트 생성.

LLM·DB·네트워크에 의존하지 않음. Claude 구현은 별도 모듈(T9), 명령 연동은 T10.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

MIN_KEY_POINTS = 3
MAX_KEY_POINTS = 5
MIN_TAGS = 1
MAX_TAGS = 5

# PRD 4.3 JSON 스키마. T9에서 구조화 출력에 그대로 사용.
SUMMARY_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "tldr": {"type": "string"},
        "key_points": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": MIN_KEY_POINTS,
            "maxItems": MAX_KEY_POINTS,
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": MIN_TAGS,
            "maxItems": MAX_TAGS,
        },
    },
    "required": ["tldr", "key_points", "tags"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class SummaryResult:
    tldr: str
    key_points: list[str]
    tags: list[str]


class SummaryValidationError(Exception):
    """응답이 스키마에 맞지 않음. 실패 1회로 셈(PRD 7장). 메시지에 어긋난 필드명 포함."""


class SummarizerError(Exception):
    """공급자 호출 실패. `transient`가 True면 재시도 대상(네트워크·429·과부하)."""

    def __init__(self, message: str, *, transient: bool = False):
        super().__init__(message)
        self.transient = transient


@runtime_checkable
class Summarizer(Protocol):
    """요약 공급자.

    구현은 `SummaryValidationError`와 `SummarizerError`만 밖으로 내야 하며,
    공급자 SDK의 예외는 이 둘로 감싸 던진다.
    """

    model: str

    def summarize(self, title: str | None, content: str, existing_tags: list[str]) -> SummaryResult: ...


def _string_list(data: dict, field: str) -> list[str]:
    value = data[field]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise SummaryValidationError(f"{field}는 문자열 배열이어야 합니다")
    return value


def validate_summary(data: object) -> SummaryResult:
    """LLM 응답(파싱된 JSON)을 검증해 `SummaryResult`로 변환. 추가 키는 무시."""
    if not isinstance(data, dict):
        raise SummaryValidationError("응답이 객체(dict)가 아닙니다")
    for field in ("tldr", "key_points", "tags"):
        if field not in data:
            raise SummaryValidationError(f"필수 필드 누락: {field}")

    tldr = data["tldr"]
    if not isinstance(tldr, str):
        raise SummaryValidationError("tldr는 문자열이어야 합니다")
    tldr = tldr.strip()
    if not tldr:
        raise SummaryValidationError("tldr가 비어 있습니다")

    key_points = [p.strip() for p in _string_list(data, "key_points")]
    if not MIN_KEY_POINTS <= len(key_points) <= MAX_KEY_POINTS:
        raise SummaryValidationError(
            f"key_points는 {MIN_KEY_POINTS}~{MAX_KEY_POINTS}개여야 합니다 (현재 {len(key_points)}개)"
        )
    if not all(key_points):
        raise SummaryValidationError("key_points에 빈 문자열이 있습니다")

    tags: list[str] = []
    for raw in _string_list(data, "tags"):
        tag = raw.strip().lower()
        if tag and tag not in tags:
            tags.append(tag)
    if not MIN_TAGS <= len(tags) <= MAX_TAGS:
        raise SummaryValidationError(f"tags는 {MIN_TAGS}~{MAX_TAGS}개여야 합니다 (정규화 후 {len(tags)}개)")

    return SummaryResult(tldr=tldr, key_points=key_points, tags=tags)


def truncate_input(text: str, max_chars: int) -> str:
    """`max_chars`를 넘으면 앞 `max_chars`자만 남김."""
    if max_chars <= 0:
        raise ValueError(f"max_chars는 양수여야 합니다: {max_chars}")
    return text if len(text) <= max_chars else text[:max_chars]


def build_prompt(title: str | None, content: str, existing_tags: list[str], max_chars: int) -> str:
    """요약 요청 프롬프트. 기존 태그는 정렬해 넣어 결정적임."""
    normalized = sorted({t.strip().lower() for t in existing_tags} - {""})
    tags = ", ".join(normalized) if normalized else "없음"
    lines = [
        "다음 글을 읽고 원문 언어와 관계없이 반드시 한국어로 요약하세요.",
        "- tldr: 1~2문장 요약",
        f"- key_points: 핵심 포인트 {MIN_KEY_POINTS}~{MAX_KEY_POINTS}개",
        f"- tags: 주제 태그 {MIN_TAGS}~{MAX_TAGS}개. 태그는 모두 소문자로 쓰세요.",
        f"기존 태그 목록(가능하면 재사용): {tags}",
        "",
    ]
    if title:
        lines.append(f"제목: {title}")
    lines += ["본문:", truncate_input(content, max_chars)]
    return "\n".join(lines)
