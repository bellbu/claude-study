from pathlib import Path
from typing import Annotated

import typer

from todo_cli import storage, todos

app = typer.Typer(help="todos.json에 저장하는 todo CLI")

STATUS_COLORS = {
    todos.TODO: typer.colors.CYAN,
    todos.DOING: typer.colors.YELLOW,
    todos.DONE: typer.colors.GREEN,
}

FileOption = Annotated[Path, typer.Option("--file", "-f", help="저장 파일 경로")]


def _update(path: Path, change, message: str) -> None:
    try:
        updated = change(storage.load(path))
    except ValueError as e:
        typer.echo(f"오류: {e}", err=True)
        raise typer.Exit(1)
    storage.save(updated, path)
    typer.echo(message)


@app.command()
def add(title: str, file: FileOption = storage.DEFAULT_PATH) -> None:
    """할 일을 추가한다."""
    _update(file, lambda ts: todos.add(ts, title), f"추가: {title}")


@app.command("list")
def list_(file: FileOption = storage.DEFAULT_PATH) -> None:
    """할 일 목록을 보여준다."""
    items = storage.load(file)
    if not items:
        typer.echo("할 일이 없습니다.")
        return
    for item, line in zip(items, todos.format_list(items)):
        typer.secho(line, fg=STATUS_COLORS[item["status"]])


@app.command()
def start(todo_id: int, file: FileOption = storage.DEFAULT_PATH) -> None:
    """할 일을 진행 중으로 바꾼다."""
    _update(file, lambda ts: todos.start(ts, todo_id), f"시작: {todo_id}")


@app.command()
def done(todo_id: int, file: FileOption = storage.DEFAULT_PATH) -> None:
    """할 일을 완료로 바꾼다."""
    _update(file, lambda ts: todos.done(ts, todo_id), f"완료: {todo_id}")
