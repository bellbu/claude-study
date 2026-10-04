import pytest

from todo_cli import todos
from todo_cli.todos import InvalidTransition, TodoNotFound


def test_add_assigns_incrementing_ids_and_todo_status():
    ts = todos.add([], "장보기")
    ts = todos.add(ts, "숙제")
    assert ts == [
        {"id": 1, "title": "장보기", "status": "todo"},
        {"id": 2, "title": "숙제", "status": "todo"},
    ]


def test_add_uses_max_id_plus_one():
    ts = [{"id": 5, "title": "a", "status": "done"}]
    assert todos.add(ts, "b")[-1]["id"] == 6


def test_add_rejects_blank_title():
    with pytest.raises(ValueError):
        todos.add([], "   ")


def test_add_does_not_mutate_input():
    original = []
    todos.add(original, "a")
    assert original == []


def test_start_moves_todo_to_doing():
    ts = todos.start(todos.add([], "a"), 1)
    assert ts[0]["status"] == "doing"


def test_start_rejects_doing_and_done():
    doing = todos.start(todos.add([], "a"), 1)
    with pytest.raises(InvalidTransition):
        todos.start(doing, 1)
    with pytest.raises(InvalidTransition):
        todos.start(todos.done(doing, 1), 1)


@pytest.mark.parametrize("prepare", [lambda ts: ts, lambda ts: todos.start(ts, 1)])
def test_done_from_todo_or_doing(prepare):
    ts = todos.done(prepare(todos.add([], "a")), 1)
    assert ts[0]["status"] == "done"


def test_done_rejects_already_done():
    ts = todos.done(todos.add([], "a"), 1)
    with pytest.raises(InvalidTransition):
        todos.done(ts, 1)


def test_status_change_does_not_mutate_input():
    ts = todos.add([], "a")
    todos.start(ts, 1)
    assert ts[0]["status"] == "todo"


@pytest.mark.parametrize("fn", [todos.start, todos.done])
def test_unknown_id_raises(fn):
    with pytest.raises(TodoNotFound):
        fn(todos.add([], "a"), 99)


def test_format_list():
    ts = todos.add(todos.add(todos.add([], "a"), "b"), "c")
    ts = todos.done(todos.start(ts, 2), 3)
    assert todos.format_list(ts) == ["[] 1 a", "[=] 2 b", "[O] 3 c"]


def test_format_list_empty():
    assert todos.format_list([]) == []
