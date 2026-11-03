# rss-wiki

RSS/Atom 피드에서 글을 수집하고, Claude로 글마다 한국어 요약을 만든 뒤, 요약을 주제(태그)별 Markdown 위키로 정리하는 개인용 로컬 CLI 도구입니다.

## 요구 사항

- Python 3.14 이상, [uv](https://docs.astral.sh/uv/)
- 환경 변수 `ANTHROPIC_API_KEY` (요약 단계에 필요). 설정 파일이나 DB에는 저장하지 않습니다.

## 설치와 시작

```
uv sync
uv run rss-wiki init
```

`init`은 데이터 디렉터리(`data/`, `wiki/`), SQLite DB(`data/rss-wiki.db`), 기본 설정 파일 `rss-wiki.toml`을 만듭니다. 다시 실행해도 안전하며 기존 설정 파일은 보존됩니다.

## 명령

`rss-wiki`는 프로젝트 가상환경(`.venv`) 안에만 설치되므로 PATH에 없습니다. 아래 명령은 모두 앞에 `uv run`을 붙여 실행하세요.

```
uv run rss-wiki feed add https://news.hada.io/rss/news --name "개발 뉴스"
```

가상환경을 활성화하면(`.venv\Scripts\activate`, macOS/Linux는 `source .venv/bin/activate`) `uv run` 없이 `rss-wiki ...`로 실행할 수 있습니다.

| 명령 | 설명 |
|---|---|
| `rss-wiki init` | 데이터 디렉터리, DB, 기본 설정 파일 생성 |
| `rss-wiki feed add <url> [--name NAME]` | 피드 등록 (URL 유효성 확인, 중복 등록 불가) |
| `rss-wiki feed list` | 등록된 피드와 마지막 수집 시각·상태 |
| `rss-wiki feed remove <id\|url>` | 피드 삭제 (기존 글과 요약은 유지) |
| `rss-wiki fetch [--feed ID]` | 새 글 수집 |
| `rss-wiki summarize [--limit N] [--retry-failed]` | 요약되지 않은 글을 요약 |
| `rss-wiki build` | 주제별 위키 페이지와 인덱스 재생성 (멱등) |
| `rss-wiki run` | `fetch` → `summarize` → `build`를 차례로 실행 (스케줄러용) |
| `rss-wiki status` | 수집/요약 대기·실패 건수 |
| `rss-wiki serve [--port 8000]` | 로컬 웹 UI 실행 (`127.0.0.1` 전용, 기본 http://127.0.0.1:8000) |

### 공통 옵션

- `--verbose` / `--quiet`: 로그 수준. 함께 쓸 수 없습니다.
- `--data-dir DIR`: 데이터 디렉터리 (기본: 현재 디렉터리). 설정 파일 값보다 우선합니다.
- `--config FILE`: 설정 파일 경로 (기본: `<data-dir>/rss-wiki.toml`).

로그는 stderr로, 명령 결과는 stdout으로 출력합니다. 출력은 항상 UTF-8입니다.

### 종료 코드

| 코드 | 의미 |
|---|---|
| 0 | 모두 성공 |
| 1 | 일부 항목만 실패 (피드·글 단위 실패, 잘못된 피드 지정 등), 출력 파이프가 끊긴 경우 |
| 2 | 설정 오류, DB를 열 수 없음, API 키 없음 등 치명적 오류 |

`status`는 조회에 성공하면 피드나 요약 상태와 무관하게 0을 반환합니다. DB 오류만 2입니다.

### status 출력 예시

```
피드: 3개 (오류 1, 미수집 1)
글: 6건
요약: 완료 2, 대기 3 (재시도 대기 1), 실패 1
실패 글은 summarize --retry-failed로 다시 시도할 수 있습니다
```

마지막 줄은 실패한 글이 있을 때만 나옵니다.

## 설정 파일 `rss-wiki.toml`

| 키 | 기본값 | 설명 |
|---|---|---|
| `model` | `"claude-haiku-5-5"` | 요약에 쓰는 Claude 모델 |
| `min_content_chars` | `500` | RSS 본문(텍스트 변환 후)이 이보다 짧으면 원문 페이지에서 본문 추출 |
| `max_input_chars` | `20000` | 요약 입력 본문 최대 길이 (초과 시 절단) |
| `http_timeout` | `15` | HTTP 타임아웃(초) |
| `max_retries` | `3` | 일시적 오류(네트워크, 5xx, 429) 재시도 횟수 |
| `max_failures` | `5` | 누적 실패가 이 횟수에 도달하면 요약을 `failed`로 고정 |
| `summarize.concurrency` | `4` | 요약 LLM 호출 동시 실행 수 (`[summarize]` 테이블의 `concurrency`, 1 이상, 너무 크면 API 속도 제한(429)에 걸릴 수 있음) |
| `data_dir` | 현재 디렉터리 | 데이터 디렉터리 |
| `db_path` | `<data_dir>/data/rss-wiki.db` | SQLite DB 경로 |
| `wiki_dir` | `<data_dir>/wiki` | 위키 출력 디렉터리 |

- 설정 파일 안의 상대 경로(`data_dir`·`db_path`·`wiki_dir`)는 **설정 파일이 있는 디렉터리 기준**으로 풀립니다.
- `--data-dir`을 주면 `data_dir`을 덮어쓰고, 설정 파일에 `db_path`·`wiki_dir`을 따로 적지 않았다면 그 아래(`data/rss-wiki.db`, `wiki`)로 따라갑니다. 따로 적었다면 그 값이 그대로 쓰입니다.

## 결과물

```
wiki/
  index.md                      태그 목록(글 수)과 최근 요약 글
  articles/YYYY/MM/<slug>.md    글별 요약 (front matter + TL;DR + 핵심 포인트 + 원문 링크)
  topics/<tag>.md               태그별 글 목록 (최신순, TL;DR 한 줄)
```

주제 파일명이 겹치면 태그 이름순으로 `-2`, `-3` 접미사가 붙습니다. 그래서 태그가 추가되면 `build`마다 접미사가 바뀔 수 있습니다.

## 실패 정책

- 피드 하나나 글 하나가 실패해도 나머지는 계속 처리합니다 (항목 격리). 원인은 DB와 로그에 남습니다.
- 일시적 오류는 한 번 실행하는 동안 지수 백오프로 최대 3회 재시도합니다. 그래도 실패하면 다음 실행 때 다시 시도합니다.
- 누적 실패가 5회에 도달하면 `failed`로 고정되어 자동 재시도에서 빠집니다. `summarize --retry-failed`로 수동 재시도할 수 있습니다.
- LLM 응답이 스키마에 맞지 않으면 실패 1회로 셉니다.
- 같은 명령을 다시 실행해도 중복 데이터가 생기지 않습니다.

## 주기 실행

도구에 스케줄러는 없습니다. Windows 작업 스케줄러나 cron에서 `rss-wiki run`을 호출하세요.

```
# cron 예: 매일 07:00
0 7 * * * ANTHROPIC_API_KEY=... uv run --project /path/to/rss-wiki rss-wiki --data-dir /path/to/data --quiet run
```

Windows 작업 스케줄러 예: 동작(프로그램)에 `uv`, 인수에 아래를 등록하고 API 키는 사용자 환경 변수로 지정합니다.

```
run --project C:\path\to\rss-wiki rss-wiki --data-dir C:\path\to\data --quiet run
```

`uv run`은 명령을 실행하는 현재 디렉터리(또는 그 상위)에서 프로젝트를 찾습니다. cron·작업 스케줄러는 보통 홈 디렉터리 등 프로젝트 밖에서 실행하므로 `--project`로 프로젝트 경로를 지정하세요.

cron 환경의 `PATH`에는 `uv`가 없을 수 있으니, `uv`를 절대 경로(예: `/home/<user>/.local/bin/uv`, `which uv`로 확인)로 적으세요.

종료 코드 1(일부 실패)이어도 실패한 항목은 다음 실행에서 다시 시도되며, `rss-wiki status`로 확인할 수 있습니다.

## 테스트

```
uv run pytest
```

네트워크와 LLM 없이 실행됩니다.
