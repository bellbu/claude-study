import argparse
import os
import subprocess
import sys
import tomllib
from pathlib import Path

from rss_wiki.cli import build_parser
from rss_wiki.config import default_config_toml

README = Path(__file__).resolve().parent.parent / "README.md"


def readme_text() -> str:
    return README.read_text(encoding="utf-8")


def test_readme_is_utf8_and_not_empty():
    assert readme_text().strip()


def test_readme_mentions_all_commands_and_options():
    text = readme_text()
    for name in ("init", "feed", "fetch", "summarize", "build", "run", "status", "serve"):
        assert f"rss-wiki {name}" in text, name
    sub = next(a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction))
    assert set(sub.choices) == {"init", "feed", "fetch", "summarize", "build", "run", "status", "serve"}
    for token in ("--retry-failed", "--limit", "--data-dir", "ANTHROPIC_API_KEY",
                  "--verbose", "--quiet", "--config", "--feed", "--name",
                  "feed add", "feed list", "feed remove"):
        assert token in text, token


def _flatten(values: dict, prefix: str = "") -> dict:
    out = {}
    for key, value in values.items():
        if isinstance(value, dict):
            out.update(_flatten(value, f"{prefix}{key}."))
        else:
            out[f"{prefix}{key}"] = value
    return out


def test_readme_config_defaults_match():
    text = readme_text()
    values = _flatten(tomllib.loads(default_config_toml()))
    assert values
    for key, value in values.items():
        shown = f'"{value}"' if isinstance(value, str) else str(value)
        assert f"| `{key}` | `{shown}` |" in text, (key, shown)


def test_readme_schedule_example_uses_project():
    lines = readme_text().splitlines()
    cron = [ln for ln in lines if ln.startswith("0 7 * * *")]
    assert cron
    for ln in cron:
        assert "uv run --project" in ln
        assert "--data-dir" in ln
        assert " run" in ln
    win = [ln for ln in lines if ln.startswith("run --project")]
    assert win
    for ln in win:
        assert "--project" in ln
        assert "--data-dir" in ln


def test_readme_mentions_all_config_keys():
    text = readme_text()
    keys = _flatten(tomllib.loads(default_config_toml()))
    assert keys
    for key in keys:
        assert f"`{key}`" in text, key
    for key in ("data_dir", "db_path", "wiki_dir"):
        assert f"`{key}`" in text, key


def test_stdout_is_utf8_on_cp949_console(tmp_path):
    env = {**os.environ, "PYTHONIOENCODING": "cp949"}
    proc = subprocess.run(
        [sys.executable, "-c", "import sys; from rss_wiki.cli import main; sys.exit(main())",
         "--data-dir", str(tmp_path), "status"],
        capture_output=True, env=env, cwd=tmp_path,
    )
    assert proc.returncode == 0, proc.stderr
    assert "피드: 0개" in proc.stdout.decode("utf-8")
