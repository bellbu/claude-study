# rss-wiki PLAN

- 기준 문서: docs/PRD.md (초안 v2, 2026-11-02: 웹 UI·디자인 품질·요약 병렬 실행 추가)
- 현재 상태(2026-11-03): M1~M6 완료. M7 진행 중: T17 조건부 PASS 11/15(스크린샷만 남음), T18 PASS 12/15, T18a PASS 13/15(전체 282건).
  T17 스크린샷이 Playwright 권한 거부로 BLOCKED 3회째라 docs/HALT를 만들어 사람에게 권한 허용을 요청함. 해제 뒤 다음 작업은 T18b(T18a 메모 2~4)와 T17 스크린샷 재시도.
  남은 PRD v2 간극: 웹 UI의 수집하기(T19)·글 보기(T20), 화면별 스크린샷.
  웹 프레임워크는 A(Flask + Jinja2)로 합의되어 PRD 11장에 반영, M7 대기 해제.
  참고(T12 메모 5): 위키 정렬 키는 `published_at` 문자열 비교라 ISO 8601 UTC 저장(feeds.py)을 전제로 함. 저장 형식을 바꾸면 wiki.py 정렬도 함께 고칠 것.
- 기술 결정: PRD 11장 (argparse, httpx, feedparser, trafilatura, 피드 수집 순차·요약 LLM 호출 병렬, 웹은 Flask + Jinja2)

## 모듈 책임 (초안)

