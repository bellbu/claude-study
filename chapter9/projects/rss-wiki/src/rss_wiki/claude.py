"""Anthropic SDK 기반 `Summarizer` 구현.

구조화 출력은 `record_summary` 강제 도구 호출로 받는다(strict 미사용). 개수 같은 스키마 제약은
모델에 주는 안내일 뿐이므로 `validate_summary`가 최종 방어선이다. SDK 자체 재시도는 끄고
재시도는 호출 측(T10 정책)이 맡는다.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

import anthropic

from rss_wiki.config import Config, ConfigError
from rss_wiki.summarize import (
    SUMMARY_SCHEMA,
    SummarizerError,
    SummaryResult,
    SummaryValidationError,
    build_prompt,
    validate_summary,
)

TOOL_NAME = "record_summary"
API_KEY_ENV = "ANTHROPIC_API_KEY"
MIN_API_TIMEOUT = 60.0  # LLM 응답은 피드 GET보다 오래 걸리므로 http_timeout의 하한을 둠


class ClaudeSummarizer:
    """`Summarizer` 프로토콜 구현. `SummaryValidationError`·`SummarizerError`만 밖으로 낸다."""

    def __init__(self, client, model: str, max_input_chars: int = 20000, max_tokens: int = 1024):
        self.client = client
        self.model = model
        self.max_input_chars = max_input_chars
        self.max_tokens = max_tokens

    def summarize(self, title: str | None, content: str, existing_tags: list[str]) -> SummaryResult:
        prompt = build_prompt(title, content, existing_tags, self.max_input_chars)
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                tools=[
                    {
                        "name": TOOL_NAME,
                        "description": "글의 한국어 요약(tldr, key_points, tags)을 기록한다.",
                        "input_schema": SUMMARY_SCHEMA,
                    }
                ],
                tool_choice={"type": "tool", "name": TOOL_NAME},
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIConnectionError as exc:
            raise self._wrap(exc, type(exc).__name__, transient=True) from exc
        except anthropic.APIStatusError as exc:
            # 429·5xx(529 과부하 포함)만 일시적 오류. SDK의 예외 클래스 계층에 의존하지 않고 상태 코드로 판단.
            transient = exc.status_code == 429 or exc.status_code >= 500
            raise self._wrap(exc, f"HTTP {exc.status_code}", transient=transient) from exc
        except anthropic.AnthropicError as exc:
            raise self._wrap(exc, type(exc).__name__, transient=False) from exc

        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == TOOL_NAME:
                return validate_summary(block.input)
        raise SummaryValidationError(
            f"tool_use 응답 없음 (model={self.model}, stop_reason={getattr(response, 'stop_reason', None)})"
        )

    def _wrap(self, exc: Exception, cause: str, *, transient: bool) -> SummarizerError:
        # 예외 원문(str(exc))은 쓰지 않음: 요청 정보가 섞일 수 있어 모델명과 원인 종류만 남긴다.
        return SummarizerError(f"요약 호출 실패 (model={self.model}, {cause})", transient=transient)


def create_claude_summarizer(config: Config, env: Mapping[str, str] = os.environ) -> ClaudeSummarizer:
    """`ANTHROPIC_API_KEY`가 없거나 비었으면 `ConfigError`(치명적 오류)."""
    api_key = env.get(API_KEY_ENV, "")
    if not api_key.strip():
        raise ConfigError(f"{API_KEY_ENV} 환경 변수가 없습니다")
    client = anthropic.Anthropic(
        api_key=api_key,
        max_retries=0,
        timeout=max(float(config.http_timeout), MIN_API_TIMEOUT),
    )
    return ClaudeSummarizer(client, config.model, max_input_chars=config.max_input_chars)
