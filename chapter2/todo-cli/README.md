# todo-cli

`todos.json`에 할 일을 저장하는 간단한 CLI입니다.

## 설치

[uv](https://docs.astral.sh/uv/)가 필요합니다.

```
uv sync
```

## 사용법

```
uv run todo add "장보기"    # 할 일 추가
uv run todo list            # 목록 보기
uv run todo start 1         # 1번을 작업 중으로
uv run todo done 1          # 1번을 완료로
```

| 명령 | 설명 |
|---|---|
| `add <제목>` | 할 일을 추가합니다. 번호는 자동으로 매겨집니다. |
| `list` | 전체 목록을 보여줍니다. |
| `start <번호>` | 미완료 항목을 작업 중으로 바꿉니다. |
| `done <번호>` | 미완료 또는 작업 중 항목을 완료로 바꿉니다. |

없는 번호를 주거나 바꿀 수 없는 상태(예: 이미 완료한 항목을 `start`)이면 오류 메시지를 보여주고 종료 코드 1로 끝납니다.

### 목록 표시

| 상태 | 표시 | 색 |
|---|---|---|
| 미완료 | `[]` | 하늘색 |
| 작업 중 | `[=]` | 노란색 |
| 완료 | `[O]` | 초록색 |

```
[] 1 숙제
[=] 2 장보기
[O] 3 청소
```

### 저장 파일

기본적으로 현재 폴더의 `todos.json`에 저장합니다. 다른 파일을 쓰려면 `--file`(`-f`) 옵션을 붙입니다.

```
uv run todo list --file work.json
```

`uv run todo --help`나 `uv run todo <명령> --help`로 도움말을 볼 수 있습니다.

## 개발

```
uv run pytest
```

- `src/todo_cli/todos.py` — 목록 조작 로직 (테스트 대상)
- `src/todo_cli/storage.py` — `todos.json` 읽기/쓰기
- `src/todo_cli/cli.py` — 명령 정의와 출력
