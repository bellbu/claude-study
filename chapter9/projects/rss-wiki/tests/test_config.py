from pathlib import Path

import pytest

from rss_wiki.config import Config, ConfigError, default_config_toml, load_config


def test_defaults_without_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = load_config(None, None)
    assert cfg.model == "claude-haiku-5-5"
    assert cfg.min_content_chars == 500
    assert cfg.max_input_chars == 20000
    assert cfg.http_timeout == 15
    assert cfg.max_retries == 3
    assert cfg.max_failures == 5
    assert cfg.data_dir == Path.cwd()
    assert cfg.db_path == Path.cwd() / "data" / "rss-wiki.db"
    assert cfg.wiki_dir == Path.cwd() / "wiki"


def test_missing_file_gives_defaults(tmp_path):
    cfg = load_config(tmp_path / "nope.toml", tmp_path)
    assert cfg == Config(data_dir=tmp_path)


def test_file_overrides_values(tmp_path):
    f = tmp_path / "rss-wiki.toml"
    f.write_text('model = "claude-x"\nmin_content_chars = 100\nhttp_timeout = 7\n', encoding="utf-8")
    cfg = load_config(f, tmp_path)
    assert cfg.model == "claude-x"
    assert cfg.min_content_chars == 100
    assert cfg.http_timeout == 7
    assert cfg.max_retries == 3


def test_data_dir_arg_beats_file(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text(f'data_dir = "{(tmp_path / "fromfile").as_posix()}"\n', encoding="utf-8")
    assert load_config(f, None).data_dir == tmp_path / "fromfile"
    other = tmp_path / "arg"
    cfg = load_config(f, other)
    assert cfg.data_dir == other
    assert cfg.db_path == other / "data" / "rss-wiki.db"
    assert cfg.wiki_dir == other / "wiki"


def test_explicit_paths_in_file(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text('db_path = "x/y.db"\nwiki_dir = "w"\n', encoding="utf-8")
    cfg = load_config(f, tmp_path)
    assert cfg.db_path == tmp_path / "x" / "y.db"
    assert cfg.wiki_dir == tmp_path / "w"


def test_invalid_toml(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text("model = = broken", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(f, tmp_path)


@pytest.mark.parametrize(
    "text",
    ['model = 5', 'max_retries = "3"', 'min_content_chars = true', 'http_timeout = "x"', 'data_dir = 1'],
)
def test_invalid_type(tmp_path, text):
    f = tmp_path / "c.toml"
    f.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(f, tmp_path)


def test_summarize_concurrency_default(tmp_path):
    assert load_config(None, tmp_path).summarize_concurrency == 4


def test_summarize_concurrency_from_file(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text("[summarize]\nconcurrency = 2\n", encoding="utf-8")
    assert load_config(f, tmp_path).summarize_concurrency == 2


@pytest.mark.parametrize(
    "text",
    ["[summarize]\nconcurrency = 0\n", '[summarize]\nconcurrency = "x"\n',
     "[summarize]\nconcurrency = true\n", "summarize = 3\n", "[summarize]\nconcurrency = -1\n"],
)
def test_invalid_summarize_concurrency(tmp_path, text):
    f = tmp_path / "c.toml"
    f.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="summarize"):
        load_config(f, tmp_path)


def test_summarize_unknown_key_is_ignored(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text("[summarize]\nfoo = 1\n", encoding="utf-8")
    assert load_config(f, tmp_path).summarize_concurrency == 4


def test_default_toml_has_concurrency(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text(default_config_toml(), encoding="utf-8")
    assert load_config(f, tmp_path).summarize_concurrency == 4


def test_default_toml_roundtrip(tmp_path):
    f = tmp_path / "c.toml"
    f.write_text(default_config_toml(), encoding="utf-8")
    assert load_config(f, tmp_path) == load_config(None, tmp_path)
