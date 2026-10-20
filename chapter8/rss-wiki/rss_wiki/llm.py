"""Claude API 래퍼: 구조화 JSON 응답, 사용량·비용 기록, 일일 비용 상한."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, time, timezone
from typing import Any

import anthropic

from rss_wiki.config import Config, WIKI_MODEL
from rss_wiki.db import get_setting, utcnow

# USD / 1M 토큰 (입력, 출력). 캐시 쓰기는 입력가의 1.25배, 캐시 읽기는 0.1배.
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
}
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(Exception):
    pass


class BudgetExceeded(LLMError):
    pass


def estimate_cost(model: str, usage: Any) -> float:
    in_price, out_price = PRICES.get(model, PRICES[WIKI_MODEL])
    uncached = getattr(usage, "input_tokens", 0) or 0
    cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
    output = getattr(usage, "output_tokens", 0) or 0
    return (
        uncached * in_price + cache_write * in_price * 1.25 + cache_read * in_price * 0.1 + output * out_price
    ) / 1_000_000


def today_start_utc() -> str:
    """로컬 시간 기준 오늘 0시를 UTC ISO 문자열로."""
    local_midnight = datetime.combine(datetime.now().date(), time.min).astimezone()
    return local_midnight.astimezone(timezone.utc).isoformat(timespec="seconds")


def spent_today(conn: sqlite3.Connection) -> float:
    row = conn.execute(
        "SELECT coalesce(sum(cost_usd), 0) FROM llm_usage WHERE created_at >= ?", (today_start_utc(),)
    ).fetchone()
    return float(row[0])


def budget_remaining(conn: sqlite3.Connection) -> float:
    return float(get_setting(conn, "daily_budget_usd")) - spent_today(conn)


class LLMClient:
    def __init__(self, conn: sqlite3.Connection, config: Config, client: Any | None = None) -> None:
        self.conn = conn
        self.config = config
        self._client = client
        self.job_run_id: int | None = None

    @property
    def client(self) -> Any:
        if self._client is None:
            if not self.config.anthropic_api_key:
                raise LLMError("ANTHROPIC_API_KEY가 설정되지 않았습니다")
            self._client = anthropic.Anthropic(api_key=self.config.anthropic_api_key)
        return self._client

    def check_budget(self) -> None:
        if budget_remaining(self.conn) <= 0:
            raise BudgetExceeded("일일 LLM 비용 상한에 도달했습니다")

    def complete_json(
        self,
        *,
        model: str,
        purpose: str,
        system: str,
        user: str,
        schema: dict,
        max_tokens: int = 4000,
        effort: str = "low",
    ) -> dict:
        self.check_budget()
        params: dict[str, Any] = dict(
            model=model,
            max_tokens=max_tokens,
            # 시스템 프롬프트는 호출마다 같으므로 캐시한다
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        )
        try:
            if model == WIKI_MODEL:
                # Sonnet 5.5는 안전 분류기 거절 시 서버 측 폴백 모델로 재시도
                response = self.client.beta.messages.create(
                    **params, betas=[FALLBACK_BETA], fallbacks="default"
                )
            else:
                response = self.client.messages.create(**params)
        except anthropic.APIConnectionError as e:
            raise LLMError(f"API 연결 실패: {e}") from e
        except anthropic.RateLimitError as e:
            raise LLMError(f"API 요청 한도 초과: {e}") from e
        except anthropic.APIStatusError as e:
            raise LLMError(f"API 오류 {e.status_code}: {e.message}") from e

        self._record_usage(model, purpose, response.usage)
        if response.stop_reason == "refusal":
            raise LLMError("모델이 요청을 거절했습니다")
        if response.stop_reason == "max_tokens":
            raise LLMError("응답이 max_tokens에서 잘렸습니다")
        text = next((b.text for b in response.content if b.type == "text"), None)
        if text is None:
            raise LLMError("응답에 텍스트가 없습니다")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMError(f"JSON 파싱 실패: {e}") from e

    def _record_usage(self, model: str, purpose: str, usage: Any) -> None:
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        self.conn.execute(
            "INSERT INTO llm_usage(job_run_id, model, purpose, input_tokens, output_tokens, cost_usd, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                self.job_run_id, model, purpose,
                (usage.input_tokens or 0) + cache_write + cache_read, usage.output_tokens or 0,
                estimate_cost(model, usage), utcnow(),
            ),
        )
        self.conn.commit()


def usage_summary(conn: sqlite3.Connection, since: str | None = None) -> list[sqlite3.Row]:
    since = since or today_start_utc()
    return conn.execute(
        "SELECT model, purpose, count(*) AS calls, sum(input_tokens) AS input_tokens, "
        "sum(output_tokens) AS output_tokens, sum(cost_usd) AS cost_usd "
        "FROM llm_usage WHERE created_at >= ? GROUP BY model, purpose ORDER BY cost_usd DESC",
        (since,),
    ).fetchall()