| 모듈 | 책임 |
|---|---|
| `rss_wiki/config.py` | `rss-wiki.toml` 로드(tomllib), 기본값, 경로 해석(`--data-dir`), 설정 오류 → `ConfigError` |
| `rss_wiki/db.py` | SQLite 연결, 스키마 생성(멱등), PRD 5장 테이블(`feeds`, `articles`, `summaries`, `tags`, `article_tags`). 연결은 autocommit(`isolation_level=None`)이므로 여러 문장을 묶을 때 호출 측이 `BEGIN`/`COMMIT`을 직접 실행함(`with conn:`은 트랜잭션을 열지 않음) |
| `rss_wiki/cli.py` | argparse 서브커맨드 파싱, `--verbose`/`--quiet`(상호 배타), 종료 코드(0/1/2) 매핑, UTF-8 콘솔 설정. 로그는 stderr, 서드파티 로거(`httpx`, `httpcore`)는 WARNING, `trafilatura`는 CRITICAL로 낮춤 (자체 결정) |
| `rss_wiki/http.py` | httpx 기반 HTTP GET 래퍼(타임아웃, User-Agent, 조건부 요청, 지수 백오프 재시도). transport와 sleep 함수를 주입받아 테스트에서 대체 가능. `get`은 정상 응답 또는 `HttpError`만 내보내며 httpx 예외를 밖으로 새지 않게 함 |
| `rss_wiki/feeds.py` | feedparser로 RSS 2.0·Atom 파싱(`parse_feed(bytes, base_url)`, HTTP 비의존), 피드 등록/목록/삭제(`FeedError`). base_url은 항상 등록 URL(`feeds.url`)을 넘겨 guid를 안정화 (자체 결정). bozo 피드에서 feedparser가 만드는 사소한 텍스트 변형(`&` → `&;`)은 보정하지 않음 (자체 결정) |
| `rss_wiki/fetch.py` | 새 글 수집, guid/링크 중복 제거, 고아 글 재연결, 피드별 실패 격리(`error_count`·`last_status` 기록), 조건부 요청 검증자 저장, 글 저장 중 `sqlite3.Error`는 ROLLBACK 후 `DatabaseError`(치명적, 종료 코드 2) (자체 결정), `last_status` 오류 메시지 200자 상한 (자체 결정), 본문 정책(500자 기준 원문 추출 폴백, http(s)가 아닌 url은 추출 생략 (자체 결정)). summaries 행은 만들지 않음 (자체 결정) |
| `rss_wiki/extract.py` | HTTP·DB 비의존. `html_to_text(html) -> str`(RSS 본문 길이 판정용, 표준 라이브러리 HTMLParser, 자체 결정), `extract_article(html, url=None) -> str | None`(trafilatura, 실패·예외 시 None). `html_to_text`는 길이 판정 전용이며 저장·요약 입력에는 쓰지 않음 (자체 결정) |
| `rss_wiki/fetch.py` (보충) | `_resolve_bodies`의 DB 조회 실패도 `DatabaseError`(종료 코드 2)로 감쌈 (T7b) |
| `rss_wiki/summarize.py` | `Summarizer` 프로토콜(`runtime_checkable`), `SummaryResult`, `SUMMARY_SCHEMA`, 직접 구현한 응답 검증(`validate_summary`, jsonschema 미사용, 자체 결정), 태그 소문자·중복 정규화, 입력 절단·프롬프트 생성(T8). 실패/재시도 정책(T10) |
| `rss_wiki/claude.py` | `ClaudeSummarizer`(Anthropic SDK). 구조화 출력은 `record_summary` 강제 도구 호출, `input_schema=SUMMARY_SCHEMA`(strict 미사용, 개수 검증은 `validate_summary`, 자체 결정). SDK 재시도 끔(`max_retries=0`, 재시도는 T10, 자체 결정). anthropic 예외를 `SummarizerError(transient)`로 감쌈. `create_claude_summarizer(config, env)`는 `ANTHROPIC_API_KEY` 없으면 `ConfigError` (T9) |
| `rss_wiki/summarize_run.py` | DB 의존 요약 실행(T10). 대상 선정(summaries 없음·pending, `--retry-failed`면 failed 포함), `SummarizerError(transient)`만 실행 내 지수 백오프 재시도, 실패 시 `attempts`(누적 실패 횟수, 자체 결정) 증가·`max_failures` 도달 시 `failed` 고정, 성공 시 summaries·tags·article_tags를 한 트랜잭션으로 기록, `sqlite3.Error` → `DatabaseError`. LLM은 `Summarizer` 프로토콜로만 접근. 입력 행의 최소 필드는 `id`·`title`·`content`(url은 선택, T10b). `summarize_pending`의 `on_outcome` 콜백으로 글별 결과를 즉시 전달(T10c) |
| `rss_wiki/cli.py` (보충) | `summarize` 결과 줄은 글마다 즉시 출력, DatabaseError 시 처리한 줄은 남기고 합계 없이 2. 공급자 모듈(anthropic)은 `make_summarizer` 안에서 지연 import (T10c) |
| `rss_wiki/wiki.py` | 글별 Markdown(T11: `slugify`·`article_relpath`·`render_article`·`write_articles`, UTF-8·LF 고정). 본문 텍스트는 `one_line`으로 한 줄화하고 front matter는 원문 보존(T11a). 주제 페이지(`topic_filenames`·`render_topic`)·인덱스(`render_index`)·`build_wiki`(쓰기 후 `articles/`·`topics/`의 오래된 `.md` 정리)의 결정적 재생성(T12). DB는 조회만 |
| `rss_wiki/cli.py` (보충) | `build`: `build_wiki` 결과 한 줄 출력, 파일 쓰기 `OSError` → 2 (T12, 자체 결정) |
| `rss_wiki/cli.py` (보충) | `run`: API 키 확인 → fetch → summarize → build, 공유 헬퍼 `_do_fetch`·`_do_summarize`, 단계 중 `DatabaseError`/`OSError` → 2로 중단, 일부 실패 → 1. `main`은 `BrokenPipeError` → 1 (T13, 자체 결정). `status`: `collect_status` 결과를 텍스트로 출력, 항상 0(DB 오류만 2) (T13b, 자체 결정) |
| `rss_wiki/status.py` | DB 조회만으로 피드·글·요약 상태 건수 집계(`StatusCounts`, `collect_status`). 요약 대기 조건은 `summarize_run.select_targets` 기본 조건과 일치. `sqlite3.Error` → `DatabaseError` (T13b) |
| `rss_wiki/config.py` (보충) | `[summarize] concurrency`(기본 4, 1 이상 정수) → `Config.summarize_concurrency` (T15) |
| `rss_wiki/summarize_run.py` (보충) | `summarize_pending(concurrency=N)`: LLM 호출은 스레드풀, 기록·`on_outcome`은 메인 스레드 id 순(T16). 오류 시 미시작 작업 취소, `KeyboardInterrupt`는 실행 중 호출을 기다리지 않고 종료(T16a, 자체 결정) |
| `rss_wiki/web/` (M7) | Flask 앱 팩토리 `create_app(config, *, http_client_factory=None)`, 패키지 내 `templates/`(Jinja2)·`static/`(디자인 토큰 CSS). 라우트는 기존 기능 함수(feeds·fetch·summarize_run·wiki·status)만 호출하고 SQL·비즈니스 로직을 새로 두지 않음. 요청마다 `connect`+`init_schema` 후 닫음 (자체 결정: sqlite 연결 스레드 공유 회피). web은 cli를 import하지 않음(HTTP 클라이언트는 팩토리 주입). 폼 처리는 PRG(303)+flash, 외부 `Origin`의 POST는 403 (T18, 자체 결정). `run_server`로 실행 분리, `DatabaseError`·raw `sqlite3.Error` → 500 오류 화면+ERROR 로그 (T17, T18a 자체 결정). 삭제는 JS `confirm` 확인 (T18a, 자체 결정) |
| `tests/` | pytest. 네트워크/LLM 없이 실행 (HTTP·LLM 계층 대체). `conftest.py`가 전역 로거 상태를 테스트마다 복원 |

