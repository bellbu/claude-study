from types import SimpleNamespace as NS

import pytest

from rss_wiki.db import set_setting
from rss_wiki.llm import BudgetExceeded, LLMClient, LLMError, estimate_cost, spent_today, usage_summary
from tests.fakes import FakeAnthropic

SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"], "additionalProperties": False}


def _call(llm, model="claude-haiku-5-5"):
    return llm.complete_json(model=model, purpose="test", system="sys", user="hi", schema=SCHEMA)


def test_returns_parsed_json_and_records_usage(conn, config):
    fake = FakeAnthropic({"x": 1}, usage=(1_000_000, 1_000_000))
    llm = LLMClient(conn, config, fake)
    assert _call(llm) == {"x": 1}
    params = fake.calls[0]
    assert params["output_config"]["format"]["schema"] == SCHEMA
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    row = conn.execute("SELECT * FROM llm_usage").fetchone()
    assert row["model"] == "claude-haiku-5-5" and row["purpose"] == "test"
    assert row["cost_usd"] == pytest.approx(0.60)
    assert spent_today(conn) == pytest.approx(0.60)
    assert usage_summary(conn)[0]["calls"] == 1


def test_wiki_model_uses_server_side_fallback(conn, config):
    fake = FakeAnthropic({"x": 2})
    _call(LLMClient(conn, config, fake), model="claude-sonnet-5-5")
    assert fake.calls[0]["fallbacks"] == "default"
    assert fake.calls[0]["betas"] == ["server-side-fallback-2026-07-01"]


def test_budget_exceeded_blocks_calls(conn, config):
    set_setting(conn, "daily_budget_usd", "0.5")
    fake = FakeAnthropic({"x": 1}, usage=(1_000_000, 1_000_000))
    llm = LLMClient(conn, config, fake)
    _call(llm)  # 0.6 사용 → 상한 초과
    with pytest.raises(BudgetExceeded):
        _call(llm)
    assert len(fake.calls) == 1


def test_invalid_json_and_stop_reasons(conn, config):
    with pytest.raises(LLMError):
        _call(LLMClient(conn, config, FakeAnthropic("not json")))
    with pytest.raises(LLMError):
        _call(LLMClient(conn, config, FakeAnthropic({"x": 1}, stop_reason="refusal")))
    with pytest.raises(LLMError):
        _call(LLMClient(conn, config, FakeAnthropic({"x": 1}, stop_reason="max_tokens")))


def test_api_errors_wrapped(conn, config):
    import anthropic
    import httpx2

    req = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    err = anthropic.APIConnectionError(request=req)
    with pytest.raises(LLMError):
        _call(LLMClient(conn, config, FakeAnthropic(lambda p: err)))


def test_missing_api_key(conn, tmp_path):
    from rss_wiki.config import Config

    with pytest.raises(LLMError):
        _call(LLMClient(conn, Config(data_dir=tmp_path, anthropic_api_key=None)))


def test_estimate_cost_with_cache():
    usage = NS(input_tokens=0, output_tokens=0, cache_creation_input_tokens=1_000_000, cache_read_input_tokens=1_000_000)
    assert estimate_cost("claude-sonnet-5-5", usage) == pytest.approx(2.0 * 1.25 + 0.2)
