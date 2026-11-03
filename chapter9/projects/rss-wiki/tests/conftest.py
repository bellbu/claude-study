import logging

import pytest

_LOGGER_NAMES = ("httpx", "httpcore", "trafilatura")


@pytest.fixture(autouse=True)
def _restore_logging_state():
    root = logging.getLogger()
    root_level = root.level
    root_handlers = list(root.handlers)
    levels = {name: logging.getLogger(name).level for name in _LOGGER_NAMES}
    yield
    root.setLevel(root_level)
    for handler in root.handlers:
        if handler not in root_handlers:
            handler.close()
    root.handlers[:] = root_handlers
    for name, level in levels.items():
        logging.getLogger(name).setLevel(level)
