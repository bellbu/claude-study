"""순수 목록 로직. 파일 I/O나 출력은 하지 않는다."""

TODO = "todo"
DOING = "doing"
DONE = "done"

_MARKS = {TODO: "[]", DOING: "[=]", DONE: "[O]"}


class TodoNotFound(ValueError):
    pass


class InvalidTransition(ValueError):
    pass


def add(todos: list[dict], title: str) -> list[dict]:
    title = title.strip()
    if not title:
        raise ValueError("제목이 비어 있습니다.")
    next_id = max((t["id"] for t in todos), default=0) + 1
    return [*todos, {"id": next_id, "title": title, "status": TODO}]


def _set_status(todos: list[dict], todo_id: int, new: str, allowed_from: set[str]) -> list[dict]:
    if not any(t["id"] == todo_id for t in todos):
        raise TodoNotFound(f"{todo_id}번 할 일이 없습니다.")
    result = []
    for t in todos:
        if t["id"] == todo_id:
            if t["status"] not in allowed_from:
                raise InvalidTransition(f"{todo_id}번은 '{t['status']}' 상태라 '{new}'로 바꿀 수 없습니다.")
            t = {**t, "status": new}
        result.append(t)
    return result


def start(todos: list[dict], todo_id: int) -> list[dict]:
    return _set_status(todos, todo_id, DOING, {TODO})


def done(todos: list[dict], todo_id: int) -> list[dict]:
    return _set_status(todos, todo_id, DONE, {TODO, DOING})


def format_list(todos: list[dict]) -> list[str]:
    return [f"{_MARKS[t['status']]} {t['id']} {t['title']}" for t in todos]
