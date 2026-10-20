from __future__ import annotations

import pytest

from rss_wiki.config import Config


@pytest.fixture
def config(tmp_path) -> Config:
    return Config(data_dir=tmp_path, anthropic_api_key="test-key")


@pytest.fixture
def conn(tmp_path):
    from rss_wiki.db import connect

    c = connect(tmp_path / "test.db")
    yield c
    c.close()
