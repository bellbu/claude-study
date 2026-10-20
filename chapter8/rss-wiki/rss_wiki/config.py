"""환경 변수 기반 설정. API 키는 .env/환경 변수로만 받는다."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

SUMMARY_MODEL = "claude-haiku-5-5"
WIKI_MODEL = "claude-sonnet-5-5"

# UI에서 바꿀 수 있는 설정의 기본값 (settings 테이블에 없을 때 사용)
DEFAULT_SETTINGS: dict[str, str] = {
    "collect_interval_minutes": "60",
    "wiki_hour": "6",
    "wiki_minute": "0",
    "daily_budget_usd": "1.0",
    "page_max_chars": "4000",
    "archive_after_days": "30",
}


@dataclass(frozen=True)
class Config:
    data_dir: Path
    anthropic_api_key: str | None
    host: str = "127.0.0.1"
    port: int = 8000
    summary_model: str = SUMMARY_MODEL
    wiki_model: str = WIKI_MODEL
    fetch_concurrency: int = 5
    initial_fetch_limit: int = 10
    min_content_chars: int = 200
    max_content_chars: int = 8000
    user_agent: str = "rss-wiki/0.1 (+personal RSS reader)"
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "rss_wiki.db"


def load_config(env_file: str | Path | None = None) -> Config:
    load_dotenv(env_file)
    data_dir = Path(os.environ.get("RSS_WIKI_DATA_DIR", "data"))
    return Config(
        data_dir=data_dir,
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        # 인증이 없는 개인용 도구이므로 host는 127.0.0.1로 고정한다
        port=int(os.environ.get("RSS_WIKI_PORT", "8000")),
    )
