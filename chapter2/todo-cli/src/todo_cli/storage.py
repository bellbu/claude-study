import json
from pathlib import Path

DEFAULT_PATH = Path("todos.json")


def load(path: Path = DEFAULT_PATH) -> list[dict]:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save(todos: list[dict], path: Path = DEFAULT_PATH) -> None:
    path.write_text(json.dumps(todos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
