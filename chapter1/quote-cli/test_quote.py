import json
import subprocess
import sys
from pathlib import Path

import pytest

import quote

SCRIPT = Path(__file__).with_name("quote.py")


def run_cli(*args):
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        encoding="utf-8",
        check=False,
    )


@pytest.fixture
def quotes():
    return quote.load_quotes()


def test_quotes_json_has_valid_entries(quotes):
    assert isinstance(quotes, list)
    assert len(quotes) > 0
    for q in quotes:
        assert isinstance(q["text"], str) and q["text"].strip()
        assert isinstance(q["author"], str) and q["author"].strip()


def test_format_quote():
    assert quote.format_quote({"text": "명언", "author": "누군가"}) == '"명언" - 누군가'


def test_no_args_prints_one_quote(quotes):
    result = run_cli()

    assert result.returncode == 0
    lines = result.stdout.splitlines()
    assert len(lines) == 1
    assert lines[0] in {quote.format_quote(q) for q in quotes}


def test_list_prints_all_quotes(quotes):
    result = run_cli("--list")

    assert result.returncode == 0
    expected = [f"{i}. {quote.format_quote(q)}" for i, q in enumerate(quotes, start=1)]
    assert result.stdout.splitlines() == expected


def test_empty_quotes_file_exits_with_error(tmp_path):
    # quotes.json이 비어 있을 때의 동작을 확인하기 위해 복사본에서 실행
    (tmp_path / "quote.py").write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "quotes.json").write_text(json.dumps([]), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(tmp_path / "quote.py")],
        capture_output=True,
        encoding="utf-8",
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "등록된 명언이 없습니다." in result.stderr
