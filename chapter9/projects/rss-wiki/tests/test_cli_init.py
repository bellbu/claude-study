import logging

import pytest

from rss_wiki.cli import main
from rss_wiki.config import default_config_toml


def test_init_creates_everything_and_is_idempotent(tmp_path):
    assert main(["--data-dir", str(tmp_path), "init"]) == 0
    assert (tmp_path / "data" / "rss-wiki.db").is_file()
    assert (tmp_path / "wiki").is_dir()
    toml = tmp_path / "rss-wiki.toml"
    assert toml.read_text(encoding="utf-8") == default_config_toml()
    assert main(["--data-dir", str(tmp_path), "init"]) == 0


def test_init_preserves_existing_config(tmp_path):
    toml = tmp_path / "rss-wiki.toml"
    toml.write_text('model = "custom-model"\n', encoding="utf-8")
    assert main(["--data-dir", str(tmp_path), "init"]) == 0
    assert toml.read_text(encoding="utf-8") == 'model = "custom-model"\n'


def test_init_invalid_config_returns_2(tmp_path, capsys):
    (tmp_path / "rss-wiki.toml").write_text("model = [", encoding="utf-8")
    assert main(["--data-dir", str(tmp_path), "init"]) == 2
    assert "rss-wiki.toml" in capsys.readouterr().err


def test_init_unopenable_db_returns_2_with_path(tmp_path, capsys):
    (tmp_path / "data" / "rss-wiki.db").mkdir(parents=True)
    assert main(["--data-dir", str(tmp_path), "init"]) == 2
    assert "rss-wiki.db" in capsys.readouterr().err


def test_explicit_config_path(tmp_path):
    cfg = tmp_path / "custom.toml"
    assert main(["--data-dir", str(tmp_path), "--config", str(cfg), "init"]) == 0
    assert cfg.is_file()


def test_help_exits_zero(capsys):
    assert main(["--help"]) == 0
    assert "init" in capsys.readouterr().out


def test_init_creates_five_tables(tmp_path):
    import sqlite3

    assert main(["--data-dir", str(tmp_path), "init"]) == 0
    conn = sqlite3.connect(tmp_path / "data" / "rss-wiki.db")
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert {"feeds", "articles", "summaries", "tags", "article_tags"} <= names


def test_default_logs_info_to_stderr_only(tmp_path, capsys):
    assert main(["--data-dir", str(tmp_path), "init"]) == 0
    out = capsys.readouterr()
    assert "초기화 완료" in out.err
    assert out.out == ""


def test_quiet_hides_info(tmp_path, capsys):
    assert main(["--quiet", "--data-dir", str(tmp_path), "init"]) == 0
    err = capsys.readouterr().err
    assert "초기화 완료" not in err
    logging.getLogger("rss_wiki").warning("경고-확인")
    assert "경고-확인" in capsys.readouterr().err


def test_verbose_keeps_info_and_quiets_httpx(tmp_path, capsys):
    assert main(["--verbose", "--data-dir", str(tmp_path), "init"]) == 0
    assert "초기화 완료" in capsys.readouterr().err
    assert logging.getLogger().level == logging.DEBUG
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


def test_verbose_and_quiet_conflict_returns_2(tmp_path, capsys):
    assert main(["--verbose", "--quiet", "--data-dir", str(tmp_path), "init"]) == 2
    assert "usage:" in capsys.readouterr().err


def test_invalid_config_type_returns_2(tmp_path, capsys):
    (tmp_path / "rss-wiki.toml").write_text('http_timeout = "x"\n', encoding="utf-8")
    assert main(["--data-dir", str(tmp_path), "init"]) == 2
    assert "http_timeout" in capsys.readouterr().err


def test_data_dir_is_a_file_returns_2(tmp_path, capsys):
    f = tmp_path / "afile"
    f.write_text("x", encoding="utf-8")
    assert main(["--data-dir", str(f), "init"]) == 2
    assert capsys.readouterr().err.startswith("오류:")


def test_missing_command_prints_usage(capsys):
    assert main([]) == 2
    assert "usage:" in capsys.readouterr().err
