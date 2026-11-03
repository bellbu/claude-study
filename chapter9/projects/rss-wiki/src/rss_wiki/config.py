"""Load rss-wiki.toml and resolve defaults and paths."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(Exception):
    """Invalid configuration (fatal, exit code 2)."""


@dataclass(frozen=True)
class Config:
    model: str = "claude-haiku-5-5"
    min_content_chars: int = 500
    max_input_chars: int = 20000
    http_timeout: int | float = 15
    max_retries: int = 3
    max_failures: int = 5
    summarize_concurrency: int = 4
    data_dir: Path = field(default_factory=Path.cwd)
    db_path: Path = field(default=None)  # type: ignore[assignment]
    wiki_dir: Path = field(default=None)  # type: ignore[assignment]

    def __post_init__(self):
        if self.db_path is None:
            object.__setattr__(self, "db_path", self.data_dir / "data" / "rss-wiki.db")
        if self.wiki_dir is None:
            object.__setattr__(self, "wiki_dir", self.data_dir / "wiki")


_STR_KEYS = ("model",)
_INT_KEYS = ("min_content_chars", "max_input_chars", "max_retries", "max_failures")
_PATH_KEYS = ("data_dir", "db_path", "wiki_dir")


def _is_num(v) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def load_config(path: Path | None, data_dir: Path | None) -> Config:
    raw: dict = {}
    if path is not None and Path(path).is_file():
        try:
            raw = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError, OSError) as e:
            raise ConfigError(f"설정 파일을 읽을 수 없습니다: {path}: {e}") from e

    base = Path(path).resolve().parent if path is not None else Path.cwd()
    values: dict = {}
    for key in _STR_KEYS:
        if key in raw:
            if not isinstance(raw[key], str):
                raise ConfigError(f"{key}는 문자열이어야 합니다")
            values[key] = raw[key]
    for key in _INT_KEYS:
        if key in raw:
            if not isinstance(raw[key], int) or isinstance(raw[key], bool):
                raise ConfigError(f"{key}는 정수여야 합니다")
            values[key] = raw[key]
    if "http_timeout" in raw:
        if not _is_num(raw["http_timeout"]):
            raise ConfigError("http_timeout은 숫자여야 합니다")
        values["http_timeout"] = raw["http_timeout"]
    if "summarize" in raw:
        table = raw["summarize"]
        if not isinstance(table, dict):
            raise ConfigError("summarize는 테이블이어야 합니다")
        if "concurrency" in table:
            c = table["concurrency"]
            if not isinstance(c, int) or isinstance(c, bool) or c < 1:
                raise ConfigError("summarize.concurrency는 1 이상의 정수여야 합니다")
            values["summarize_concurrency"] = c
    for key in _PATH_KEYS:
        if key in raw:
            if not isinstance(raw[key], str):
                raise ConfigError(f"{key}는 문자열 경로여야 합니다")
            p = Path(raw[key])
            values[key] = p if p.is_absolute() else base / p

    if data_dir is not None:
        values["data_dir"] = Path(data_dir)
    return Config(**values)


def default_config_toml() -> str:
    d = Config()
    return (
        "# rss-wiki 설정 (API 키는 환경 변수 ANTHROPIC_API_KEY로만 지정)\n"
        f'model = "{d.model}"\n'
        f"min_content_chars = {d.min_content_chars}\n"
        f"max_input_chars = {d.max_input_chars}\n"
        f"http_timeout = {d.http_timeout}\n"
        f"max_retries = {d.max_retries}\n"
        f"max_failures = {d.max_failures}\n"
        '# data_dir = "."\n'
        '# db_path = "data/rss-wiki.db"\n'
        '# wiki_dir = "wiki"\n'
        "\n[summarize]\n"
        f"concurrency = {d.summarize_concurrency}\n"
    )
