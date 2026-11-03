import json

import anthropic
import httpx2 as httpx
import pytest

from rss_wiki.claude import ClaudeSummarizer, create_claude_summarizer
from rss_wiki.config import Config, ConfigError
from rss_wiki.summarize import (
    SUMMARY_SCHEMA,
    Summarizer,
    SummarizerError,
    SummaryResult,
    SummaryValidationError,
)

API_KEY = "sk-test-secret-key"
GOOD = {"tldr": "요약", "key_points": ["a", "b", "c"], "tags": ["Python", "AI"]}


def message(content, stop_reason="tool_use"):
    return {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }


def tool_use(data):
    return {"type": "tool_use", "id": "tu_1", "name": "record_summary", "input": data}


def make(handler, **kw):
    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = anthropic.Anthropic(api_key=API_KEY, max_retries=0, http_client=http)
    return ClaudeSummarizer(client, "claude-haiku-5-5", **kw)


def ok_handler(requests, body=None):
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json=body or message([tool_use(GOOD)]))

    return handler


def test_success_and_request_shape():
    reqs = []
    s = make(ok_handler(reqs))
    r = s.summarize("제목입니다", "본문", ["rust"])
    assert r == SummaryResult("요약", ["a", "b", "c"], ["python", "ai"])
    req = reqs[0]
    assert req["model"] == "claude-haiku-5-5"
    assert req["tool_choice"] == {"type": "tool", "name": "record_summary"}
    assert req["tools"][0]["input_schema"] == SUMMARY_SCHEMA
    prompt = req["messages"][0]["content"]
    assert "한국어" in prompt and "제목입니다" in prompt and "rust" in prompt


def test_long_content_truncated():
    reqs = []
    s = make(ok_handler(reqs), max_input_chars=100)
    s.summarize(None, "가" * 25000, [])
    prompt = reqs[0]["messages"][0]["content"]
    assert "가" * 100 in prompt and "가" * 101 not in prompt


def test_too_few_key_points_is_validation_error():
    bad = {**GOOD, "key_points": ["a", "b"]}
    s = make(ok_handler([], message([tool_use(bad)])))
    with pytest.raises(SummaryValidationError, match="key_points"):
        s.summarize("t", "c", [])


@pytest.mark.parametrize(
    "body",
    [
        message([{"type": "text", "text": "요약해 드립니다"}], stop_reason="end_turn"),
        message([], stop_reason="max_tokens"),
    ],
)
def test_missing_tool_use_is_validation_error(body):
    s = make(ok_handler([], body))
    with pytest.raises(SummaryValidationError, match="tool_use"):
        s.summarize("t", "c", [])


@pytest.mark.parametrize("status, transient", [(429, True), (500, True), (529, True), (400, False), (401, False)])
def test_http_errors_mapped(status, transient):
    def handler(request):
        return httpx.Response(status, json={"type": "error", "error": {"type": "x", "message": "boom"}})

    s = make(handler)
    with pytest.raises(SummarizerError) as exc:
        s.summarize("t", "c", [])
    assert exc.value.transient is transient
    assert isinstance(exc.value.__cause__, anthropic.APIStatusError)
    assert "claude-haiku-5-5" in str(exc.value) and str(status) in str(exc.value)
    assert API_KEY not in str(exc.value)


def test_connection_error_is_transient():
    def handler(request):
        raise httpx.ConnectError("down", request=request)

    s = make(handler)
    with pytest.raises(SummarizerError) as exc:
        s.summarize("t", "c", [])
    assert exc.value.transient is True
    assert isinstance(exc.value.__cause__, anthropic.APIConnectionError)
    assert API_KEY not in str(exc.value)


def test_other_anthropic_error_not_transient():
    class Boom:
        class messages:
            @staticmethod
            def create(**kw):
                raise anthropic.AnthropicError("weird")

    with pytest.raises(SummarizerError) as exc:
        ClaudeSummarizer(Boom, "m").summarize("t", "c", [])
    assert exc.value.transient is False
    assert isinstance(exc.value.__cause__, anthropic.AnthropicError)


def test_satisfies_protocol():
    assert isinstance(ClaudeSummarizer(object(), "m"), Summarizer)


@pytest.mark.parametrize("env", [{}, {"ANTHROPIC_API_KEY": ""}, {"ANTHROPIC_API_KEY": "  "}])
def test_missing_api_key_is_config_error(env):
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        create_claude_summarizer(Config(), env=env)


def test_create_with_key():
    cfg = Config(model="claude-sonnet-5-5", max_input_chars=123)
    s = create_claude_summarizer(cfg, env={"ANTHROPIC_API_KEY": "k"})
    assert s.model == "claude-sonnet-5-5"
    assert s.max_input_chars == 123
    assert s.client.max_retries == 0
    assert s.client.timeout >= cfg.http_timeout