## 마일스톤

### M1. 기반: 설정·DB·CLI 골격
- 설정 로드와 기본값, SQLite 스키마 생성, 테스트 환경(pytest)
- CLI 골격과 `init`, 공통 옵션, 종료 코드 규칙
- 완료 기준: `rss-wiki init`이 `data/rss-wiki.db`와 `rss-wiki.toml`을 만들고 재실행해도 안전

### M2. 피드 관리와 수집
- `feed add/list/remove`, RSS 2.0·Atom 파싱, URL 중복 금지
- `fetch`: guid 중복 제거, 조건부 요청, 타임아웃, 본문 정책과 원문 추출 폴백
- 고아 글(feed 삭제로 `feed_id`가 NULL) 정책: 수집 시 같은 guid의 고아 글이 있으면 새로 넣지 않고 현재 feed로 재연결함. 스키마는 바꾸지 않음 (자체 결정)
- 완료 기준: 고정 XML/HTML 픽스처로 수집·본문 정책 테스트 통과

### M3. 요약
- `Summarizer` 프로토콜, Claude 구현(Anthropic SDK, 구조화 출력), 한국어 요약
- 스키마 검증, 입력 길이 절단, 기존 태그 힌트, 재시도/실패 고정/`--retry-failed`
- 완료 기준: 가짜 Summarizer로 실패 정책 테스트 통과

### M4. 위키 빌드
- `wiki/articles/YYYY/MM/<slug>.md`, `wiki/topics/<tag>.md`, `wiki/index.md`
- 완료 기준: 같은 DB로 두 번 build 시 결과 바이트 동일(멱등)

### M5. 통합과 마감
- `run`(fetch→summarize→build), `status`, 일부 실패 시 종료 코드 1, 치명적 오류 2
- 로깅 수준, UTF-8(Windows 콘솔), README 사용법
- 완료 기준: 가짜 HTTP·LLM으로 `run` 종단 테스트 통과, README에 모든 서브커맨드·설정 키가 등장(test_readme), cp949 콘솔에서도 UTF-8 출력,
  README 주기 실행 예가 프로젝트 밖 cwd에서 동작(`uv run --project`)하고 cron 줄 단위로 테스트됨(T14c)

### M6. 요약 병렬 실행 (PRD 4.3, v2)
- 설정 `[summarize] concurrency`(기본 4, 1 이상 정수) 로드
- `summarize_pending`: LLM 호출(재시도 포함)은 스레드풀에서 병렬, DB 기록·`on_outcome`은 메인 스레드에서 대상 id 순으로 하나씩 (자체 결정: 결정적 출력·sqlite 연결 단일 스레드 사용)
- 완료 기준: 가짜 Summarizer로 동시 실행 수 상한·실패 격리·id 순 기록 테스트 통과, `concurrency=1`이면 기존 동작과 동일

### M7. 웹 UI (PRD 5장, v2) — Flask + Jinja2 (합의 A)
- `rss-wiki serve [--port 8000]`, 127.0.0.1 전용, CLI와 같은 기능 함수 호출
- 스크린샷은 `docs/screens/<화면>-{light,dark}.png`로 남김 (자체 결정)
- 피드 관리(목록·등록·삭제), 수집하기(`run` 실행·진행 표시), 글 보기(목록·상세·태그별)
- 디자인 토큰(CSS 변수)·한국어 타이포그래피·반응형·다크 모드·빈/로딩/오류 화면, 화면 변경마다 스크린샷 확인
- 완료 기준: 테스트 클라이언트로 라우트 테스트 통과, 화면별 스크린샷(라이트/다크) 확인

## 미해결 의사결정

(없음. 웹 프레임워크는 합의 A로 PRD 11장에 반영, 2026-11-02)
