import pytest

from rss_wiki.summarize import (
    SUMMARY_SCHEMA,
    Summarizer,
    SummarizerError,
    SummaryResult,
    SummaryValidationError,
    build_prompt,
    truncate_input,
    validate_summary,
)


def good(**over):
    data = {"tldr": " 요약입니다. ", "key_points": ["a", "b", "c"], "tags": ["python"]}
    data.update(over)
    return data


def test_valid_dict_becomes_result():
    r = validate_summary(good(extra="무시"))
    assert r == SummaryResult(tldr="요약입니다.", key_points=["a", "b", "c"], tags=["python"])


def test_tags_normalized():
    assert validate_summary(good(tags=[" Python", "python", "AI "])).tags == ["python", "ai"]


@pytest.mark.parametrize(
    "data, field",
    [
        (good(key_points=["a", "b"]), "key_points"),
        (good(key_points=list("abcdef")), "key_points"),
        (good(key_points="abc"), "key_points"),
        (good(key_points=["a", "b", " "]), "key_points"),
        (good(tags=[]), "tags"),
        (good(tags=["a", "b", "c", "d", "e", "f"]), "tags"),
        (good(tags=[" ", ""]), "tags"),
        (good(tags="python"), "tags"),
        (good(tldr="  "), "tldr"),
        (good(tldr=1), "tldr"),
        ({"key_points": ["a", "b", "c"], "tags": ["x"]}, "tldr"),
        ({"tldr": "t", "tags": ["x"]}, "key_points"),
        ({"tldr": "t", "key_points": ["a", "b", "c"]}, "tags"),
    ],
)
def test_invalid_names_field(data, field):
    with pytest.raises(SummaryValidationError, match=field):
        validate_summary(data)


@pytest.mark.parametrize(
    "data, field",
    [
        (good(key_points=[1, 2, 3]), "key_points"),
        (good(tags=[None]), "tags"),
    ],
)
def test_non_string_elements_name_field(data, field):
    with pytest.raises(SummaryValidationError, match=field):
        validate_summary(data)


def test_non_dict_rejected():
    with pytest.raises(SummaryValidationError, match="dict"):
        validate_summary(["tldr"])


def test_build_prompt_normalizes_existing_tags():
    p = build_prompt("t", "x", ["Python", " python", "AI", " "], 10)
    assert "ai, python" in p
    assert "Python" not in p


def test_schema_shape():
    assert SUMMARY_SCHEMA["required"] == ["tldr", "key_points", "tags"]
    assert SUMMARY_SCHEMA["additionalProperties"] is False
    assert SUMMARY_SCHEMA["properties"]["key_points"]["minItems"] == 3
    assert SUMMARY_SCHEMA["properties"]["tags"]["maxItems"] == 5


def test_truncate_input():
    assert len(truncate_input("가" * 25000, 20000)) == 20000
    assert truncate_input("짧음", 20000) == "짧음"
    with pytest.raises(ValueError):
        truncate_input("x", 0)


def test_build_prompt_contents():
    p = build_prompt("제목입니다", "본문" * 100, ["rust", "ai"], 50)
    assert "한국어" in p
    assert "제목입니다" in p
    assert "ai, rust" in p
    assert "소문자" in p
    assert "본문" * 25 in p and "본문" * 26 not in p


def test_build_prompt_deterministic_and_optional_parts():
    a = build_prompt(None, "x", ["b", "a"], 10)
    assert a == build_prompt(None, "x", ["a", "b"], 10)
    assert "제목:" not in a
    assert "없음" in build_prompt("t", "x", [], 10)


def test_summarizer_error_transient_flag():
    assert SummarizerError("x", transient=True).transient is True
    assert SummarizerError("x").transient is False


def test_fake_satisfies_protocol():
    class FakeSummarizer:
        model = "fake"

        def summarize(self, title, content, existing_tags):
            return SummaryResult("t", ["a", "b", "c"], ["x"])

    assert isinstance(FakeSummarizer(), Summarizer)
    assert not isinstance(object(), Summarizer)
