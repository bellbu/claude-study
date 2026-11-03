# rss-wiki TASKS

표기: `[ ]` 미완료, `[x]` 완료. **다음** 표시가 붙은 항목이 이번 Generator 대상입니다.
테스트는 `uv run pytest`로 실행합니다. pytest는 dev 의존성(`uv add --dev pytest`)으로 추가합니다.

## M1. 기반

- [x] T1. 설정 모듈
  - 내용: `rss_wiki/config.py`에 `Config` 데이터클래스와 `load_config(path: Path | None, data_dir: Path | None) -> Config`.
    기본값: model=`claude-haiku-5-5`, min_content_chars=500, max_input_chars=20000, http_timeout=15,
    max_retries=3, max_failures=5, data_dir=현재 작업 디렉터리, db_path=`{data_dir}/data/rss-wiki.db`, wiki_dir=`{data_dir}/wiki`.
    파일이 없으면 기본값, TOML 문법 오류나 잘못된 타입이면 `ConfigError`. `--data-dir` 인자가 설정 파일 값보다 우선.
    기본 설정 TOML 문자열을 만드는 `default_config_toml() -> str`도 제공(이후 `init`에서 사용). API 키는 다루지 않음.
  - touch: `pyproject.toml`(dev 의존성 pytest), `src/rss_wiki/config.py`, `tests/test_config.py`
  - acceptance:
    - `uv run pytest tests/test_config.py` 통과 (기본값, 파일 값 덮어쓰기, data_dir 우선순위, 잘못된 TOML → ConfigError, 잘못된 타입 → ConfigError, `default_config_toml()` 결과를 다시 로드하면 기본값과 동일)

- [x] T2. DB 스키마 모듈
  - 내용: `rss_wiki/db.py`에 `connect(db_path: Path) -> sqlite3.Connection`(상위 디렉터리 생성, foreign_keys ON, UTF-8)과
    `init_schema(conn)`(CREATE TABLE IF NOT EXISTS, 멱등). PRD 5장 컬럼을 그대로 따름:
    `feeds.url` UNIQUE, `articles` (feed_id, guid) UNIQUE, `summaries.article_id` PK,
    `summaries.status` ∈ {pending, done, failed} CHECK, `tags.name` UNIQUE, `article_tags` (article_id, tag_id) PK.
    DB를 열 수 없으면 `DatabaseError`(치명적 오류용)로 감싸서 던짐. 표준 라이브러리 sqlite3만 사용.
  - touch: `src/rss_wiki/db.py`, `tests/test_db.py`
  - acceptance:
    - `uv run pytest tests/test_db.py` 통과 (tmp_path에 스키마 생성, 두 번 호출해도 오류 없음, 5개 테이블 존재, feeds.url 중복 삽입 시 IntegrityError, 같은 feed의 같은 guid 중복 삽입 시 IntegrityError, 잘못된 status CHECK 위반, 디렉터리 경로를 DB로 열면 DatabaseError)

- [x] T2a. DB 모듈 보완 (T2 REVIEW 메모 2~4)
  - 내용: `connect`에서 연결을 연 뒤 PRAGMA나 조기 SELECT가 실패하면 `conn.close()` 후 `DatabaseError`를 던지도록 수정.
    `connect`/`init_schema`에 docstring 추가. `connect` docstring에 autocommit(`isolation_level=None`) 계약을 명시
    (여러 문장을 묶을 때는 호출 측이 `BEGIN`/`COMMIT` 실행, `with conn:`은 트랜잭션을 열지 않음). 스키마는 변경하지 않음.
  - touch: `src/rss_wiki/db.py`, `tests/test_db.py`
  - acceptance:
    - `uv run pytest tests/test_db.py` 통과, 아래 테스트 추가 포함:
      - SQLite가 아닌 손상 파일(tmp_path에 임의 바이트 기록)을 `connect`하면 `DatabaseError`
      - 닫힌 연결(또는 실패하는 연결)로 `init_schema`를 호출하면 `DatabaseError`
      - `content_source='bogus'` 삽입 시 `IntegrityError`
      - article 삭제 시 해당 summaries·article_tags 행이 CASCADE 삭제됨
    - `uv run pytest` 전체 통과 (기존 22건 회귀 없음)

- [x] T3. CLI 골격과 `init`
  - 내용: argparse(PRD 10장)로 서브커맨드 파서 구성. `main(argv: list[str] | None = None) -> int`가 종료 코드를 반환하고
    엔트리포인트는 `sys.exit(main())`. 공통 옵션 `--verbose`/`--quiet`/`--data-dir`/`--config`, 종료 코드 0/1/2,
    UTF-8 stdout(`sys.stdout.reconfigure(encoding="utf-8")`). `ConfigError`/`DatabaseError`는 종료 코드 2로 매핑하고,
    예외 메시지(db.py의 경로·원인 포함)를 그대로 stderr에 출력.
    `init`은 data/, wiki/, DB 스키마(T2 `init_schema`), `rss-wiki.toml`(없을 때만, T1 `default_config_toml()`) 생성.
    아직 구현되지 않은 서브커맨드는 이번 항목에서 등록하지 않음.
    엔트리포인트는 pyproject의 `rss_wiki:main`을 유지하고, `__init__.main()`이 `cli.main()`의 반환값으로 `sys.exit`하도록 바꿈 (자체 결정).
    부수 작업(T2a REVIEW 메모 1): `connect` 실패 시 연결이 닫히는지 고정하는 회귀 테스트를 `tests/test_db.py`에 1건 추가.
    방법은 `monkeypatch`로 `sqlite3.connect`를 감싸 반환 연결의 `close` 호출 여부를 확인(플랫폼 무관). `db.py`는 수정하지 않음.
  - touch: `src/rss_wiki/__init__.py`, `src/rss_wiki/cli.py`, `tests/test_cli_init.py`, `tests/test_db.py`(테스트 1건 추가만)
  - acceptance:
    - `uv run rss-wiki --help` 종료 코드 0
    - `uv run pytest tests/test_cli_init.py` 통과 (tmp 디렉터리에서 `main(["--data-dir", tmp, "init"])` 두 번 실행 시 모두 0, DB·wiki/·설정 파일 생성, 기존 설정 파일 내용 보존, 잘못된 설정 파일이면 2, DB 경로가 디렉터리 등으로 열 수 없으면 2이고 stderr에 경로 포함)
    - `uv run pytest tests/test_db.py` 통과 (close 회귀 테스트 포함 15건)
    - `uv run pytest` 전체 통과 (기존 26건 회귀 없음)

- [x] T3a. CLI 로그 옵션 정리와 `init` 테스트 보강 (T3 REVIEW 메모 1~3)
  - 내용: `--verbose`/`--quiet`를 `add_mutually_exclusive_group()`으로 묶음(함께 주면 argparse usage 오류 → 종료 코드 2).
    로그는 stderr로 출력(현 `basicConfig` 기본 동작 유지)하고, `_setup_logging`에서 `logging.getLogger("httpx")`·`logging.getLogger("httpcore")`를
    WARNING으로 낮춤(`--verbose`일 때도 WARNING 유지, 자체 결정). `cmd_init`/`main`에 docstring 추가.
    테스트 보강: `init` 후 `sqlite_master`에서 5개 테이블 확인, 기본/`--quiet`/`--verbose`별 출력(기본은 INFO가 stderr에 보이고 stdout에는 없음, `--quiet`는 INFO 숨김),
    `--verbose --quiet` → 2, 잘못된 타입 설정(`http_timeout = "x"`) → 2, `--data-dir`가 일반 파일 → 2(OSError 경로), 명령 누락 시 stderr에 usage 출력.
    `config.py`·`db.py`는 수정하지 않음.
  - touch: `src/rss_wiki/cli.py`, `tests/test_cli_init.py`
  - acceptance:
    - `uv run pytest tests/test_cli_init.py` 통과 (위 신규 테스트 포함)
    - `uv run rss-wiki --verbose --quiet init` 종료 코드 2
    - `uv run pytest` 전체 통과 (기존 34건 회귀 없음)

- [x] T3b. 로그 수준 테스트 강화와 로거 상태 격리 (T3a REVIEW 메모 1·2, tests만 수정)
  - 내용: `tests/conftest.py`를 새로 만들고 autouse fixture로 각 테스트 전후에 루트·`httpx`·`httpcore` 로거의 `level`과
    루트 로거의 `handlers` 목록을 저장·복원함. `tests/test_cli_init.py` 수정:
    - `--verbose` 테스트에 `logging.getLogger().level == logging.DEBUG` 단언 추가.
    - `--quiet` 테스트에 `main(...)` 후 `logging.getLogger("rss_wiki").warning("경고-확인")`을 호출하고 그 문자열이 stderr에 보이는지 단언 추가.
    - `test_verbose_and_quiet_conflict_returns_2`의 `"not allowed with"` 단언을 `"usage:"` 확인으로 교체.
    - 중복 테스트 `test_missing_command_returns_2`(46-47행)를 삭제하고 `test_missing_command_prints_usage`로 일원화.
    `src/` 아래는 수정하지 않음. 테스트가 `src/` 수정 없이 통과하지 않으면 BLOCKED로 기록하고 원인을 IMPL.md에 남김.
  - touch: `tests/conftest.py`(신규), `tests/test_cli_init.py`
  - acceptance:
    - `uv run pytest tests/test_cli_init.py` 통과 (14건: 기존 15건 − 중복 1건)
    - `uv run pytest tests/test_cli_init.py tests/test_db.py` 와 `uv run pytest tests/test_db.py tests/test_cli_init.py`가 모두 통과 (순서 무관)
    - `uv run pytest` 전체 통과 (41건, 회귀 없음)

## M2. 피드 관리와 수집
- [x] T4. HTTP 계층 (httpx, MockTransport로 테스트)
  - 내용: `uv add httpx`. `rss_wiki/http.py`에 다음을 제공.
    - `HttpResponse` 데이터클래스: `status: int`, `content: bytes`, `url: str`(최종 URL), `etag: str | None`, `last_modified: str | None`, `not_modified: bool`(304일 때 True).
    - `HttpError(Exception)`: 최종 실패. 메시지에 URL과 원인(상태 코드 또는 예외) 포함, `status: int | None`, `transient: bool` 속성.
    - `HttpClient(timeout: float = 15, max_retries: int = 3, transport: httpx.BaseTransport | None = None, sleep: Callable[[float], None] = time.sleep, backoff_base: float = 1.0)`.
      내부 `httpx.Client`는 `follow_redirects=True`, `User-Agent: rss-wiki/<버전>`. 컨텍스트 매니저(`with HttpClient(...) as c:`)와 `close()` 지원.
    - `get(url, *, etag=None, last_modified=None) -> HttpResponse`: 값이 있으면 `If-None-Match`/`If-Modified-Since` 헤더 전송.
      2xx·304는 정상 반환. 일시적 오류(`httpx.TransportError`(타임아웃 포함), 5xx, 429)는 `sleep(backoff_base * 2**i)`로 지수 백오프하며 최대 `max_retries`회 재시도(총 시도 `1 + max_retries`),
      그래도 실패하면 `HttpError(transient=True)`. 그 외 4xx는 재시도 없이 즉시 `HttpError(transient=False)`.
    - 이 모듈은 DB·CLI를 모르며, `Config`에서 값을 꺼내 생성하는 것은 호출 측(T5/T6) 몫.
    - 부수 작업(T3b REVIEW 메모 2): `tests/conftest.py`의 fixture 정리 단계에서, 테스트 중 루트 로거에 새로 추가된 handler
      (저장해 둔 목록에 없는 것)를 `close()`한 뒤 원래 목록을 복원함. 저장·복원 대상 로거는 그대로 둠.
  - touch: `pyproject.toml`, `uv.lock`, `src/rss_wiki/http.py`, `tests/test_http.py`, `tests/conftest.py`(handler close만)
  - acceptance:
    - `uv run pytest tests/test_http.py` 통과 (모두 `httpx.MockTransport`와 기록용 sleep 스텁 사용, 실제 네트워크·대기 없음):
      200 응답의 content/etag/last_modified 반환, User-Agent 헤더 전송, etag·last_modified 전달 시 조건부 헤더 전송, 304 → `not_modified=True`,
      503 두 번 후 200 → 성공이고 sleep 인자 `[1.0, 2.0]`, 429 계속 → 총 4회 시도 후 `HttpError(transient=True)`, `httpx.ConnectError` 계속 → `HttpError(transient=True)`,
      404 → 1회 시도 후 `HttpError(transient=False, status=404)`, 리다이렉트 후 최종 URL 반환, 오류 메시지에 URL 포함
    - `uv run pytest tests/test_cli_init.py tests/test_db.py`와 역순 실행이 모두 통과 (conftest 변경 후 순서 독립성 유지)
    - `uv run pytest` 전체 통과 (기존 41건 회귀 없음)
- [x] T4a. HTTP 예외 감싸기·입력 검증·테스트 보강 (T4 REVIEW 메모 1~4)
  - 내용: `rss_wiki/http.py`의 `get` 수정.
    - `httpx.UnsupportedProtocol`(잘못된 스킴)은 재시도 없이 즉시 `HttpError(transient=False)` (자체 결정: 재시도해도 결과가 바뀌지 않음).
      나머지 `httpx.TransportError`는 기존대로 일시적 오류로 재시도.
    - 그 외 `httpx.RequestError`(`TooManyRedirects`, `DecodingError` 등)는 재시도 없이 `HttpError(transient=False)`로 감쌈. 메시지에 URL과 예외 타입명 포함, `from exc` 연결.
    - 생성자에서 `max_retries < 0`이면 `ValueError`. 루프 끝의 `assert`는 제거하고 `last_error`가 반드시 설정되는 구조로 둠.
    - 이 결과 `get`은 2xx·304 반환 또는 `HttpError`만 던짐(호출 측이 httpx 예외를 몰라도 됨). docstring에 이 계약을 적음.
  - touch: `src/rss_wiki/http.py`, `tests/test_http.py`
  - acceptance:
    - `uv run pytest tests/test_http.py` 통과, 아래 테스트 추가 포함 (MockTransport·sleep 스텁, 실제 네트워크·대기 없음):
      - 302 자기 자신 리다이렉트 → `HttpError(transient=False)`, 메시지에 URL 포함, sleep 호출 없음
      - `ftp://` URL → `HttpError(transient=False)`, sleep 호출 없음
      - `HttpClient(max_retries=-1)` → `ValueError`
      - 503 → 200 재시도 시 `caplog`(logger `rss_wiki.http`, DEBUG)에 URL 포함 로그 기록
      - 검증자 헤더 없는 304 → `etag is None` 그리고 `last_modified is None`
      - ConnectError 계속 테스트에 총 시도 횟수 4회 단언 추가
    - `uv run pytest` 전체 통과 (기존 52건 회귀 없음)

- [x] T5. 피드 파싱 모듈 (feedparser)
  - 내용: `uv add feedparser`. `rss_wiki/feeds.py`에 파싱만 구현(DB·CLI 연동은 T5a).
    - `ParsedEntry` 데이터클래스: `guid: str`, `url: str`, `title: str | None`, `published_at: str | None`(ISO8601 UTC, 없으면 None), `content: str`(HTML 원문 그대로; 텍스트 변환은 T7 몫).
    - `ParsedFeed` 데이터클래스: `title: str | None`, `entries: list[ParsedEntry]`.
    - `FeedParseError(Exception)`: 피드가 아닌 문서(HTML 페이지 등, feedparser `version`이 빈 문자열)일 때.
    - `parse_feed(content: bytes, base_url: str) -> ParsedFeed`: RSS 2.0·Atom 지원. guid는 `id`(Atom id/RSS guid), 없으면 링크 URL(PRD 4.2).
      guid와 링크가 모두 없는 항목은 건너뛰고 WARNING 로그. content는 `content[0].value` 우선, 없으면 `summary`/`description`, 둘 다 없으면 빈 문자열.
      published_at은 `published_parsed` → 없으면 `updated_parsed`. 사소한 bozo(문법 경고)만 있고 version이 있으면 정상 처리.
    - 이 모듈은 HTTP를 모름(바이트만 받음).
  - touch: `pyproject.toml`, `uv.lock`, `src/rss_wiki/feeds.py`, `tests/test_feeds_parse.py`, `tests/fixtures/`(rss2.xml, atom.xml, not_feed.html 신규)
  - acceptance:
    - `uv run pytest tests/test_feeds_parse.py` 통과 (네트워크 없음):
      RSS 2.0 픽스처의 제목·항목 수·guid·링크·published_at(ISO8601), Atom 픽스처의 id·`content` 우선 사용, guid 없는 RSS 항목 → 링크가 guid,
      guid·링크 모두 없는 항목 건너뜀, HTML 문서 → `FeedParseError`, 한국어 제목이 UTF-8로 깨지지 않음
    - `uv run pytest` 전체 통과 (기존 57건 회귀 없음)

- [x] T5b. 파싱·HTTP 테스트 보강 (T5 REVIEW 메모 1, T4a REVIEW 메모 1, tests만 수정)
  - 내용: `src/` 아래는 수정하지 않음. 현재 동작을 회귀 방지용으로 고정.
    - `tests/test_feeds_parse.py`:
      - 신규 픽스처 `tests/fixtures/rss2_bozo.xml`(본문에 이스케이프 안 된 `&` 포함, 항목 1건) → 예외 없이 제목과 항목 1건 반환.
      - 인라인 RSS: `isPermaLink` 속성 없는 `<guid>post-1</guid>` + 상대 링크 `<link>/rel/1</link>`, `base_url="https://example.com/feed.xml"`
        → guid `https://example.com/post-1`, url `https://example.com/rel/1`.
      - HTML 문서 → `FeedParseError` 테스트에 `base_url in str(exc.value)` 단언 추가.
    - `tests/test_http.py`:
      - `test_self_redirect_is_non_transient_error`에 `"TooManyRedirects" in str(exc.value)`와 `isinstance(exc.value.__cause__, httpx.TooManyRedirects)` 단언 추가.
      - `Content-Encoding: gzip` + gzip이 아닌 본문 → `HttpError(transient=False)`, `__cause__`가 `httpx.DecodingError`, sleep 호출 없음 테스트 1건 추가.
      - ftp 테스트는 transport 주입 없는 기본 `HttpClient()`로 바꿔 실제 스킴 검증 경로를 사용(네트워크 접속 없음).
    테스트가 `src/` 수정 없이 통과하지 않으면 BLOCKED로 기록하고 실제 동작을 IMPL.md에 남김.
  - touch: `tests/test_feeds_parse.py`, `tests/test_http.py`, `tests/fixtures/rss2_bozo.xml`(신규)
  - acceptance:
    - `uv run pytest tests/test_feeds_parse.py tests/test_http.py` 통과 (신규 3건 포함: bozo 픽스처, 상대 guid/링크, DecodingError)
    - `uv run pytest` 전체 통과 (기존 64건 회귀 없음, 67건)

- [x] T5c. bozo 파싱 결과 고정과 HTTP 오류 단언 보강 (T5b REVIEW 메모 1~3, tests만 수정)
  - 내용: `src/` 아래는 수정하지 않음.
    - 메모 1 결정: bozo 피드에서 feedparser 느슨한 파서가 `Q&A 시간`을 `Q&A; 시간`으로 바꾸는 동작은 **보정하지 않고 현재 동작을 고정**함
      (자체 결정: 깨진 피드에서만 생기는 사소한 변형이고, 보정 로직은 정상 피드 제목을 망칠 위험이 있음. 가장 단순한 선택).
    - `tests/test_feeds_parse.py`의 `test_bozo_feed_still_parsed`에 단언 추가:
      항목의 guid(`https://example.com/bozo-1`), url, title(`"Q&A; 시간"`, feedparser 동작 고정이라는 주석 포함), content에 `"Tom & Jerry"` 포함.
      `caplog`(logger `rss_wiki.feeds`, DEBUG)로 `피드 문법 경고` 로그가 기록됨을 단언(픽스처가 실제 bozo 경로를 탄다는 전제 고정).
    - `tests/test_http.py`:
      - `test_bad_gzip_body_is_non_transient_decoding_error`에 `"https://example.com/gz" in str(exc.value)` 단언 추가(실제 테스트 URL에 맞출 것).
      - `test_unsupported_scheme_no_retry`에 `isinstance(exc.value.__cause__, httpx.UnsupportedProtocol)` 단언 추가.
    실제 값이 위와 다르면 실제 동작에 맞춰 단언하고 차이를 IMPL.md에 기록. `src/` 수정 없이 통과하지 않으면 BLOCKED로 기록.
  - touch: `tests/test_feeds_parse.py`, `tests/test_http.py`
  - acceptance:
    - `uv run pytest tests/test_feeds_parse.py tests/test_http.py` 통과 (26건, 신규 테스트 없이 단언만 추가)
    - `uv run pytest` 전체 통과 (67건, 회귀 없음)

- [x] T5a. `feed add/list/remove` 명령
  - 내용: `feeds.py`에 DB 연동 함수 추가(`parse_feed`는 변경하지 않음).
    - `FeedError(Exception)`: 단일 피드 작업 실패(중복 URL, 없는 피드, 피드 아님, HTTP 실패). 메시지에 URL 또는 id 포함.
    - `add_feed(conn, client, url, name=None) -> int`: DB에 같은 URL이 있으면 GET 없이 `FeedError`.
      `client.get(url)` → `parse_feed(resp.content, url)`로 유효성 확인. `parse_feed`의 base_url은 **등록 URL**을 씀
      (리다이렉트 최종 URL이 바뀌어도 guid가 안정적이도록, 자체 결정, T5 REVIEW 메모 4). name 기본값은 피드 제목, 제목도 없으면 URL.
      `HttpError`·`FeedParseError`는 `FeedError`로 감싸 `from exc` 연결. `HttpError.transient`가 True면 메시지에 "일시적 오류, 나중에 다시 시도"를 덧붙임 (자체 결정, T4a REVIEW 메모 2).
      등록 시점에는 글을 저장하지 않음(수집은 T6), etag/last_modified도 저장하지 않음. 새 feed id 반환.
    - `list_feeds(conn) -> list[sqlite3.Row 또는 데이터클래스]`: id 오름차순, id·name·url·last_fetched_at·last_status.
    - `remove_feed(conn, id_or_url: str) -> None`: 정수 문자열이면 id, 아니면 url로 찾음. 없으면 `FeedError`. 기존 글은 `ON DELETE SET NULL`로 유지(PRD 3장).
    - CLI: `feed` 서브커맨드 아래 `add <url> [--name NAME]`, `list`, `remove <id|url>` 등록. 각 명령은 `connect` 후 `init_schema`(멱등)를 호출해
      `init` 전이어도 동작 (자체 결정). `FeedError`는 메시지를 stderr에 출력하고 종료 코드 1. 성공 메시지와 `list` 표는 stdout.
      `list`는 피드가 없으면 "등록된 피드가 없습니다"를 출력하고 0. 마지막 수집 시각이 없으면 `-`로 표시.
    - `HttpClient`는 cli.py의 모듈 함수 `make_http_client(config) -> HttpClient`(`Config.http_timeout`·`max_retries` 사용)로 만들고,
      테스트는 `monkeypatch`로 이 함수를 `HttpClient(transport=httpx.MockTransport(...), sleep=기록용)`을 돌려주게 바꿈.
    - 부수 작업(T5c REVIEW 메모 1, tests만): `tests/test_feeds_parse.py`의 `test_bozo_feed_still_parsed` 로그 단언(78-81행)에
      `"not well-formed" in r.getMessage()` 조건을 추가해, Content-Type 없는 정상 피드에서도 나오는 `no Content-type specified` 로그와 구분함.
      실제 메시지가 다르면 실제 문구에 맞추고 IMPL.md에 기록.
  - touch: `src/rss_wiki/feeds.py`, `src/rss_wiki/cli.py`, `tests/test_feeds_cmd.py`(신규), `tests/test_feeds_parse.py`(단언 1곳만)
  - acceptance:
    - `uv run pytest tests/test_feeds_cmd.py` 통과 (네트워크 없음, `tests/fixtures/rss2.xml`을 MockTransport로 제공):
      - `main(["--data-dir", tmp, "feed", "add", URL])` → 0, feeds 행 1건, name이 피드 제목, stdout에 id 포함
      - `--name 내블로그` 지정 시 name이 그대로 저장
      - 같은 URL 재등록 → 1, stderr에 URL 포함, feeds 행 수 그대로, 두 번째는 HTTP 요청 없음
      - HTML 응답(not_feed.html) → 1, 404 → 1, 503 지속 → 1이고 stderr에 "일시적 오류" 포함, 모두 feeds 행 0건
      - `feed list` → 0, 등록한 피드의 id·name·url이 stdout에 보임. 빈 DB면 "등록된 피드가 없습니다"
      - `feed remove <id>`와 `feed remove <url>` 각각 → 0이고 행 삭제, 없는 id → 1
      - feed 삭제 후 해당 feed의 기존 articles 행(테스트에서 직접 INSERT)이 남고 `feed_id IS NULL`
    - `uv run rss-wiki feed --help` 종료 코드 0
    - `uv run pytest tests/test_feeds_parse.py` 통과 (bozo 로그 단언이 `not well-formed` 포함 메시지를 요구)
    - `uv run pytest` 전체 통과 (기존 67건 회귀 없음)
- [x] T5d. feed 명령 보완 (T5a REVIEW 메모 1~4)
  - 내용:
    - (src, 메모 2) `remove_feed`의 id 판별을 ASCII 숫자만 인정하도록 변경(`id_or_url.isascii() and id_or_url.isdigit()`).
      `²` 같은 유니코드 숫자는 URL로 취급되어 "등록된 피드가 없습니다" `FeedError`가 됨.
    - (docs, 메모 4) feeds.py 1행 모듈 docstring을 "RSS 2.0·Atom 파싱(`parse_feed`는 HTTP 비의존)과 피드 등록/목록/삭제."로 수정.
    - (tests, 메모 1) `test_list_shows_feeds`의 부분 문자열 단언을 출력 줄 전체 비교(`"1\t내블로그\thttps://example.com/feed.xml\t-\t-"`,
      실제 테스트 URL·이름에 맞출 것)로 교체. 404 테스트에 `URL in err`와 `"일시적 오류" not in err` 단언 추가.
    - (tests, 메모 3) 리다이렉트 테스트 추가: MockTransport에서 등록 URL → 302 → `https://example.com/moved.xml`(rss2.xml 제공) 후
      종료 코드 0, `feeds.url == 등록 URL`.
    - (tests, 메모 2) `feed remove ²` → 종료 코드 1, stderr에 `오류:` 포함·`Traceback` 미포함 테스트 추가.
  - touch: `src/rss_wiki/feeds.py`(remove_feed 1줄·docstring), `tests/test_feeds_cmd.py`
  - acceptance:
    - `uv run pytest tests/test_feeds_cmd.py` 통과 (신규 2건: 리다이렉트, `²` 삭제)
    - `uv run rss-wiki --data-dir <tmp> feed remove ²` 종료 코드 1, 트레이스백 없음
    - `uv run pytest` 전체 통과 (기존 79건 회귀 없음, 81건)

- [x] T6. `fetch` 수집·중복 제거·조건부 요청
  - 내용: 신규 `rss_wiki/fetch.py`. 본문 정책·원문 추출은 T7 몫이며, 이번 항목에서는 RSS 본문(HTML 원문 그대로)을 `content_source='rss'`로 저장.
    - `FetchResult` 데이터클래스: `feed_id`, `new: int`, `not_modified: bool`, `error: str | None`.
    - `fetch_feed(conn, client, feed_row) -> FetchResult`: `client.get(feeds.url, etag=feeds.etag, last_modified=feeds.last_modified)`.
      - 304 → 글 저장 없이 `last_status='not_modified'`, `last_fetched_at` 갱신, `error_count=0`.
      - 2xx → `parse_feed(resp.content, feeds.url)` (base_url은 **등록 URL**, 자체 결정, T5 REVIEW 메모 4). 응답의 etag/last_modified 저장,
        `last_status='ok'`, `error_count=0`. 항목마다: 같은 (feed_id, guid)가 있으면 건너뜀. 없고 같은 guid의 고아 글(`feed_id IS NULL`)이 있으면
        삽입하지 않고 `feed_id`를 현재 feed로 UPDATE(재연결, T2 REVIEW 메모 1, 자체 결정, 스키마 변경 없음). 둘 다 없으면 INSERT
        (`fetched_at`은 UTC ISO8601 `YYYY-MM-DDTHH:MM:SSZ`). 한 피드의 글 저장은 `BEGIN`/`COMMIT`으로 묶음(autocommit 계약).
      - `HttpError`·`FeedParseError` → 예외를 밖으로 내지 않고 `error_count += 1`, `last_status='error: <메시지>'`, `last_fetched_at` 갱신,
        WARNING 로그, `FetchResult.error`에 메시지. 피드 하나 실패가 다른 피드를 멈추지 않음(PRD 7장).
    - fetch는 summaries 행을 만들지 않음. 요약 대상은 T10에서 "summaries 행이 없거나 pending인 글"로 고름 (자체 결정).
    - `fetch_all(conn, client, feed_id: int | None = None) -> list[FetchResult]`: id 오름차순 순차 처리(PRD 10장). 없는 feed_id면 `FeedError`.
    - CLI: `fetch [--feed ID]`. `connect`+`init_schema` 후 실행, 피드별 결과 한 줄(`<id>\t<name>\t새 글 N건|변경 없음|오류: ...`)을 stdout에,
      마지막에 합계 한 줄. 실패 피드가 하나라도 있으면 종료 코드 1, 없는 `--feed` id면 stderr + 1, 등록 피드가 없으면 안내 후 0.
    - Content-Type 연동(T5 REVIEW 메모 3)은 T6a로 분리했으므로 이번 항목에서 `HttpResponse`·`parse_feed` 시그니처는 바꾸지 않음.
    - 부수 작업(T5d REVIEW 메모 1, tests만): `tests/test_feeds_cmd.py`의 `test_remove_unicode_digit_is_not_an_id`에
      `"등록된 피드가 없습니다" in err` 단언 1줄 추가(URL 경로로 처리됐음을 직접 고정). 다른 테스트는 건드리지 않음.
  - touch: `src/rss_wiki/fetch.py`(신규), `src/rss_wiki/cli.py`, `tests/test_fetch.py`(신규), `tests/fixtures/`(필요 시 rss2 변형 픽스처 신규), `tests/test_feeds_cmd.py`(단언 1줄만)
  - acceptance:
    - `uv run pytest tests/test_fetch.py` 통과 (MockTransport, 네트워크 없음):
      - 첫 fetch → rss2.xml 항목 수만큼 articles 행, `content_source='rss'`, feeds.etag/last_modified가 응답 헤더 값으로 저장, `last_status='ok'`
      - 같은 응답으로 두 번째 fetch → articles 행 수 그대로(멱등), 두 번째 요청에 `If-None-Match`/`If-Modified-Since` 헤더 포함
      - 304 응답 → 새 글 0, `last_status='not_modified'`
      - 503 지속(sleep 스텁) → `error_count` 1 증가, `last_status`가 `error:`로 시작, 함께 등록된 다른 피드는 정상 수집
      - feed 삭제 → 같은 URL 재등록 → fetch 시 articles 행 수가 늘지 않고 기존 글의 `feed_id`가 새 feed id (고아 재연결)
      - 상대 guid 피드(T5b 인라인 RSS와 같은 형태)를 리다이렉트된 최종 URL에서 받아도 guid가 등록 URL 기준으로 풀림 (T5a REVIEW 메모 3 후반)
      - CLI: `main([... "fetch"])` 성공 시 0, 실패 피드 포함 시 1, `fetch --feed 999` → 1
    - `uv run rss-wiki fetch --help` 종료 코드 0
    - `uv run pytest tests/test_feeds_cmd.py` 통과 (14건, `²` 테스트가 "등록된 피드가 없습니다" 문구를 요구)
    - `uv run pytest` 전체 통과 (T5d 이후 81건 회귀 없음)

- [x] T6b. fetch 저장 오류 방침·last_status 길이 상한·테스트 보강 (T6 REVIEW 메모 1~4)
  - 내용:
    - (src, 메모 2 결정) 글 저장 중 `sqlite3.Error`는 **치명적 오류(종료 코드 2)**로 처리함 (자체 결정: 잠긴 DB·디스크 오류는
      다음 피드에서도 반복될 가능성이 높고, PRD 7장의 "DB를 열 수 없으면 즉시 종료"와 같은 범주. 되돌리기 쉬움).
      `fetch_feed`의 저장 블록에서 `sqlite3.Error`를 잡으면 ROLLBACK(ROLLBACK 자체의 `sqlite3.Error`는 무시) 후
      `DatabaseError(f"글 저장 실패 (feed id={id}, {url}): {exc}")`를 `from exc`로 던짐. `sqlite3.Error`가 아닌 예외는 기존대로 ROLLBACK 후 재던짐.
      cli.py는 이미 `DatabaseError`를 종료 코드 2로 매핑하므로 수정 불필요(이미 출력한 피드별 줄은 그대로 남고 합계 줄은 출력하지 않음).
      `_record_error`(HTTP·파싱 실패 기록)에서 나는 `sqlite3.Error`도 같은 방식으로 `DatabaseError`로 감쌈.
    - (src, 메모 3) `last_status`에 저장하는 오류 메시지를 200자로 자름(`error: ` 접두어 제외, 넘으면 끝에 `…`). `FetchResult.error`와 로그는 원문 유지. 상수 `MAX_STATUS_CHARS = 200`.
    - (참고, 메모 4) `fetch_all`은 T13 `run`에서 사용할 예정이므로 유지하고 아래 테스트로 고정.
    - (tests, 메모 1) `tests/test_fetch.py`에 추가:
      - 503 지속 테스트에 `caplog`(logger `rss_wiki.fetch`, WARNING) 단언: 레코드 1건 이상, 메시지에 피드 URL 포함
      - `not_feed.html` 응답 → CLI 종료 코드 1, `last_status`가 `error:`로 시작, `error_count == 1`
      - 실패(503) 뒤 정상 200 → `error_count == 0`, `last_status == 'ok'`
      - 304 테스트에 `error_count == 0`과 `last_fetched_at`이 NULL이 아님(또는 이전 값과 다름) 단언 추가
      - `fetch_all` 직접 호출: 피드 2개 등록 시 반환 `feed_id` 순서가 id 오름차순, 없는 id → `FeedError`
      - `monkeypatch`로 `rss_wiki.fetch._store_entries`가 `sqlite3.OperationalError("database is locked")`를 던지게 하면
        `main([... "fetch"])` → 2, stderr에 `database is locked` 포함·`Traceback` 미포함, articles 0건(ROLLBACK), 해당 feeds의 `last_status`가 `ok`가 아님
      - 1000자 오류 메시지(예: `parse_feed`를 monkeypatch해 긴 메시지의 `FeedParseError`) → `last_status` 길이 ≤ `len("error: ") + 201`이고 `…`로 끝남, `FetchResult.error`는 원문 길이
  - touch: `src/rss_wiki/fetch.py`, `tests/test_fetch.py`
  - acceptance:
    - `uv run pytest tests/test_fetch.py` 통과 (위 신규 테스트 포함)
    - `uv run pytest` 전체 통과 (T6 이후 91건 회귀 없음)

- [x] T6a. HTTP Content-Type을 파서에 전달 (T5 REVIEW 메모 3, 선택) — **범위 밖으로 닫음**
  - 결정(Planner, 2026-11-02, 자체 결정): 구현하지 않음. 영향은 DEBUG 로그 소음뿐이고 PRD 요구가 아니며, 도입 시 `HttpResponse`·`parse_feed` 시그니처와
    bozo 로그 단언(T5c)을 함께 바꿔야 해 최소 변경 원칙에 어긋남. 필요해지면 아래 메모대로 새 항목으로 재개.
  - 메모: 정상 피드마다 남는 `no Content-type specified` bozo DEBUG 로그를 줄이기 위해
    `HttpResponse`에 `content_type`을 추가해 `parse_feed`에 전달하는 방안을 검토(시그니처는 키워드 인자 기본값 None으로 하위 호환 유지).
    도입하면 T5c의 bozo 로그 단언(`피드 문법 경고`)이 여전히 맞는지 함께 점검할 것 (T5b REVIEW 메모 2).
    도입 시 "정상 피드(rss2.xml, content_type 지정)에서는 `피드 문법 경고` 로그가 없음"을 단언하는 반대 방향 테스트도 추가할 것 (T5c REVIEW 메모 1).
- [x] T7. 본문 추출 모듈(trafilatura)과 fetch 오류 경로 보완 (T6b REVIEW 메모 1~3)
  - 내용: `uv add trafilatura`. 신규 `rss_wiki/extract.py`(HTTP·DB 비의존, 문자열만 다룸). fetch 연동은 T7a 몫이므로 이번에는 fetch.py의 수집 동작을 바꾸지 않음.
    - `html_to_text(html: str) -> str`: RSS `content`/`description`의 길이 판정용 텍스트 변환. 표준 라이브러리 `html.parser.HTMLParser`로 태그 제거,
      `script`/`style` 내용 제외, 엔티티 해제(`&amp;` → `&`), 연속 공백을 공백 하나로 접고 앞뒤 공백 제거. 빈 입력이면 `""` (자체 결정: 짧은 조각에는
      trafilatura 휴리스틱이 본문을 버릴 수 있어 단순 변환이 적합).
    - `extract_article(html: str | bytes, url: str | None = None) -> str | None`: `trafilatura.extract`로 원문 페이지의 본문 텍스트 추출.
      결과가 None·공백뿐이면 None. trafilatura 내부 예외는 밖으로 내지 않고 DEBUG 로그 후 None (호출 측이 "추출 실패"로만 처리하도록).
    - 부수 작업(src, T6b 메모 1): `fetch_feed`의 304 분기 UPDATE(fetch.py:107-110)에서 나는 `sqlite3.Error`를
      `DatabaseError(f"수집 상태 기록 실패 (feed id={id}, {url}): {exc}")`로 `from exc` 감쌈. 그 외 fetch 동작은 그대로.
    - 부수 작업(tests, T6b 메모 2): `test_store_failure_is_fatal_and_rolled_back`의 `boom`이 원래 `_store_entries`를 먼저 호출(실제 INSERT 발생)한 뒤
      `sqlite3.OperationalError("database is locked")`를 던지게 바꿔, "articles 0건" 단언이 ROLLBACK을 실제로 검증하게 함.
    - 부수 작업(tests, T6b 메모 3): 트리거(`CREATE TRIGGER ... BEFORE UPDATE ON feeds BEGIN SELECT RAISE(ABORT, 'boom'); END`) 등으로
      `_record_error` UPDATE를 실패시킨 503 피드 → `main([... "fetch"])` 종료 코드 2, stderr에 `수집 오류 기록 실패` 포함·`Traceback` 미포함.
      같은 방식으로 304 분기 실패 → 종료 코드 2, stderr에 `수집 상태 기록 실패`. 절단 테스트의 단언을 `len(status) == len("error: ") + 201`로 정확히 확인.
  - touch: `pyproject.toml`, `uv.lock`, `src/rss_wiki/extract.py`(신규), `src/rss_wiki/fetch.py`(304 분기 래핑만), `tests/test_extract.py`(신규),
    `tests/fixtures/article.html`(신규: 메뉴·푸터·`<script>`와 한국어 본문 문단 여러 개, 본문 600자 이상), `tests/test_fetch.py`
  - acceptance:
    - `uv run pytest tests/test_extract.py` 통과 (네트워크 없음):
      - `html_to_text("<p>Tom &amp; Jerry</p><script>x()</script>  <b>굵게</b>")` == `"Tom & Jerry 굵게"`, `html_to_text("")` == `""`
      - `extract_article(article.html)`이 본문 문단의 특정 한국어 문장을 포함하고 `<script>` 내용·푸터 문구는 포함하지 않음, 길이 500자 이상
      - 본문 없는 HTML(`<html><body></body></html>`)과 빈 문자열 → None
      - `trafilatura.extract`를 monkeypatch해 예외를 던지게 하면 예외 없이 None
    - `uv run pytest tests/test_fetch.py` 통과 (ROLLBACK 테스트 강화, `_record_error`·304 분기 실패 → 2 테스트 2건 추가, 절단 정확 단언)
    - `uv run pytest` 전체 통과 (T6b 이후 98건 회귀 없음)

- [x] T7a. fetch에 본문 정책 연동 (PRD 4.2) + T7 REVIEW 메모 1~3
  - 내용:
    - (src, fetch.py) `fetch_feed(conn, client, feed, *, min_content_chars: int = 500)`, `fetch_all(..., feed_id=None, *, min_content_chars: int = 500)`.
      파싱 후 `BEGIN` **전에** 원문 추출 대상을 고름: 이 피드에 같은 guid가 없고 같은 guid의 고아 글도 없는 항목(=INSERT될 새 글, 응답 안 guid 중복은 첫 항목만) 중
      `len(html_to_text(entry.content)) < min_content_chars`인 것. 대상마다 트랜잭션 밖에서 `client.get(entry.url)` → `extract_article(resp.content, entry.url)`.
      성공하면 추출 텍스트를 `content`로, `content_source='extracted'`로 INSERT. `HttpError`·None이면 RSS 본문(HTML 원문 그대로)·`content_source='rss'`이고
      INFO 로그 `원문 추출 실패, RSS 본문 사용 (<url>): <원인>`. 원문 실패는 피드 실패가 아님(`last_status='ok'`, `FetchResult.error is None`).
      url 스킴이 http/https가 아니면 GET 없이 `rss`이고 INFO 로그(자체 결정, T5 REVIEW 메모 2). 재연결·기존 글은 추출하지 않음.
      `_store_entries`는 guid → (content, source) 대체 맵을 받아 INSERT에 쓰는 방식 등으로 구현(시그니처는 Generator 재량, 기존 monkeypatch 테스트가 깨지면 함께 맞출 것).
    - (src, cli.py) `cmd_fetch`가 `config.min_content_chars`를 넘김. `_setup_logging`의 noisy 처리에 `trafilatura` 로거를 추가하되 수준은 **CRITICAL**
      (trafilatura가 추출 실패를 ERROR로 내므로 WARNING으로는 부족, 자체 결정, T7 REVIEW 메모 1). `httpx`/`httpcore`는 기존대로 WARNING.
    - (tests, conftest.py) 저장·복원 대상 로거에 `trafilatura` 추가.
    - (tests, T7 REVIEW 메모 2) `test_extract_article_swallows_exceptions`에 caplog(`rss_wiki.extract`, DEBUG)로 url 포함 레코드 단언,
      `test_extract_article_accepts_bytes`에 한국어 본문 문장 포함 단언 추가.
    - (tests, T7 REVIEW 메모 3) `html_to_text("un<b>bold</b>") == "un bold"` 동작 고정 테스트 1건 추가(길이 판정 전용이며 저장·요약 입력에는 쓰지 않음을 주석으로 명시). `extract.py`는 수정하지 않음.
    - 기존 test_fetch.py 테스트가 rss2.xml의 짧은 본문 때문에 원문 GET을 하게 되어 요청 수 단언이 깨지면, MockTransport 핸들러가 글 URL에 404를 주도록 맞추거나
      해당 테스트에 `min_content_chars=0`을 넘겨 의도를 유지하고 IMPL.md에 기록.
  - touch: `src/rss_wiki/fetch.py`, `src/rss_wiki/cli.py`, `tests/test_fetch.py`, `tests/test_extract.py`, `tests/conftest.py`, `tests/fixtures/`(필요 시 짧은/긴 본문 RSS 픽스처 신규)
  - acceptance:
    - `uv run pytest tests/test_fetch.py` 통과, 아래 신규 테스트 포함 (MockTransport, 네트워크 없음):
      - 본문 500자 이상 항목 → 원문 GET 0회, `content_source='rss'`
      - 짧은 본문 항목, 원문 URL이 `tests/fixtures/article.html` 응답 → `content_source='extracted'`, content에 article.html 본문 문장 포함
      - 짧은 본문, 원문 404 → `content_source='rss'`, content는 RSS 본문, `last_status='ok'`, CLI `fetch` 종료 코드 0, caplog에 `원문 추출 실패, RSS 본문 사용` INFO
      - url이 `urn:1`인 짧은 본문 항목 → 원문 HTTP 요청 0회, `content_source='rss'`
      - 같은 피드 재수집(200 동일 응답) → 원문 GET 0회, articles 행 수 그대로
      - `min_content_chars=0` → 원문 GET 0회
      - 원문 GET 중(핸들러 안)에서 별도 연결로 `BEGIN IMMEDIATE`가 성공함 → 원문 GET이 트랜잭션 밖임을 확인
      - CLI `main([... "fetch"])`로 추출 실패 경로 실행 시 stderr에 `trafilatura`가 포함된 ERROR 줄이 없음 (본문 없는 HTML 응답으로 trafilatura 오류 유발)
    - `uv run pytest tests/test_extract.py` 통과 (메모 2 단언, `un<b>bold</b>` 고정 테스트 포함)
    - `uv run pytest` 전체 통과 (T7 이후 107건 회귀 없음)

- [x] T7b. fetch 조회 오류 래핑과 본문 정책 테스트 보강 (T7a REVIEW 메모 1~3)
  - 내용:
    - (src, 메모 1) `_resolve_bodies`의 `_is_new` 조회(fetch.py:80-86, 103)에서 나는 `sqlite3.Error`를 잡아
      `DatabaseError(f"글 조회 실패 (feed id={id}, {url}): {exc}") from exc`로 감쌈(T6b/T7의 "DB 오류 → 메시지 + 종료 코드 2" 정책과 일치).
      원문 GET의 `HttpError` 처리 등 다른 동작은 바꾸지 않음.
    - (tests, 메모 1) `monkeypatch`로 `rss_wiki.fetch._is_new`가 `sqlite3.OperationalError("disk I/O error")`를 던지게 하고 짧은 본문 피드를
      `main([... "fetch"])` → 종료 코드 2, stderr에 `글 조회 실패` 포함·`Traceback` 미포함, articles 0건.
    - (tests, 메모 2) 한 응답 안에 같은 guid·짧은 본문 항목이 2번 있는 RSS → 원문 GET 1회, articles 1건.
      원문 URL이 503 지속(sleep 스텁) → `content_source='rss'`, `last_status='ok'`, `FetchResult.error is None`.
    - (tests, 메모 3) `test_original_404_falls_back_to_rss_body`(test_fetch.py:326-336)에서 쓰지 않는 `caplog` 인자와
      `addHandler` 두 줄(329, 332)을 제거함(로그 단언은 `test_original_404_logs_info`가 담당). 나머지 단언은 유지.
  - touch: `src/rss_wiki/fetch.py`(`_resolve_bodies` 예외 래핑만), `tests/test_fetch.py`
  - acceptance:
    - `uv run pytest tests/test_fetch.py` 통과 (신규 3건: 조회 실패 → 2, 응답 내 guid 중복 → 원문 GET 1회, 원문 503 → rss·ok)
    - `uv run pytest` 전체 통과 (T7a 이후 117건 회귀 없음, 120건)

## M3. 요약
- [x] T8. `Summarizer` 프로토콜, 응답 스키마 검증, 입력 절단 (LLM·DB 비의존)
  - 내용: 신규 `rss_wiki/summarize.py`. Claude 구현(T9)과 명령·DB 연동(T10)은 이번 항목에서 하지 않으며 새 의존성도 추가하지 않음.
    - `SummaryResult` 데이터클래스(frozen): `tldr: str`, `key_points: list[str]`, `tags: list[str]`.
    - `SummaryValidationError(Exception)`: 응답이 스키마에 맞지 않음(PRD 7장 "검증 실패 = 실패 1회"의 근거). 메시지에 어긋난 필드명 포함.
    - `SummarizerError(Exception)`: 공급자 호출 실패. `transient: bool` 속성(네트워크·429·과부하면 True, T10 재시도 판단용).
    - `Summarizer` (`typing.Protocol`): `model: str` 속성과 `summarize(title: str | None, content: str, existing_tags: list[str]) -> SummaryResult`.
      구현은 `SummaryValidationError`·`SummarizerError`만 밖으로 내는 계약을 docstring에 적음.
    - `SUMMARY_SCHEMA`: PRD 4.3 JSON 스키마 dict(`tldr` string, `key_points` array 3~5, `tags` array 1~5, 모두 required, `additionalProperties: false`). T9에서 구조화 출력에 그대로 사용.
    - `validate_summary(data: object) -> SummaryResult`: 외부 라이브러리 없이 직접 검증 (자체 결정: jsonschema 의존성 불필요, 가장 단순).
      dict가 아님, 필수 키 누락, 타입 불일치, `tldr` 공백뿐, `key_points` 3~5개 아님 또는 빈 문자열 포함 → `SummaryValidationError`.
      `tags`는 앞뒤 공백 제거·소문자화(PRD 10장)·빈 문자열 제거·순서 유지 중복 제거 후 1~5개가 아니면 `SummaryValidationError`. 문자열 값은 strip해서 담음. 추가 키는 무시 (자체 결정).
    - `truncate_input(text: str, max_chars: int) -> str`: `len(text) <= max_chars`면 그대로, 넘으면 앞 `max_chars`자만(PRD 4.3 기본 20,000자). `max_chars <= 0`이면 `ValueError`.
    - `build_prompt(title: str | None, content: str, existing_tags: list[str], max_chars: int) -> str`: 원문 언어와 관계없이 한국어로 요약하라는 지시,
      제목(없으면 생략), 절단된 본문, 기존 태그 목록(재사용 유도, 없으면 "없음"), 태그는 소문자라는 지시를 담음. 기존 태그는 정렬해서 넣어 결정적으로 만듦.
    - 부수 작업(tests만, T7b REVIEW 메모 1·2): `tests/test_fetch.py`에서 단언만 추가하고 `src/rss_wiki/fetch.py`는 수정하지 않음.
      - `test_original_503_falls_back_to_rss_body`: 원문 URL 요청 횟수 == `1 + max_retries`(테스트의 `HttpClient` 설정값 기준), 저장된 `content == "<p>짧음</p>"`(실제 픽스처 본문에 맞출 것).
      - `test_lookup_failure_is_fatal`: `fetch_feed`를 직접 호출해 `DatabaseError`가 나고 `isinstance(exc.value.__cause__, sqlite3.OperationalError)`임을 단언(기존 CLI 단언은 유지).
      실제 값이 다르면 실제 동작에 맞춰 단언하고 IMPL.md에 기록. `src/` 수정 없이 통과하지 않으면 BLOCKED로 기록.
  - touch: `src/rss_wiki/summarize.py`(신규), `tests/test_summarize_core.py`(신규), `tests/test_fetch.py`(단언 추가만)
  - acceptance:
    - `uv run pytest tests/test_summarize_core.py` 통과 (네트워크·LLM 없음):
      - 정상 dict → `SummaryResult`, 태그 `[" Python", "python", "AI "]` → `["python", "ai"]`
      - `key_points` 2개·6개, `tags` 0개·6개(정규화 후 기준), `tldr` 누락·`"  "`, `key_points`가 문자열, 입력이 list → 각각 `SummaryValidationError`이고 메시지에 필드명 포함
      - `truncate_input("가"*25000, 20000)` 길이 20000, 짧은 입력은 그대로, `max_chars=0` → `ValueError`
      - `build_prompt`가 "한국어" 지시·제목·기존 태그를 포함하고, 본문이 `max_chars`로 잘리며, 기존 태그 순서가 달라도 결과가 같음
      - 테스트용 가짜 구현(`FakeSummarizer`)이 `isinstance(fake, Summarizer)`를 만족(`@runtime_checkable`)
    - `uv run pytest tests/test_fetch.py` 통과 (31건, 신규 테스트 없이 단언만 추가)
    - `uv run pytest` 전체 통과 (T7b 이후 120건 회귀 없음)
- [x] T9. Claude 구현 (Anthropic SDK) + T8 REVIEW 메모 1·2·4
  - 메모(Planner): 이 항목의 별도 REVIEW.md는 없음(현재 REVIEW.md는 T8 대상). T10 Evaluator가 `tests/test_claude.py` 17건(당초 "20건"은 오기, T10 REVIEW로 정정) 회귀와
    IMPL.md의 편차(테스트가 `httpx2.MockTransport` 사용, 529는 상태 코드로 transient 판정)를 함께 확인할 것.
  - 내용: `uv add anthropic`. 신규 `rss_wiki/claude.py`. 명령·DB 연동(T10)은 하지 않음.
    - `ClaudeSummarizer(client, model: str, max_input_chars: int = 20000, max_tokens: int = 1024)`: `Summarizer` 프로토콜 구현, `model` 속성 노출.
      `client`는 `anthropic.Anthropic` 또는 같은 모양(`client.messages.create(**kwargs)`)의 객체 (테스트 주입용).
    - 구조화 출력 방식(T8 REVIEW 메모 2 결정): **강제 도구 호출**로 받음 (자체 결정: 오래 지원된 안정 API이고 가짜 클라이언트로 대체하기 쉬움).
      `tools=[{"name": "record_summary", "description": ..., "input_schema": SUMMARY_SCHEMA}]`, `tool_choice={"type": "tool", "name": "record_summary"}`,
      `messages=[{"role": "user", "content": build_prompt(title, content, existing_tags, max_input_chars)}]`.
      strict 모드는 쓰지 않으므로 `minItems`/`maxItems`는 모델에 주는 안내일 뿐 API가 강제하지 않음. 개수 검증은 항상 `validate_summary`가 최종 방어선 (자체 결정).
      응답 `content`에서 `type == "tool_use"`이고 `name == "record_summary"`인 블록의 `input`을 `validate_summary`에 넘김.
      해당 블록이 없으면(`stop_reason == "max_tokens"` 포함) `SummaryValidationError("tool_use 응답 없음 ...")`.
    - 예외 매핑(Protocol 계약: `SummaryValidationError`·`SummarizerError`만 밖으로): `anthropic.APIConnectionError`(타임아웃 포함)·`RateLimitError`(429)·
      `InternalServerError`(5xx, 529 과부하 포함) → `SummarizerError(transient=True)`. 그 외 `anthropic.APIStatusError`(400·401·403·404 등)와 기타 `anthropic.AnthropicError`
      → `SummarizerError(transient=False)`. 메시지에 모델명과 원인(상태 코드 또는 예외 타입명) 포함, `from exc` 연결. API 키는 메시지·로그에 넣지 않음.
    - `create_claude_summarizer(config, env: Mapping[str, str] = os.environ) -> ClaudeSummarizer`: `env["ANTHROPIC_API_KEY"]`가 없거나 빈 값이면
      `ConfigError("ANTHROPIC_API_KEY 환경 변수가 없습니다")`(PRD 7장 치명적 오류, 종료 코드 2는 T10에서 매핑). 있으면
      `anthropic.Anthropic(api_key=..., max_retries=0, timeout=config.http_timeout 이상의 적절한 값)`으로 생성, `config.model`·`config.max_input_chars` 사용.
      SDK 자체 재시도는 끄고 재시도는 T10 정책이 맡음 (자체 결정: PRD 7장 "최대 3회"가 중복 적용되지 않게).
    - 부수 작업(src, T8 메모 4): `build_prompt`에서 기존 태그를 `strip().lower()`·빈 값 제거·중복 제거 후 정렬. 그 외 summarize.py는 바꾸지 않음.
    - 부수 작업(tests, T8 메모 1): `tests/test_summarize_core.py`에 `key_points=[1, 2, 3]`, `tags=[None]` → `SummaryValidationError`이고 메시지에 필드명 포함,
      입력이 list일 때 `match="dict"` 단언, `build_prompt`에 `["Python", " python", "AI"]`를 넘기면 `ai, python`이 들어가는지 단언.
  - touch: `pyproject.toml`, `uv.lock`, `src/rss_wiki/claude.py`(신규), `src/rss_wiki/summarize.py`(`build_prompt` 태그 정규화만), `tests/test_claude.py`(신규), `tests/test_summarize_core.py`
  - acceptance:
    - `uv run pytest tests/test_claude.py` 통과 (실제 네트워크·API 키 없음). 클라이언트는 가짜 객체 또는
      `anthropic.Anthropic(api_key="test-key", max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(handler)))`로 만듦:
      - 정상 tool_use 응답 → `SummaryResult`, 태그 소문자 정규화. 요청 인자에 `model`, `tool_choice` 강제, `input_schema == SUMMARY_SCHEMA`, 프롬프트에 "한국어"·제목 포함
      - 본문 25,000자 → 요청 프롬프트의 본문이 `max_input_chars`로 잘림
      - `key_points` 2개인 tool_use 응답(스키마 안내를 어긴 응답) → `SummaryValidationError`
      - tool_use 블록 없음(text만, 또는 `stop_reason="max_tokens"`) → `SummaryValidationError`
      - HTTP 429·500·529와 연결 오류 → `SummarizerError(transient=True)`, 400·401 → `SummarizerError(transient=False)`, 모두 `__cause__`가 anthropic 예외, 메시지에 API 키 문자열 없음
      - `isinstance(ClaudeSummarizer(...), Summarizer)`
      - `create_claude_summarizer(config, env={})` → `ConfigError`, `env={"ANTHROPIC_API_KEY": "k"}` → `model == config.model`
    - `uv run pytest tests/test_summarize_core.py` 통과 (메모 1 단언·build_prompt 태그 정규화 테스트 포함)
    - `uv run pytest` 전체 통과 (T8 이후 142건 회귀 없음)
- [x] T10. 요약 실행 모듈: 대상 선정·재시도·실패 고정·DB 기록 (CLI 연동은 T10a)
  - 결과: REVIEW PASS 10/12 (2026-10-31). 메모 1~4는 T10b, 메모 5는 T10a 사양(`--limit` 양의 정수)으로 해소.
  - 메모(Planner): T9는 별도 REVIEW 없이 완료됨. 이번 Evaluator는 T10 평가와 함께 `tests/test_claude.py` 17건(당초 "20건"은 오기) 회귀와 IMPL(T9) 편차
    (`httpx2.MockTransport` 사용, 529를 상태 코드로 transient 판정, `SummarizerError` 메시지에 SDK 원문 미포함)를 확인할 것.
    `ClaudeSummarizer`의 실패 메시지는 `요약 호출 실패 (model=…, HTTP 429)` 형태이므로 `last_error`에는 이 문구가 그대로 들어가면 충분함(원문은 로그에도 넣지 않음, 키 노출 방지).
    `last_error` 200자 절단은 fetch.py의 같은 규칙(`MAX_STATUS_CHARS`)을 재사용하거나 같은 동작으로 구현하되 fetch.py는 수정하지 않음.
    고아 글(`feed_id IS NULL`)도 요약 대상에 포함함 (자체 결정: PRD 3장 "기존 글/요약은 유지").
  - 내용: 신규 `rss_wiki/summarize_run.py`(DB 의존, LLM은 `Summarizer` 프로토콜로만 접근). summarize.py·claude.py·cli.py는 수정하지 않음. 새 의존성 없음.
    - 용어 결정 (자체 결정): `summaries.attempts`는 **누적 실패 횟수**(실행 단위). 한 실행 안의 재시도는 합쳐서 실패 1회로 셈.
      `attempts >= max_failures`(기본 5)가 되면 `status='failed'`로 고정(PRD 7장 "기준을 넘으면", 5회째 실패에서 고정).
    - `select_targets(conn, *, limit: int | None = None, retry_failed: bool = False) -> list[sqlite3.Row]`:
      summaries 행이 없거나 `status='pending'`인 글(T6 자체 결정), `retry_failed`면 `status='failed'`도 포함. `done`은 제외. articles.id 오름차순, `limit`이 있으면 그 수만.
      행에는 최소 `id`, `title`, `content`가 있어야 함.
    - `SummarizeOutcome` 데이터클래스: `article_id: int`, `ok: bool`, `error: str | None`.
    - `summarize_article(conn, summarizer, article, existing_tags: list[str], *, max_retries=3, max_failures=5, sleep=time.sleep, backoff_base=1.0) -> SummarizeOutcome`:
      `summarizer.summarize(article["title"], article["content"] or "", existing_tags)` 호출.
      - `SummarizerError(transient=True)` → `sleep(backoff_base * 2**i)`로 지수 백오프하며 최대 `max_retries`회 재시도(총 시도 `1 + max_retries`, http.py와 같은 규칙).
        `transient=False`와 `SummaryValidationError`는 재시도 없음(PRD 7장 "검증 실패 = 실패 1회").
      - 성공: `BEGIN` 안에서 summaries UPSERT(`status='done'`, `tldr`, `key_points`=`json.dumps(list, ensure_ascii=False)`, `model=summarizer.model`,
        `summarized_at`=UTC `YYYY-MM-DDTHH:MM:SSZ`, `last_error=NULL`, `attempts`는 유지), `tags`에 `INSERT OR IGNORE`, `article_tags` 연결
        (재요약 시 해당 글의 기존 `article_tags`는 지우고 다시 넣음), `COMMIT`. 성공 시 `existing_tags`(호출 측 리스트)에 새 태그를 추가해 다음 글 프롬프트에 반영.
      - 실패: summaries UPSERT(`attempts = 기존 + 1`, `last_error`=메시지 200자 상한(fetch.py `MAX_STATUS_CHARS`와 같은 규칙·`…`),
        `status = 'failed' if attempts >= max_failures else 'pending'`), WARNING 로그(글 id·url·원인). 예외는 밖으로 내지 않음(PRD 7장 항목 단위 격리).
      - `sqlite3.Error`는 ROLLBACK(ROLLBACK 자체 오류 무시) 후 `DatabaseError(f"요약 저장 실패 (article id={id}): {exc}") from exc` (T6b와 같은 치명 정책).
      - `SummaryResult`의 list 필드는 tuple로 바꾸지 않고 그대로 둠, 이 모듈은 결과를 변경하지 않음 (자체 결정, T8 REVIEW 메모 3 종결).
    - `load_tag_names(conn) -> list[str]`: `tags.name` 정렬 목록.
    - `summarize_pending(conn, summarizer, *, limit=None, retry_failed=False, max_retries=3, max_failures=5, sleep=time.sleep) -> list[SummarizeOutcome]`:
      `select_targets` → `load_tag_names` → 글마다 순차로 `summarize_article`(PRD 10장 순차 처리).
  - touch: `src/rss_wiki/summarize_run.py`(신규), `tests/test_summarize_run.py`(신규)
  - acceptance:
    - `uv run pytest tests/test_summarize_run.py` 통과 (tmp DB에 articles를 직접 INSERT, 가짜 Summarizer와 기록용 sleep 스텁, 네트워크·LLM 없음):
      - 성공 → summaries `status='done'`, `key_points`가 JSON 배열(한국어가 `\u` 이스케이프 없이 저장), `model` 기록, tags·article_tags 행 생성, 같은 태그를 쓰는 두 번째 글은 tags 행이 늘지 않음
      - 두 번째 글의 `existing_tags` 인자에 첫 글의 태그가 들어 있음
      - transient 오류 2회 후 성공 → done, sleep 인자 `[1.0, 2.0]`, `attempts == 0`
      - transient 오류 계속 → 총 4회 호출, `attempts == 1`, `status='pending'`, `last_error`에 원인 포함
      - `SummaryValidationError`(가짜가 "스키마는 통과했지만 `validate_summary`에서 실패"하는 dict를 `validate_summary`에 넘겨 발생시킴) → 호출 1회, sleep 없음, `attempts == 1` (T8 REVIEW 메모 2)
      - `SummarizerError(transient=False)` → 호출 1회, `attempts == 1`
      - `attempts == 4`인 pending 글이 한 번 더 실패 → `attempts == 5`, `status='failed'`. 이후 `select_targets()`에서 제외, `select_targets(retry_failed=True)`에는 포함
      - `done` 글은 대상에서 제외, `limit=1`이면 1건만, id 오름차순
      - 한 글 실패가 다음 글 처리를 막지 않음(2건 중 첫 글 실패, 둘째 done), 실패 시 caplog(`rss_wiki.summarize_run`, WARNING)에 글 id 포함
      - 1000자 오류 메시지 → `last_error` 길이 201이고 `…`로 끝남
      - `monkeypatch`로 저장 단계가 `sqlite3.OperationalError`를 던지게 하면 `DatabaseError`, `__cause__`가 `sqlite3.OperationalError`, summaries·article_tags에 반쯤 쓴 행 없음(ROLLBACK)
    - `uv run pytest` 전체 통과 (T9 이후 162건 회귀 없음)

- [x] T10b. 요약 실행 모듈 보완 (T10 REVIEW 메모 1~4)
  - 결과: REVIEW PASS 11/12 (2026-10-31). 메모 1·2(테스트 단언 보강)·3(로그/stdout 분리 확인)은 T10a로 이관.
  - 내용:
    - (src, 메모 1) `summarize_article`의 실패 WARNING 로그(summarize_run.py:140)가 `url` 키 없는 행에서도 동작하게 함
      (예: `article["url"] if "url" in article.keys() else "-"`; `sqlite3.Row`와 dict 모두 지원). 행의 최소 필드 계약은 `id`, `title`, `content` 유지 (자체 결정: 호출 측 부담이 가장 적음).
    - (src, 메모 4) 재시도 직전(summarize_run.py:84 부근)에 DEBUG 로그 `요약 재시도 (article id=…, n/max, 대기 s초): <원인>`,
      성공 기록 후 INFO 로그 `요약 완료 (article id=…, 태그 …)`를 추가. 로그에 API 키·SDK 원문은 넣지 않음(기존 메시지만 사용).
    - (tests, 메모 2) `tests/test_summarize_run.py`에 추가:
      ① 기존 `article_tags`(태그 `old`)가 연결된 failed 글을 `retry_failed=True`로 재요약(새 태그 `new`) → 해당 글의 연결이 `new`만 남음
      (summarize_run.py의 article_tags DELETE를 지우면 실패해야 함). ② `attempts=5`인 failed 글이 재요약에 성공한 뒤 `attempts == 5`, `status='done'`.
      ③ `test_store_failure_rolls_back_and_raises_database_error`의 쓰지 않는 `monkeypatch` 인자 제거.
      ④ `url` 키 없는 dict(`{"id", "title", "content"}`)로 실패 경로 → 예외 없이 `SummarizeOutcome(ok=False)`, caplog에 글 id 포함.
      ⑤ transient 1회 후 성공 시 caplog(`rss_wiki.summarize_run`, DEBUG)에 재시도 레코드 1건, 성공 시 INFO 레코드에 글 id 포함.
    - (deps, 메모 3) `uv add --dev httpx2`로 `tests/test_claude.py`가 직접 import하는 패키지를 dev 의존성에 선언 (자체 결정: 테스트 코드 변경 없이 가장 단순).
      runtime 의존성은 바꾸지 않음. 버전 제약은 uv 기본값(현재 lock 버전과 호환)을 따름.
  - touch: `src/rss_wiki/summarize_run.py`, `tests/test_summarize_run.py`, `pyproject.toml`, `uv.lock`
  - acceptance:
    - `uv run pytest tests/test_summarize_run.py` 통과 (기존 14건 + 신규 ①②④⑤ 4건 = 18건)
    - `uv run pytest tests/test_claude.py` 통과 (17건)
    - `pyproject.toml`의 dev 의존성 그룹에 `httpx2`가 있음
    - `uv run pytest` 전체 통과 (T10 이후 176건 회귀 없음, 180건)

- [x] T10a. `summarize` CLI 명령 + T10b REVIEW 메모 1~3
  - 결과: REVIEW PASS 11/12 (2026-10-31). 메모 1·2는 T10c, 메모 3(탭·개행 출력 정규화)은 T14 메모, 메모 4(환경)는 참고로만 둠.
  - 메모(Planner): T10 REVIEW 메모 5에 따라 `--limit` 양의 정수 검증은 argparse `type` 함수로 처리(음수가 `LIMIT -1`로 새지 않게).
    T10b REVIEW 메모 3의 전제("기본 로그 레벨 WARNING")는 실제와 다름: cli.py `_setup_logging`의 기본은 PRD 8장대로 **INFO**(stderr)이며 바꾸지 않음.
    로그는 stderr, 결과 줄은 stdout이라 스트림이 분리되므로, stdout에 로그 문구가 섞이지 않는지와 `--quiet`에서 INFO가 숨는지만 테스트로 고정함 (자체 결정).
  - 부수 작업(tests만, T10b REVIEW 메모 1·2): `src/rss_wiki/summarize_run.py`는 수정하지 않음.
    - `test_failure_without_url_key_does_not_crash`를 parametrize해 url 키 없는 dict와 `SELECT id, title, content`로 조회한 `sqlite3.Row` 두 경우를 모두 검사하고,
      레코드 레벨이 WARNING이며 메시지에 `id=…`와 대체값 `, -)`(실제 문구에 맞출 것)가 들어 있음을 단언.
    - `test_retry_and_success_are_logged`에 재시도 DEBUG 레코드 메시지에 `1/3`과 원인(`HTTP 429` 등 테스트가 던진 메시지), INFO 레코드에 태그(`python` 등 가짜 결과의 태그)가 포함됨을 단언.
    실제 문구가 다르면 실제 동작에 맞춰 단언하고 IMPL.md에 기록. `src/` 수정 없이 통과하지 않으면 BLOCKED로 기록.
  - 내용: cli.py에 `summarize [--limit N] [--retry-failed]` 등록. `--limit`은 양의 정수만(0·음수는 argparse 오류 → 2).
    - 모듈 함수 `make_summarizer(config) -> Summarizer`(기본은 `create_claude_summarizer(config)`)로 만들고 테스트는 monkeypatch로 가짜를 주입(`make_http_client`와 같은 방식).
    - 순서: `connect`+`init_schema` → `make_summarizer`(API 키 없으면 `ConfigError` → 종료 코드 2, 대상 유무와 무관하게 먼저 확인, 자체 결정) →
      `summarize_pending(..., max_retries=config.max_retries, max_failures=config.max_failures)`.
    - 출력(stdout): 글마다 `<article id>\t<제목 또는 ->\t완료|실패: <원인>` 한 줄, 마지막에 `합계: 완료 N건, 실패 M건`. 대상이 없으면 "요약할 글이 없습니다"와 0.
      실패가 하나라도 있으면 종료 코드 1, `DatabaseError`는 2(기존 매핑).
  - touch: `src/rss_wiki/cli.py`, `tests/test_summarize_cmd.py`(신규), `tests/test_summarize_run.py`(단언·parametrize만)
  - acceptance:
    - `uv run rss-wiki summarize --help` 종료 코드 0
    - `uv run pytest tests/test_summarize_cmd.py` 통과 (가짜 Summarizer, 네트워크·API 키 없음):
      전부 성공 → 0, 일부 실패 → 1, 대상 없음 → 0과 안내 문구, `make_summarizer`를 원래 함수로 두고 `ANTHROPIC_API_KEY` 제거(monkeypatch.delenv) → 2이고 stderr에 `ANTHROPIC_API_KEY` 포함·`Traceback` 미포함,
      `--limit 1` → 1건만 처리, `--limit 0` → 2, `--limit -1` → 2, failed 글은 기본 실행에서 제외되고 `--retry-failed`로 처리됨,
      성공 실행의 stdout 줄이 결과 줄과 합계 줄뿐이고 `요약 완료` 로그 문구는 stdout에 없음(기본 실행에서는 stderr에 있음), `--quiet` 실행 시 stderr에 `요약 완료` 없음
    - `uv run pytest tests/test_summarize_run.py` 통과 (19건: 기존 18건 + url 없는 `sqlite3.Row` parametrize 1건)
    - `uv run pytest` 전체 통과 (T10b 이후 180건 회귀 없음)

- [x] T10c. summarize 결과 즉시 출력·anthropic 지연 import (T10a REVIEW 메모 1·2)
  - 결과: REVIEW PASS 12/12 (2026-10-31). 메모 1(trafilatura 지연 import, 선택)은 T14 메모, 메모 2(콜백 출력 실패 정책)는 T13 메모, 메모 3은 T14 메모 유지.
  - 메모(Planner): 메모 2의 방식은 `summarize_pending`에 콜백 인자를 추가하는 쪽으로 정함 (자체 결정: 대상 선정·태그 목록 관리를 summarize_run에 그대로 두고
    CLI 변경이 가장 작음. 기본값 None이라 기존 호출과 테스트가 그대로 동작). DatabaseError 방침은 T6b(fetch)와 같음: 이미 처리한 항목의 줄은 남기고 합계 줄 없이 종료 코드 2.
    T13 `run`도 같은 방침을 따름.
  - 내용:
    - (src, summarize_run.py) `summarize_pending(..., on_outcome: Callable[[sqlite3.Row, SummarizeOutcome], None] | None = None)`.
      글 하나를 처리할 때마다(다음 글로 넘어가기 전) `on_outcome(article_row, outcome)`을 호출. 반환값(list)은 그대로 유지. 그 외 동작은 바꾸지 않음.
    - (src, cli.py, 메모 2) `cmd_summarize`가 `on_outcome` 콜백에서 결과 줄 `<id>\t<제목|->\t완료|실패: …`을 바로 print(`flush=True`)하고,
      제목은 콜백이 받은 행의 `title`을 씀. cli.py:171의 사전 `select_targets` 호출과 `titles` 맵을 제거하고, "요약할 글이 없습니다"는
      `summarize_pending`이 빈 목록을 돌려줄 때 출력. 합계 줄·종료 코드 규칙은 그대로.
      (`make_summarizer`는 계속 대상 확인보다 먼저 호출해 키 없음 → 2 순서를 유지.)
    - (src, cli.py, 메모 1) 모듈 최상단의 `from rss_wiki.claude import create_claude_summarizer`를 제거하고 `make_summarizer` 함수 안에서 import.
      `rss_wiki.summarize`의 `Summarizer` 타입 import는 그대로 둠(anthropic 비의존인지 확인할 것).
    - (tests) `tests/test_summarize_cmd.py`에 추가:
      - 2건 대상 중 2번째 글 저장 단계에서 `sqlite3.OperationalError`가 나게(monkeypatch로 `rss_wiki.summarize_run._store_success`를 2번째 호출에서 던지게) →
        `main([... "summarize"])` 종료 코드 2, stdout에 1번 글의 `완료` 줄이 있고 `합계:` 줄은 없음, stderr에 `요약 저장 실패` 포함·`Traceback` 미포함
      - 새 프로세스(`subprocess.run([sys.executable, "-c", "import sys, rss_wiki.cli; print('anthropic' in sys.modules)"])`)의 출력이 `False`
      - `--limit abc` → 2 (T10a REVIEW 테스트 공백)
    - (tests) `tests/test_summarize_run.py`에 `on_outcome` 콜백이 글마다 1회, id 순서로 `(행, outcome)`을 받는지 단언 1건 추가.
  - touch: `src/rss_wiki/cli.py`, `src/rss_wiki/summarize_run.py`(`summarize_pending` 콜백 인자만), `tests/test_summarize_cmd.py`, `tests/test_summarize_run.py`
  - acceptance:
    - `uv run pytest tests/test_summarize_cmd.py` 통과 (기존 11건 + 신규 3건 = 14건)
    - `uv run pytest tests/test_summarize_run.py` 통과 (기존 19건 + 신규 1건 = 20건)
    - `uv run python -c "import sys, rss_wiki.cli; print('anthropic' in sys.modules)"`가 `False` 출력
    - `uv run pytest` 전체 통과 (T10a 이후 192건 회귀 없음, 196건)

## M4. 위키 빌드
- [x] T11. 글별 요약 Markdown 렌더링·쓰기 (`wiki.py`, CLI 연동은 T12)
  - 결과: REVIEW PASS 10/12 (2026-10-31). 메모 1~4는 T11a, 메모 5는 T12 사양에 반영.
  - 메모(Planner): 결과물은 DB에서 매번 재생성하는 파생 파일이라 경로·형식 결정은 되돌리기 쉬움(HALT 대상 아님). 아래 결정은 모두 (자체 결정).
  - 내용: 신규 `rss_wiki/wiki.py`(LLM·HTTP 비의존, DB는 조회만). 새 의존성 없음(YAML 라이브러리 미사용).
    `rss_wiki.fetch`·`extract`·`claude`를 import하지 않음(T10c REVIEW 메모 1의 시작 시간 방침과 일치, `db` 정도만 사용).
    - `slugify(title: str | None, article_id: int) -> str`: NFKC 정규화·소문자화 후 유니코드 단어 문자(`\w`, 한국어 포함)가 아닌 연속 문자를 `-` 하나로 바꾸고
      앞뒤 `-` 제거, 최대 60자로 자른 뒤 다시 끝 `-` 제거, 비면 `article`. 결과 끝에 `-{article_id}`를 붙여 유일성 보장 (자체 결정: 같은 제목 충돌 방지, 결정적).
      Windows 예약 문자(`<>:"/\|?*`)는 `\w`가 아니므로 자연히 제거됨.
    - `article_relpath(row) -> PurePosixPath`: `articles/YYYY/MM/<slug>.md`. 연·월은 `published_at`의 앞 7자(`YYYY-MM`), 없거나 형식이 다르면 `fetched_at` 기준 (자체 결정).
    - `render_article(row, tags: list[str]) -> str`: front matter(`---`로 감싼 YAML)와 본문.
      - 키 순서 고정: `title`, `url`, `feed`, `published`, `summarized`, `model`, `tags`. 문자열 값은 `json.dumps(value, ensure_ascii=False)`로 큰따옴표 인용
        (JSON 문자열은 유효한 YAML이라 콜론·따옴표·개행이 안전, 자체 결정). 값이 없으면 `null`. `tags`는 정렬한 `["a", "b"]` 형태(JSON 배열).
        `feed`는 피드 이름(고아 글처럼 없으면 `null`).
      - 본문: `# <제목 또는 (제목 없음)>`, 빈 줄, `## TL;DR`, tldr, `## 핵심 포인트`, `- ` 목록(key_points JSON 순서), `## 원문`, `[<url>](<url>)`. 파일 끝은 개행 1개.
    - `load_done_articles(conn) -> list[sqlite3.Row]`: `summaries.status='done'`인 글을 articles·feeds(LEFT JOIN)와 묶어 id 오름차순으로 조회
      (`id, title, url, published_at, fetched_at, feed_name, tldr, key_points, model, summarized_at`). 태그는 글별로 `article_tags`·`tags`에서 정렬해 가져오는 헬퍼 제공.
    - `write_articles(conn, wiki_dir: Path) -> list[Path]`: done 글마다 파일을 `encoding="utf-8", newline="\n"`로 씀(OS와 무관하게 바이트 동일). 내용이 같으면 다시 쓰지 않아도 됨(선택).
      쓴(또는 유지한) 파일 경로 목록을 id 순으로 반환. pending·failed 글은 쓰지 않음. 오래된 파일 정리·주제 페이지·인덱스·`build` CLI는 T12 몫.
  - touch: `src/rss_wiki/wiki.py`(신규), `tests/test_wiki_articles.py`(신규)
  - acceptance:
    - `uv run pytest tests/test_wiki_articles.py` 통과 (tmp DB에 feeds·articles·summaries·tags를 직접 INSERT, 네트워크·LLM 없음):
      - `slugify("Hello, World!", 3) == "hello-world-3"`, `slugify("파이썬 3.14 출시", 7) == "파이썬-3-14-출시-7"`, `slugify(None, 5) == "article-5"`, `slugify("???", 2) == "article-2"`,
        200자 제목 → `-{id}` 앞 부분이 60자 이하
      - `published_at="2026-09-15T00:00:00Z"` → `articles/2026/09/...`, `published_at` 없음 → `fetched_at`의 연·월
      - `render_article` 결과가 `---`로 시작하고 7개 키가 고정 순서로 있으며, 제목에 `: "따옴표"`가 있어도 front matter 줄이 `json.loads`로 원래 값이 됨,
        tags가 정렬됨, 본문에 TL;DR·핵심 포인트 목록(한국어 그대로)·원문 링크가 있음, 고아 글은 `feed: null`
      - `write_articles` → done 글만 파일 생성(pending·failed 글은 없음), 파일이 UTF-8이고 `\r\n`이 없음, 두 번 실행해도 바이트 동일, 반환 목록이 id 순
    - `uv run pytest` 전체 통과 (T10c 이후 196건 회귀 없음)
- [x] T11a. 글별 Markdown 텍스트 정규화·링크 안전화·테스트 보강 (T11 REVIEW 메모 1~4)
  - 결과: Generator 완료(IMPL 보고 전체 209건 통과), 별도 REVIEW 없음(REVIEW.md는 T11 대상). wiki.py에 `one_line`·`_source_link`·`articles/unknown/` 폴백 확인(Planner 코드 대조).
    T11a에 대한 지적은 T12 REVIEW에서 함께 받음.
  - 메모(Planner): 결과물은 DB에서 재생성하는 파생 파일이라 아래 결정은 모두 되돌리기 쉬움 (자체 결정). front matter 값은 JSON 인용이라 원문(개행 포함)을 그대로 보존하고, 정규화는 Markdown 본문에만 적용함.
  - 내용 (`src/rss_wiki/wiki.py`):
    - 헬퍼 `one_line(text: str | None) -> str`: `" ".join(text.split())`(모든 공백·CR·LF를 공백 하나로, 앞뒤 제거, None → `""`). T12 주제 페이지·인덱스에서도 재사용.
    - 본문 제목 `# …`은 `one_line(title)`(비면 `(제목 없음)`), 각 key_point는 `one_line(point)`(빈 결과는 목록에서 뺌).
      tldr은 `\r\n`·`\r`을 `\n`으로 바꾸고 앞뒤 공백 제거(문단 구분은 유지). 결과적으로 파일에 `\r`이 입력과 무관하게 없어야 함.
    - 원문 링크(메모 2): `[<텍스트>](<<목적지>>)` 꼴(CommonMark 꺾쇠 목적지). 목적지는 url에서 `<`→`%3C`, `>`→`%3E`, 공백 문자(개행 포함)→`%20`.
      링크 텍스트는 `one_line(url)`에서 `\`·`[`·`]`를 백슬래시 이스케이프. url이 None이면 `## 원문` 아래에 `-` 한 줄.
    - (메모 4) `article_relpath`: `fetched_at`도 `^\d{4}-\d{2}$`를 통과하지 못하면 `articles/unknown/<slug>.md`.
    - `slugify`·front matter 형식·`write_articles`의 쓰기 방식은 바꾸지 않음.
  - touch: `src/rss_wiki/wiki.py`, `tests/test_wiki_articles.py`
  - acceptance:
    - `uv run pytest tests/test_wiki_articles.py` 통과, 아래 신규 테스트 포함 (tmp DB 직접 INSERT, 네트워크·LLM 없음):
      - 제목 `"line1\nline2"` → 본문에 `# line1 line2` 한 줄, front matter `title`을 `json.loads`하면 원래 개행 포함 값
      - tldr `"a\r\nb\rc"`·key_point `"x\r\ny"` → 렌더 결과·`write_articles` 파일 바이트에 `\r` 없음, 핵심 포인트 줄이 `- x y`
      - url `https://e.com/a_(b) c` → 링크 줄이 정확히 `[https://e.com/a_(b) c](<https://e.com/a_(b)%20c>)`. url `https://e.com/[x]` → 텍스트가 `\[x\]`로 이스케이프됨. url None → 예외 없이 `-`
      - `published_at`·`fetched_at` 모두 형식 불일치(`"garbage"`) → `articles/unknown/…md`, `published_at="Mon, 01 Sep"` → `fetched_at` 연·월
      - (메모 3) `write_articles` 결과 파일의 front matter `tags`가 DB `article_tags`의 태그를 정렬한 배열과 같음(태그 2개 이상, INSERT 순서와 정렬 순서가 다르게)
      - (메모 3) `key_points` NULL → `## 핵심 포인트` 아래 목록 없음·예외 없음, 제목 NULL → `# (제목 없음)`
      - (메모 3) 두 번째 `write_articles` 호출 후 모든 파일의 `stat().st_mtime_ns`가 첫 호출 직후와 같음
    - `uv run pytest` 전체 통과 (T11 이후 202건 회귀 없음)

- [x] T12. 주제 페이지·인덱스·오래된 파일 정리와 `build` CLI (T11 REVIEW 메모 5, M4 완료 기준)
  - 결과: REVIEW PASS 11/12 (2026-10-31, 전체 217건). M4 완료 기준(두 번 build 바이트·mtime 동일) 확인. 메모 1·4는 T12a, 메모 2는 T14(README), 메모 3은 T13, 메모 5는 PLAN 참고로 이관.
  - 메모(Planner): 아래 결정은 모두 파생 파일 형식이라 되돌리기 쉬움 (자체 결정). T11a의 `one_line`을 재사용하므로 T11a 다음에 진행.
    `write_articles`·`load_article_tags`는 `sqlite3.Error`를 감싸지 않으므로 `build_wiki` 쪽에서 조회 단계 전체를 감쌀 것(wiki.py는 `rss_wiki.db`의 `DatabaseError`만 추가 import).
    주제 페이지·인덱스 줄의 TL;DR은 반드시 `one_line(tldr)`로 한 줄화(T11a의 tldr은 문단 구분을 유지하므로 그대로 쓰면 목록이 깨짐).
  - 내용:
    - (src, wiki.py) `topic_filenames(tags: list[str]) -> dict[str, str]`: 태그 → `<파일명>.md`. 파일명은 NFKC·`\W+`→`-`·strip(`slugify`와 같은 규칙, 60자 상한, id 접미 없음),
      비면 `tag`. 결과가 다른 태그와 겹치거나 Windows 예약 이름(`con`, `prn`, `aux`, `nul`, `com1`~`com9`, `lpt1`~`lpt9`)이면 태그 이름 오름차순으로 처리하며
      두 번째부터 `-2`, `-3`…을 붙임(예약 이름은 처음부터 `-2`). 결정적.
    - 글 정렬 키(최신순): `published_at`(없으면 `fetched_at`) 내림차순, 같으면 id 내림차순.
    - `render_topic(tag, entries) -> str`: `# <태그>`, 빈 줄, `글 N건`, 빈 줄, 글마다 `- [<one_line 제목, [] 이스케이프>](<../articles/…md>) — <one_line(tldr)>` (최신순, TL;DR 한 줄 포함, PRD 4.4). 끝 개행 1개.
    - `render_index(tag_counts, recent) -> str`: `# rss-wiki`, `## 태그` 아래 `- [<태그>](<topics/…md>) (N)`(글 수 내림차순, 같으면 이름 오름차순),
      `## 최근 요약` 아래 최신 20건(상수 `RECENT_LIMIT = 20`)을 주제 페이지와 같은 줄 형식(링크는 `articles/…`). 생성 시각 등 비결정적 값은 넣지 않음.
      done 글이 없으면 각 섹션에 `(없음)`.
    - 태그는 done 글에 연결된 것만 대상(글 0건인 태그는 페이지·인덱스에서 제외).
    - `BuildResult` 데이터클래스: `articles: int`, `topics: int`, `removed: int`.
      `build_wiki(conn, wiki_dir: Path) -> BuildResult`: `write_articles` → 주제 페이지 → `index.md`(모두 내용이 같으면 다시 쓰지 않음, UTF-8·LF).
      이어서 오래된 파일 정리 (자체 결정): `wiki/articles/`·`wiki/topics/` 아래의 `.md` 중 이번에 만든 집합에 없는 것을 삭제하고, `articles/` 아래 빈 디렉터리를 제거.
      `.md`가 아닌 파일과 `wiki/` 바로 아래의 `index.md` 외 파일은 건드리지 않음. DB 조회 중 `sqlite3.Error` → `DatabaseError(f"위키 조회 실패: {exc}") from exc`.
    - (src, cli.py) `build` 서브커맨드: `connect`+`init_schema` → `build_wiki(conn, config.wiki_dir)` → stdout `글 N건, 주제 M건, 정리 K건` 후 0.
      `DatabaseError` → 2(기존 매핑). 파일 쓰기 `OSError` → stderr에 경로 포함 메시지·Traceback 없이 2 (자체 결정: 출력 디렉터리 문제는 항목 단위가 아니라 설정 오류 범주).
  - touch: `src/rss_wiki/wiki.py`, `src/rss_wiki/cli.py`, `tests/test_wiki_build.py`(신규)
  - acceptance:
    - `uv run rss-wiki build --help` 종료 코드 0
    - `uv run pytest tests/test_wiki_build.py` 통과 (tmp DB 직접 INSERT, 네트워크·LLM 없음):
      - done 글 3건(태그 `python` 2건·`ai` 1건, 발행일 서로 다름)과 pending 글 1건 → `topics/python.md`에 2건이 최신순, 각 줄에 TL;DR, 링크가 실제 글 파일을 가리킴(경로를 풀어 `is_file()`), pending 글 태그만 가진 태그 페이지 없음
      - `index.md`에 `python`(2)·`ai`(1)이 그 순서로 있고 최근 요약 목록이 최신순
      - 같은 DB로 `build_wiki` 두 번 → `wiki/` 전체 트리(상대 경로 → 바이트 사전)가 같고 mtime도 그대로 (M4 완료 기준)
      - 글 하나의 summaries를 `pending`으로 바꾸고 다시 build → 그 글 파일과 글 0건이 된 주제 페이지가 삭제되고 `removed`에 반영, 빈 월 디렉터리 제거, `wiki/notes.txt`(테스트가 만든 비 md 파일)는 유지
      - 태그 `c++`와 `c`가 함께 있으면 파일명이 겹치지 않음(`c.md`, `c-2.md` 등 결정적), 태그 `con` → `con-2.md`
      - CLI `main(["--data-dir", tmp, "build"])` → 0이고 stdout에 `글 3건`; `wiki` 경로가 일반 파일이면 2·stderr에 경로 포함·`Traceback` 없음
    - `uv run pytest` 전체 통과 (T11a 이후 209건 회귀 없음)

- [x] T12a. 위키 빌드 테스트 보강과 중복 코드 정리 (T12 REVIEW 메모 1·4)
  - 결과: REVIEW PASS 12/12 (2026-10-31, 전체 219건). build_wiki의 글 조회 1회 확인. 메모 1(test_wiki_build.py:149 SyntaxWarning)은 T13 부수 작업, 메모 2(`write_articles` 공개 유지 여부)는 T14 메모로 이관.
  - 내용:
    - (tests, 메모 1) `tests/test_wiki_build.py`:
      - `seed`를 acceptance대로 `python` 2건·`ai` 1건이 되게 처음부터 맞춤(예: 글 1 `python`, 글 2 `python`, 글 3 `ai`. 구성은 Generator 재량이되 정리 테스트가 "글 0건이 된 주제 페이지 삭제"를 계속 검증해야 함).
        42-44행의 사후 DELETE와 의도·실제가 섞인 주석을 없애고, 주석은 실제 데이터와 일치시킬 것. `test_topic_and_index`·`test_prune_stale`의 기대값을 새 seed에 맞춤.
      - 72행 `"(3)" in index and "(1)" in index`를 줄 단위 단언(`"- [python](<topics/python.md>) (2)" in index.splitlines()` 형태, 실제 형식에 맞출 것)으로 교체, `ai` 줄도 같은 방식.
      - 95-97행의 `or` 단언을 삭제하거나 "삭제된 글의 파일이 없음"을 직접 확인하는 단언으로 교체.
      - 신규: 스키마 없는 연결(`sqlite3.connect(tmp_path / "empty.db")`, row_factory는 `connect`와 같게 하거나 `rss_wiki.db.connect`로 열고 init_schema 생략)로 `build_wiki` →
        `DatabaseError`, `isinstance(exc.value.__cause__, sqlite3.Error)`, 메시지에 `위키 조회 실패` 포함.
      - 신규: done 글 21건 → `index.md`의 `## 최근 요약` 아래 목록 줄이 정확히 20건이고 가장 오래된 1건이 빠짐, 각 링크가 `articles/`로 시작하며 풀었을 때 `is_file()`.
    - (src, 메모 4, 동작 불변) `wiki.py`의 `write_articles` 쓰기 블록(137-140)을 `_write_if_changed`로 교체하고,
      `build_wiki`가 done 글을 두 번 조회하지 않게 함(예: `write_articles`가 조회한 행을 받는 내부 헬퍼로 분리, 공개 시그니처 `write_articles(conn, wiki_dir)`·`build_wiki(conn, wiki_dir)`는 유지).
      `test_wiki_articles.py`·`test_wiki_build.py`의 기존 단언(mtime 유지 포함)이 그대로 통과해야 함.
  - touch: `src/rss_wiki/wiki.py`, `tests/test_wiki_build.py`
  - acceptance:
    - `uv run pytest tests/test_wiki_build.py` 통과 (신규 2건 포함, 10건)
    - `uv run pytest tests/test_wiki_articles.py` 통과 (회귀 없음)
    - `uv run pytest` 전체 통과 (T12 이후 217건 회귀 없음, 219건)

## M5. 통합과 마감
- [x] T13. `run` 명령과 출력 실패 정책
  - 결과: Generator 완료(IMPL 보고 전체 230건, test_run_cmd 11건, SyntaxWarning 제거), 별도 REVIEW 없음(REVIEW.md는 T12a 대상).
    Planner 코드 대조: cli.py에 `_do_fetch`(143)·`_do_summarize`(161)·`cmd_run`(224)·`main`의 `BrokenPipeError` 처리(273) 확인. T13에 대한 지적은 T13b REVIEW에서 함께 받음.
  - 메모(Planner): 아래 결정은 모두 CLI 동작이라 되돌리기 쉬움 (자체 결정). `status`는 T13b로 분리.
  - 내용 (`src/rss_wiki/cli.py`):
    - 리팩터링(동작 불변): `cmd_fetch`의 피드 루프·출력·합계를 `_do_fetch(conn, config, feed_id) -> int`(실패 피드 수, 없는 id면 `FeedError` 전파),
      `cmd_summarize`의 본문을 `_do_summarize(conn, config, summarizer, limit, retry_failed) -> int`(실패 글 수)로 뽑아 `cmd_fetch`·`cmd_summarize`·`cmd_run`이 공유.
      fetch·summarize의 기존 출력 문구와 종료 코드는 바꾸지 않음(기존 테스트가 그대로 통과).
    - `run` 서브커맨드(옵션 없음, PRD 3장): `connect`+`init_schema` → `make_summarizer(config)`를 **가장 먼저** 호출(API 키 없으면 아무것도 수집하지 않고 2, 자체 결정: 스케줄러 실행에서 수집만 되고 요약이 밀리는 상태를 피함)
      → `[fetch]` 머리줄 후 `_do_fetch`(등록 피드가 없으면 안내 줄만 출력하고 계속 진행) → `[summarize]` 머리줄 후 `_do_summarize`(`limit=None`, `retry_failed=False`)
      → `[build]` 머리줄 후 `build_wiki` 결과 줄. 실패 피드나 실패 글이 하나라도 있으면 1, 아니면 0.
    - 치명 오류 (T6b REVIEW 메모 4): 어느 단계든 `DatabaseError`가 나면 다음 단계로 넘어가지 않고 2(기존 `main` 매핑, 이미 출력한 줄은 남음).
    - build 단계 `OSError` (T12 REVIEW 메모 3): stderr에 `오류: 위키 빌드 실패(일부 파일만 갱신됐을 수 있음, 다음 build에서 회복): <원인>` 후 2. 원인에 경로가 포함되어야 함.
    - 출력 실패 정책 (T10c REVIEW 메모 2): `main`에서 `BrokenPipeError`를 잡아 Traceback 없이 종료 코드 1을 반환(모든 명령 공통, 자체 결정: 데이터는 이미 커밋됐고 출력만 잃었으므로 부분 실패 범주).
    - 부수 작업(tests, T12a REVIEW 메모 1): `tests/test_wiki_build.py:149`의 `"- [a \[b\] c](<../articles/"`를 raw 문자열 `r"- [a \[b\] c](<../articles/"`로 바꿔
      SyntaxWarning을 없앰(단언 의미 불변). 이 파일의 다른 줄은 건드리지 않음.
  - touch: `src/rss_wiki/cli.py`, `tests/test_run_cmd.py`(신규), `tests/test_wiki_build.py`(149행 raw 문자열화만)
  - acceptance:
    - `uv run rss-wiki run --help` 종료 코드 0
    - `uv run pytest tests/test_run_cmd.py` 통과 (`make_http_client`·`make_summarizer`를 monkeypatch, MockTransport·가짜 Summarizer, 네트워크·LLM 없음):
      - 피드 1개(rss2.xml, 원문 URL은 404 또는 `min_content_chars=0` 설정) → `run` 0, articles·summaries(done) 생성, `wiki/index.md` 존재, stdout에 `[fetch]`·`[summarize]`·`[build]`가 그 순서로 있음
      - 같은 DB로 `run` 두 번 → 두 번째도 0, articles 행 수 그대로, wiki 트리 바이트 동일
      - 피드 하나 503 지속(sleep 스텁)·다른 피드 정상 → 1이고 정상 피드 글은 요약·위키에 반영됨
      - 가짜 Summarizer가 한 글에서 비일시 오류 → 1, 나머지 글은 done
      - `make_summarizer`가 `ConfigError` → 2, HTTP 요청 0회, articles 0건
      - `rss_wiki.cli.build_wiki`(또는 fetch 단계 함수)가 `DatabaseError`를 던지게 하면 2·stderr에 메시지·`Traceback` 미포함; fetch 단계에서 던지면 stdout에 `[summarize]`가 없음
      - `wiki` 경로가 일반 파일 → 2, stderr에 `위키 빌드 실패`와 경로 포함, `Traceback` 미포함
      - `--verbose run` → stderr에 `HTTP Request:` 없음 (T3a REVIEW 메모 4)
      - `on_outcome` 출력 중 `BrokenPipeError`(예: `builtins.print`를 summarize 결과 줄에서 던지게 monkeypatch) → 종료 코드 1, `Traceback` 미포함, 해당 글은 done으로 커밋됨
    - `uv run pytest tests/test_fetch.py tests/test_summarize_cmd.py` 통과 (리팩터링 회귀 없음)
    - `uv run python -W error::SyntaxWarning -m pytest tests/test_wiki_build.py` 통과 (10건, SyntaxWarning 없음)
    - `uv run pytest` 전체 통과 (T12a 이후 219건 회귀 없음)

- [x] T13b. `status` 명령
  - 메모(Planner): 출력 형식은 사람이 읽는 텍스트이고 파생 정보라 되돌리기 쉬움 (자체 결정). DB 스키마·다른 명령은 바꾸지 않음.
  - 내용:
    - (src, 신규 `rss_wiki/status.py`, DB 조회만, HTTP·LLM 비의존) `StatusCounts` 데이터클래스와 `collect_status(conn) -> StatusCounts`.
      - `feeds`: 등록 피드 수, `feeds_error`: `last_status LIKE 'error:%'`인 피드 수, `feeds_never`: `last_fetched_at IS NULL`인 피드 수
      - `articles`: 전체 글 수(고아 글 포함)
      - `pending`: summaries 행이 없거나 `status='pending'`인 글 수 (summarize_run의 기본 대상 선정과 같은 조건, summarize_run.py:58-59)
      - `pending_retrying`: 그중 `status='pending' AND attempts > 0`(실패 후 다음 실행 재시도 대기)인 글 수
      - `done`, `failed`: 해당 status 글 수
      - 조회 중 `sqlite3.Error` → `DatabaseError(f"상태 조회 실패: {exc}") from exc`.
    - (src, cli.py) `status` 서브커맨드(옵션 없음, help "수집/요약 대기·실패 건수 요약"): `connect`+`init_schema`(init 전에도 동작, 기존 명령과 같은 방침) → `collect_status` → stdout에 아래 4줄 후 0.
      ```
      피드: N개 (오류 E, 미수집 U)
      글: N건
      요약: 완료 D, 대기 P (재시도 대기 R), 실패 F
      ```
      실패 F가 1 이상이면 마지막 줄 `실패 글은 summarize --retry-failed로 다시 시도할 수 있습니다`를 추가(없으면 3줄). 종료 코드는 상태와 무관하게 0(조회 성공 = 명령 성공, 자체 결정).
      `DatabaseError` → 2(기존 `main` 매핑).
  - touch: `src/rss_wiki/status.py`(신규), `src/rss_wiki/cli.py`, `tests/test_status_cmd.py`(신규)
  - acceptance:
    - `uv run rss-wiki status --help` 종료 코드 0
    - `uv run pytest tests/test_status_cmd.py` 통과 (tmp DB 직접 INSERT, 네트워크·LLM 없음):
      - 빈 DB(`init` 전) → 0, stdout 첫 줄 `피드: 0개 (오류 0, 미수집 0)`, `요약: 완료 0, 대기 0 (재시도 대기 0), 실패 0`, 안내 줄 없음
      - 피드 3개(ok 1·`error: x` 1·미수집 1), 글 6건(summaries 없음 1·pending attempts 0 1·pending attempts 2 1·done 2·failed 1, 고아 글 1건 포함)
        → `collect_status` 각 필드 값이 정확하고, stdout이 위 형식과 줄 단위로 정확히 일치, 안내 줄 있음
      - `collect_status`의 `pending` 값이 `summarize_run.select_targets`의 결과 건수와 같음(같은 DB에서 `retry_failed=False`, limit 없음)
      - 스키마 없는 연결로 `collect_status` → `DatabaseError`, 메시지에 `상태 조회 실패`, `__cause__`가 `sqlite3.Error`
      - 표준 출력에 로그 줄이 섞이지 않음(stderr로만)
    - `uv run pytest` 전체 통과 (T13 이후 230건 회귀 없음)
  - 결과: REVIEW PASS 11/12 (2026-11-02, 전체 235건). T13 acceptance 재실행 회귀 없음. 메모 1~3(tests)은 T13c, 메모 4(README에 status 예시·종료 코드 0 방침)는 T14로 이관.

- [x] T13c. status 테스트 보강 (T13b REVIEW 메모 1~3, tests만 수정)
  - 내용: `src/` 아래는 수정하지 않음. `tests/test_status_cmd.py`만 고침.
    - (메모 1) `test_logs_not_on_stdout`(87-90행)을 실제로 로그가 발생하는 조건으로 바꿈: `monkeypatch`로 `rss_wiki.cli.collect_status`를
      원래 함수를 감싼 함수로 바꾸고, 그 안에서 `logging.getLogger("rss_wiki").info("상태-로그")`를 남긴 뒤 원래 함수 결과를 돌려줌.
      `main([... "status"])`(기본 INFO 수준) → 0, `capsys`로 stdout에 `상태-로그`가 없고 stderr에는 있음을 단언.
    - (메모 2) `test_empty_db_before_init`(50-55행)를 stdout 줄 목록 전체 비교로 바꿈:
      `["피드: 0개 (오류 0, 미수집 0)", "글: 0건", "요약: 완료 0, 대기 0 (재시도 대기 0), 실패 0"]`.
    - (메모 3) 신규 1건: tmp_path의 `data/rss-wiki.db`에 임의 바이트(SQLite가 아닌 파일)를 쓰고 `main([... "status"])` → 2,
      stderr에 `오류:` 포함·`Traceback` 미포함, stdout 비어 있음.
    테스트가 `src/` 수정 없이 통과하지 않으면 BLOCKED로 기록하고 실제 동작을 IMPL.md에 남김.
  - touch: `tests/test_status_cmd.py`
  - acceptance:
    - `uv run pytest tests/test_status_cmd.py` 통과 (6건: 기존 5건 + 손상 DB 1건)
    - `uv run pytest` 전체 통과 (T13b 이후 235건 회귀 없음, 236건)
  - 결과: REVIEW PASS 12/12 (2026-11-02, 전체 236건). src 미수정 확인. 메모 1(`--quiet status` 반대 방향 단언, 선택)은 T14 부수 작업으로 이관.

- [x] T14. README 사용법과 UTF-8 콘솔 점검
  - 메모(Planner): README는 문서, UTF-8 점검은 테스트 추가만이라 되돌리기 쉬움. 아래 남은 메모 중 선택 항목은 T14a로 분리함.
  - 내용:
    - (docs, `README.md` 현재 빈 파일) 한국어로 작성. 포함 항목:
      - 개요 1~2문장(PRD 1장), 요구 사항(Python 3.14+, uv, 환경 변수 `ANTHROPIC_API_KEY`; 설정 파일·DB에 저장하지 않음)
      - 설치·실행: `uv sync`, `uv run rss-wiki init`
      - 명령 표: `init`·`feed add/list/remove`·`fetch [--feed ID]`·`summarize [--limit N] [--retry-failed]`·`build`·`run`·`status` (PRD 3장과 같은 이름·옵션)
      - 공통 옵션 `--verbose`/`--quiet`(함께 쓸 수 없음)·`--data-dir`·`--config`, 로그는 stderr·결과는 stdout
      - 종료 코드 0/1/2 규칙과 예외: `status`는 조회에 성공하면 상태와 무관하게 0 (T13b REVIEW 메모 4), 출력 파이프가 끊기면 1
      - `status` 출력 예시(3줄 + 실패 시 안내 줄)
      - 설정 파일 `rss-wiki.toml` 키와 기본값(`default_config_toml()`·config.py 기본값과 일치: model, min_content_chars, max_input_chars, http_timeout, max_retries, max_failures, 경로)
      - 결과물 구조 `wiki/articles/YYYY/MM/<slug>.md`, `wiki/topics/<tag>.md`, `wiki/index.md`. 주제 파일명은 태그 이름순 `-N` 접미 규칙이라
        태그가 추가되면 build마다 바뀔 수 있음 (T12 REVIEW 메모 2, 접미 규칙은 바꾸지 않음, 자체 결정)
      - 실패 정책 요약(항목 격리, 실행 내 최대 3회 재시도, 누적 5회 실패 시 failed 고정, `--retry-failed`)
      - 주기 실행 예시: Windows 작업 스케줄러 또는 cron에서 `rss-wiki run` (도구 내장 스케줄러 없음, PRD 비목표)
    - (tests, 신규 `tests/test_readme.py`) README 회귀 방지:
      - `README.md`가 UTF-8로 읽히고 비어 있지 않음
      - `rss_wiki.cli.build_parser()`의 서브커맨드 이름 7개(`init`,`feed`,`fetch`,`summarize`,`build`,`run`,`status`)와 옵션
        `--retry-failed`·`--limit`·`--data-dir`·`ANTHROPIC_API_KEY`가 모두 README에 등장
      - `rss_wiki.config.default_config_toml()`을 `tomllib`로 읽은 키 이름이 모두 README에 등장 (설정 표 누락 방지)
    - (tests, UTF-8 콘솔 점검, PRD 8장) `tests/test_readme.py` 또는 `tests/test_cli_init.py`에 subprocess 테스트 1건:
      `[sys.executable, "-c", "import sys; from rss_wiki.cli import main; sys.exit(main())", "--data-dir", tmp, "status"]`를
      환경 변수 `PYTHONIOENCODING=cp949`(Windows 기본 코드 페이지 모사)로 실행 → 종료 코드 0, stdout 바이트를 UTF-8로 디코드하면 `피드: 0개`가 포함됨.
      (`main`의 `reconfigure(encoding="utf-8")`가 콘솔 인코딩과 무관하게 UTF-8로 내보냄을 고정)
    - (tests, 부수 작업, T13c REVIEW 메모 1) `tests/test_status_cmd.py`에 1건 추가: `test_logs_not_on_stdout`과 같은 방식으로
      `cli.collect_status`를 감싸 INFO `상태-로그`를 남기고 `main([... "--quiet", "status"])` → 0, stdout·stderr 모두에 `상태-로그`가 없음.
      기존 테스트는 건드리지 않음.
    - `src/` 수정은 하지 않음. 테스트가 `src/` 수정 없이 통과하지 않으면 BLOCKED로 기록하고 IMPL.md에 남김.
  - touch: `README.md`, `tests/test_readme.py`(신규), `tests/test_status_cmd.py`(테스트 1건 추가만)
  - acceptance:
    - `uv run pytest tests/test_readme.py` 통과 (README 내용 3건 + UTF-8 subprocess 1건)
    - `uv run pytest tests/test_status_cmd.py` 통과 (7건: 기존 6건 + `--quiet` 1건)
    - `uv run rss-wiki --help` 종료 코드 0
    - `uv run pytest` 전체 통과 (T13c 이후 236건 회귀 없음, 241건)
  - 결과: REVIEW PASS 10/12 (2026-11-02, 전체 241건). src 미수정 확인. 메모 1~3(cron 예시 실패, 설정 경로 기준 미기재, README 테스트 기본값·옵션 대조)은 T14b로 이관.

- [x] T14b. README 주기 실행·설정 경로 안내 수정과 README 테스트 보강 (T14 REVIEW 메모 1~3)
  - 메모(Planner): 문서와 테스트만 바꾸므로 되돌리기 쉬움. `src/` 수정 없음.
  - 내용:
    - (docs, 메모 1) `README.md` "주기 실행" 절(95-102행)을 프로젝트 밖에서도 동작하는 형태로 고침:
      - cron 예: `0 7 * * * ANTHROPIC_API_KEY=... uv run --project /path/to/rss-wiki rss-wiki --data-dir /path/to/data --quiet run`
      - Windows 작업 스케줄러 예 한 줄: 동작에 `uv`, 인수에 `run --project C:\path\to\rss-wiki rss-wiki --data-dir C:\path\to\data --quiet run` 등록,
        API 키는 사용자 환경 변수로 지정.
      - `uv run`은 현재 디렉터리에서 프로젝트를 찾으므로 `--project`를 빼면 데이터 디렉터리와 프로젝트 디렉터리가 같을 때만 동작한다는 문장 1줄.
      - 종료 코드 1(일부 실패)은 다음 실행에서 재시도된다는 점과 `status`로 확인할 수 있다는 점을 한 줄로 덧붙임 (자체 결정).
    - (docs, 메모 2) "설정 파일" 절의 표 아래에 두 줄 추가:
      - 설정 파일 안의 상대 경로(`data_dir`·`db_path`·`wiki_dir`)는 **설정 파일이 있는 디렉터리 기준**으로 풀린다 (config.py:48, 69).
      - `--data-dir`을 주면 `data_dir`을 덮어쓰고, 설정 파일에 `db_path`·`wiki_dir`을 따로 적지 않았다면 그 아래(`data/rss-wiki.db`, `wiki`)로 따라간다.
        따로 적었다면 그 값이 그대로 쓰인다 (config.py:24-28, 64-72).
    - (tests, 메모 3) `tests/test_readme.py`:
      - 신규 `test_readme_config_defaults_match`: `tomllib.loads(default_config_toml())`의 각 `(키, 값)`에 대해 README에
        `` | `키` | `값` | `` 형태가 있는지 단언(문자열 값은 큰따옴표 포함, 예: `` `"claude-haiku-5-5"` ``, 숫자는 `str(값)`).
      - `test_readme_mentions_all_commands_and_options`의 토큰 목록에 `--verbose`·`--quiet`·`--config`·`--feed`·`--name`과
        `feed add`·`feed list`·`feed remove`를 추가.
      - 25행 서브파서 탐색을 `isinstance(a, argparse._SubParsersAction)`로 바꿔 의도를 분명히 함(단언 의미 불변).
      - 신규 `test_readme_schedule_example_uses_project`: README에 `uv run --project`가 포함됨(메모 1 회귀 방지).
    - 기존 테스트 파일 중 `tests/test_readme.py` 외에는 건드리지 않음. 테스트가 `src/` 수정 없이 통과하지 않으면 BLOCKED로 기록하고 IMPL.md에 남김.
  - touch: `README.md`, `tests/test_readme.py`
  - acceptance:
    - `uv run pytest tests/test_readme.py` 통과 (6건: 기존 4건 + 기본값 대조 1건 + `--project` 1건)
    - `uv run rss-wiki --help` 종료 코드 0
    - (수동 확인, Evaluator) 프로젝트 밖 임시 디렉터리에서 README의 형태 그대로 `uv run --project <프로젝트 경로> rss-wiki --data-dir <임시 디렉터리> status` → 종료 코드 0
    - `uv run pytest` 전체 통과 (T14 이후 241건 회귀 없음, 243건)
  - 결과: REVIEW PASS 11/12 (2026-11-02, 전체 243건). src 미수정, 프로젝트 밖 `uv run --project ... status` 종료 코드 0 확인.
    메모 1(cron 줄 단위 테스트)·메모 2(README:113 문장 정확화·cron PATH의 uv 절대 경로)는 T14c로 이관.

- [x] T14a. 마감 정리 (선택, 남은 REVIEW 메모) — **범위 밖으로 닫음**
  - 결정(Planner, 2026-11-02, 자체 결정): 아래 "남은 선택 작업 후보" 3건은 이번 버전에서 구현하지 않음. 모두 PRD 요구가 아닌 출력·메시지 다듬기와
    시작 시간 최적화이며, PRD 전 요구가 코드에 대응함을 확인했으므로 최소 변경 원칙에 따라 닫음. 필요해지면 후보별로 새 항목을 만듦.
  - 결정(Planner, 자체 결정, 모두 되돌리기 쉬움):
    - (T7a REVIEW 4) 원문 GET 피드당 상한·재시도 축소: **이번 버전에서는 적용하지 않음**(PRD에 요구 없음, 설정 키 추가 없이 현행 유지가 가장 단순).
    - (T12a REVIEW 2) `wiki.write_articles`: **현 시그니처로 공개 유지**(가장 단순).
    - (T10a REVIEW 4, 환경) `VIRTUAL_ENV` 불일치 경고는 코드 결함이 아니므로 작업 항목으로 두지 않음.
  - 남은 선택 작업 후보(필요 시 한 항목씩 구체화):
    - (T10a REVIEW 3) fetch(피드 이름)·summarize(제목·실패 원인) 결과 줄의 탭·개행을 공백 하나로 정규화(두 명령에 같이 적용).
    - (T10c REVIEW 1) trafilatura 지연 import(`extract_article` 안), `'trafilatura' in sys.modules`가 False임을 subprocess 테스트로 고정.
    - (T3 REVIEW 4) `config.py` 타입 오류 메시지에 설정 파일 경로를 붙임.

- [x] T14c. README 주기 실행 문장 정확화와 cron 예 테스트 좁히기 (T14b REVIEW 메모 1·2)
  - 메모(Planner): 문서와 테스트만 바꾸므로 되돌리기 쉬움. `src/` 수정 없음. 이 항목이 PASS면 TASKS 전체가 완료되어 종료 판정 대상이 됨.
  - 내용:
    - (docs, 메모 2) `README.md` 113행 문장을 사실에 맞게 고침:
      "`uv run`은 명령을 실행하는 현재 디렉터리(또는 그 상위)에서 프로젝트를 찾습니다. cron·작업 스케줄러는 보통 홈 디렉터리 등 프로젝트 밖에서
      실행하므로 `--project`로 프로젝트 경로를 지정하세요." 취지로 바꿈(문구는 Generator 재량, "데이터 디렉터리와 프로젝트 디렉터리가 같을 때만" 표현은 제거).
    - (docs, 메모 2) 그 아래 한 줄 추가: cron 환경의 `PATH`에는 `uv`가 없을 수 있으므로 `uv`를 절대 경로(예: `/home/<user>/.local/bin/uv`, `which uv`로 확인)로
      적으라는 안내. cron 예(104행) 자체는 바꾸지 않음(자체 결정: 예는 간결하게 유지하고 안내 문장으로 보완).
    - (tests, 메모 1) `tests/test_readme.py`의 `test_readme_schedule_example_uses_project`를 cron 줄 단위로 좁힘:
      README에서 `0 7 * * *`로 시작하는 줄을 찾아(정확히 1줄 이상) 그 줄에 `uv run --project`, `--data-dir`, ` run`이 모두 들어 있음을 단언.
      Windows 예(`run --project` 로 시작하는 줄)에도 `--project`·`--data-dir`이 있음을 단언.
    - (tests) README에 "데이터 디렉터리와 프로젝트 디렉터리가 같을 때만" 문구가 없음을 단언하지는 않음(문구 고정 과잉 방지).
    - `tests/test_readme.py` 외 테스트 파일과 `src/`는 건드리지 않음. 테스트가 `src/` 수정 없이 통과하지 않으면 BLOCKED로 기록하고 IMPL.md에 남김.
  - touch: `README.md`, `tests/test_readme.py`
  - acceptance:
    - `uv run pytest tests/test_readme.py` 통과 (6건, 테스트 수 그대로, `--project` 테스트가 cron 줄·Windows 줄 단위로 단언)
    - (수동 확인, Evaluator) README의 cron 줄에서 `uv run --project`를 지우면 `test_readme_schedule_example_uses_project`가 실패함(변이 확인 후 원복)
    - `uv run rss-wiki --help` 종료 코드 0
    - `uv run pytest` 전체 통과 (T14b 이후 243건 회귀 없음, 243건)
  - 결과: REVIEW PASS 11/12. test_readme 6건·전체 243건·`--help` 0·cron 줄 변이 검출 확인(Evaluator).
  - 남은 REVIEW 메모 처리(Planner, 2026-11-02, 자체 결정): 범위 밖으로 닫음. 모두 선택 메모이며 PRD 요구가 아님. 필요해지면 새 항목으로 재개.
    - (메모 1) tests/test_readme.py:49 `" run" in ln`이 `uv run`만으로 항상 참(공허한 단언) → `ln.rstrip().endswith(" run")`으로 교체, :53 중복 `--project` 단언은 `rss-wiki` 포함 단언으로 교체.
    - (메모 2) README.md:107 Windows 작업 스케줄러 예에 `uv` 절대 경로(`where uv`) 안내 한 구절 추가.

## M6. 요약 병렬 실행 (PRD v2 4.3)

- [x] T15. 설정 `summarize.concurrency` 추가
  - 메모(Planner): PRD 4.3·6장 "요약 동시 실행 수" 반영. 설정 키 추가만이라 되돌리기 쉬움. 실행 로직(병렬화)은 T16 몫.
  - 내용:
    - (src, config.py) `Config`에 `summarize_concurrency: int = 4` 추가. TOML에서는 PRD 표기대로 테이블 `[summarize]`의 `concurrency` 키로 읽음.
      `summarize`가 테이블이 아니면 `ConfigError("summarize는 테이블이어야 합니다")`, `concurrency`가 정수가 아니거나(bool 포함) 1 미만이면
      `ConfigError("summarize.concurrency는 1 이상의 정수여야 합니다")`. 테이블 안의 다른 키는 무시(기존 최상위 키 처리와 같은 관대함).
    - `default_config_toml()` 끝에 `\n[summarize]\nconcurrency = 4\n`을 추가(테이블은 최상위 키·주석 뒤에 와야 함).
    - (docs, README.md) 설정 표에 `` | `summarize.concurrency` | `4` | 요약 LLM 호출 동시 실행 수 | `` 행 추가(설명 문구는 Generator 재량, 앞 두 칸 형식은 고정).
    - (tests, test_readme.py) `test_readme_config_defaults_match`·`test_readme_mentions_all_config_keys`가 테이블 값(dict)을 만나면
      `상위.하위` 점 표기 키로 펼쳐서 대조하도록 작은 헬퍼(`_flatten`)를 추가. 그 외 테스트는 건드리지 않음.
  - touch: `src/rss_wiki/config.py`, `tests/test_config.py`, `README.md`, `tests/test_readme.py`
  - acceptance:
    - `uv run pytest tests/test_config.py` 통과, 신규: 기본값 4, `[summarize]\nconcurrency = 2` → 2, `concurrency = 0`·`"x"`·`true` → `ConfigError`,
      `summarize = 3`(테이블 아님) → `ConfigError`, `default_config_toml()`을 다시 로드하면 `summarize_concurrency == 4`이고 기존 기본값 대조 테스트도 통과
    - `uv run pytest tests/test_readme.py` 통과 (6건, `summarize.concurrency` 행 대조 포함)
    - `uv run pytest` 전체 통과 (T14c 이후 243건 회귀 없음)
  - 결과: PASS 11/12 (전체 250건). 메모 1(오류 문구·무시 규칙·음수 테스트)·3(429 재시도)은 T16 부수 작업으로, 메모 2(README 문구)는 T16 완료로 해소.

- [x] T16. 요약 LLM 호출 병렬화
  - 메모(Planner): PRD 4.3 "글별 LLM 호출 병렬, DB 저장은 한 번에 하나씩, 한 글의 실패는 다른 글에 영향 없음". 새 의존성 없음(표준 `concurrent.futures`).
  - 내용:
    - (src, summarize_run.py) `summarize_article`을 두 단계로 나눔: LLM 호출부(`_call_with_retry`, DB 비의존·스레드에서 실행)와
      기록부(성공/실패 저장·로그·existing_tags 갱신, 메인 스레드). 기존 `summarize_article`의 시그니처·동작은 유지(내부에서 두 단계를 차례로 호출).
    - `summarize_pending(..., concurrency: int = 1)` 추가. `concurrency < 1`이면 `ValueError`. `ThreadPoolExecutor(max_workers=concurrency)`로
      대상 글마다 LLM 호출을 제출하고, **제출 순서(id 오름차순)대로** 결과를 기다려 메인 스레드에서 하나씩 DB 기록 후 `on_outcome` 호출
      (자체 결정: 출력·DB 기록이 결정적이고 sqlite 연결을 한 스레드에서만 씀). 각 호출에는 제출 시점의 태그 목록 **복사본**을 넘김
      (병렬 호출 사이에 새 태그 힌트가 즉시 공유되지 않는 것은 허용, 자체 결정).
    - 작업 스레드에서 `SummarizerError`·`SummaryValidationError`가 아닌 예외가 나면 기존 순차 동작처럼 메인 스레드에서 재던짐.
      `DatabaseError`가 나면 남은 미시작 작업은 취소(`cancel_futures=True`)하고 던짐(이미 기록한 결과는 유지).
    - (src, cli.py) `_do_summarize`가 `concurrency=config.summarize_concurrency`를 넘김. 결과 줄 출력 형식·종료 코드는 그대로.
    - `concurrency=1`이면 기존 순차 실행과 결과·호출 순서가 같아야 함(기존 테스트가 그대로 통과).
    - 동시 실행 수 상한은 두지 않음(설정값 그대로, 자체 결정). 429는 기존 `SummarizerError(transient=True)` 재시도 경로로 흡수됨을 테스트로 확인(T15 REVIEW 메모 3).
    - 부수 작업(tests만, T15 REVIEW 메모 1): `tests/test_config.py`의 summarize 오류 테스트에 `match="summarize"` 추가,
      `[summarize]\nfoo = 1` → 4(무시 규칙)·`concurrency = -1` → `ConfigError` 케이스 추가. `config.py`는 수정하지 않음.
  - touch: `src/rss_wiki/summarize_run.py`, `src/rss_wiki/cli.py`, `tests/test_summarize_run.py`, `tests/test_summarize_cmd.py`(필요 시), `tests/test_config.py`(부수 작업만)
  - acceptance:
    - `uv run pytest tests/test_summarize_run.py` 통과, 신규 (가짜 Summarizer, 네트워크·LLM 없음, sleep 스텁):
      - `threading.Barrier(2, timeout=5)`를 기다리는 가짜 Summarizer + `concurrency=2`, 글 2건 → 교착 없이 둘 다 done (실제로 동시에 실행됨을 증명)
      - 동시 실행 중인 호출 수를 세는 가짜 Summarizer + `concurrency=3`, 글 8건 → 관측 최대값 ≤ 3이고 ≥ 2
      - 글 4건 중 1건만 `SummarizerError(transient=False)` → 나머지 3건 done, 실패 글만 `attempts=1`, 반환 결과와 `on_outcome` 호출 순서가 id 오름차순
      - `on_outcome`이 받은 스레드가 모두 메인 스레드(`threading.main_thread()`)
      - `concurrency=0` → `ValueError`
      - `concurrency=2`, 한 글이 첫 호출에서 `SummarizerError(transient=True)`(429 모사) 후 성공 → done, sleep 스텁 1회 기록, 다른 글 영향 없음
    - `uv run pytest tests/test_config.py` 통과 (신규 2건: 무시 규칙, 음수, 오류 문구 `match`)
    - `uv run pytest tests/test_summarize_cmd.py tests/test_run_cmd.py` 통과 (회귀 없음)
    - `uv run pytest` 전체 통과 (T15 이후 250건 회귀 없음)
  - 결과: PASS 10/12 (전체 259건). 메모 1~4는 T16a로 이관.

- [x] T16a. 병렬 요약 취소 경로 테스트·Ctrl+C 빠른 종료·README 주의 문구 (T16 REVIEW 메모 1~4)
  - 내용:
    - (src, summarize_run.py, 메모 3) 병렬 경로의 `except BaseException:`(현 226-228행)을 나눔: `KeyboardInterrupt`면
      `executor.shutdown(wait=False, cancel_futures=True)` 후 재던짐(이미 실행 중인 호출을 기다리지 않음, 자체 결정: 웹 UI 백그라운드 `run` 중단에도 재사용).
      그 외 예외(`DatabaseError` 포함)는 기존대로 `shutdown(wait=True, cancel_futures=True)` 후 재던짐. 순차 경로·출력 형식은 그대로.
    - (tests, 메모 1) `concurrency=2`, 글 6건, monkeypatch로 `_store_success`(또는 기록부의 실제 저장 함수, 이름은 현재 코드에 맞출 것)가
      2번째 글에서 `sqlite3.OperationalError`를 던지게 함 → `DatabaseError` 발생, 1번째 글 `status == "done"` 유지, 2번째 이후 글은 done 아님,
      가짜 Summarizer 호출 수 < 6 (미시작 작업 취소 확인, 호출 수 상한은 `2 + concurrency` 이하로 단언).
    - (tests, 메모 2) 429 모사 테스트에 다른 글의 `status == "done"`·`attempts == 0` 단언 추가.
    - (tests, 메모 3) 2번째 글 호출이 `threading.Event().wait(5)`로 막혀 있는 가짜 Summarizer + `concurrency=2`, `on_outcome`이 1번째 글에서
      `KeyboardInterrupt`를 던짐 → `KeyboardInterrupt` 전파, 경과 시간 < 2초. 테스트 끝(`finally`)에서 이벤트를 set해 스레드를 풀어 줌.
    - (docs, 메모 4) README 설정 표 `summarize.concurrency` 설명에 "너무 크면 API 속도 제한(429)에 걸릴 수 있음" 취지 문구 추가(앞 두 칸 형식은 유지).
  - touch: `src/rss_wiki/summarize_run.py`, `tests/test_summarize_run.py`, `README.md`
  - acceptance:
    - `uv run pytest tests/test_summarize_run.py` 통과 (신규 2건: DatabaseError 취소, KeyboardInterrupt 빠른 종료 / 429 테스트 단언 보강)
    - `uv run pytest tests/test_readme.py` 통과, README에 `429` 문자열 포함
    - `uv run pytest` 전체 통과 (T16 이후 259건 회귀 없음, 261건)
  - 결과: Generator 완료(전체 261건). Evaluator 사이클 없이 다음 사이클로 넘어옴. Planner가 summarize_run.py:226-227(`KeyboardInterrupt` → `shutdown(wait=False, cancel_futures=True)`)과 README 429 문구를 확인함. 회귀는 T17 acceptance의 전체 테스트로 확인.

## M7. 웹 UI (PRD v2 5장) — Flask + Jinja2 (합의 A)

- [ ] T17. `serve` 골격·디자인 토큰·빈 상태 홈 (스크린샷만 남음, BLOCKED 3회째 → docs/HALT로 사람에게 브라우저 도구 권한 요청, 2026-11-03)
  - BLOCKED(1회째): 코드·테스트는 완료(전체 266건 통과)했으나 스크린샷(`docs/screens/home-{light,dark}.png`)을 찍지 못함. Playwright MCP 도구(navigate, emulate_media) 사용 권한이 거부됨. 필요: 브라우저 도구 권한 허용 또는 다른 캡처 수단 승인.
  - BLOCKED(2회째): T18 세션 재시도에서도 Playwright `browser_navigate` 권한이 거부됨. 스크린샷 미생성.
  - BLOCKED(3회째): T18a 세션 재시도에서도 Playwright `browser_navigate` 권한이 거부됨. 스크린샷(home·feeds, light·dark) 미생성. 사람이 브라우저 도구 권한을 허용해야 함.
  - 결과: 조건부 PASS 11/15 (전체 266건). 남은 acceptance는 스크린샷 2장뿐. PRD 5장 "화면을 바꿀 때마다 스크린샷으로 확인"이 요구이므로 acceptance에서 빼지 않음 (Planner).
    재시도는 T18 세션에서 함께 함. 권한이 다시 거부되면 Generator는 이 항목에 `BLOCKED(2회째)`를 기록하고 T18의 나머지 작업은 계속함.
    (3회째가 되면 Planner가 HALT로 사람에게 브라우저 도구 권한 허용을 요청함.) 다른 우회 수단(새 캡처 의존성 설치 등)은 쓰지 않음.
    메모 2(내비 404)·메모 3(테스트 보강)은 T18로 이관.
  - 메모(Planner): 웹 프레임워크 합의 A(Flask + Jinja2) 반영. 이번 항목은 골격만이며 피드·수집·글 화면은 T18 이후.
  - 내용:
    - `uv add flask` (Jinja2 포함). 신규 패키지 `src/rss_wiki/web/`: `__init__.py`에 `create_app(config: Config) -> Flask`
      (config는 `app.config["RSS_WIKI"]`에 보관), `templates/base.html`(공통 레이아웃: `<html lang="ko">`, 헤더 내비 `피드`·`수집하기`·`글`, `<meta name="viewport">`),
      `templates/home.html`, `static/style.css`.
    - 디자인 토큰: `style.css` 맨 위 `:root`에 색상(`--color-bg`, `--color-fg`, `--color-muted`, `--color-accent`, `--color-border`, `--color-danger`)·
      글꼴(`--font-sans`: Pretendard/Noto Sans KR/시스템 한글 글꼴 폴백)·간격(`--space-1`~`--space-6`)·`--radius` 정의, 본문 `line-height` 1.7·`word-break: keep-all`(한국어 가독성).
      다크 모드는 `@media (prefers-color-scheme: dark)`에서 색상 토큰만 재정의 (자체 결정: 토글 UI 없이 OS 설정 추종, 가장 단순).
      반응형은 640px 기준 미디어 쿼리 1개로 내비·본문 폭 조정. 이후 화면의 색·간격은 토큰만 사용.
    - `GET /`: `status.collect_status`로 피드 수·글 수·요약 대기 수를 카드로 표시. 피드가 0개면 빈 상태 안내("등록된 피드가 없습니다" + 피드 등록 안내).
      요청마다 `connect`+`init_schema` 후 닫음. `DatabaseError` → 500 오류 화면(템플릿 `error.html`, 메시지 표시, 트레이스백 미노출).
    - CLI: `serve [--port 8000]` 서브커맨드. 호스트는 `127.0.0.1` 고정(옵션 없음). 실제 실행은 모듈 함수 `run_server(app, host, port)`(`app.run(...)`)로 분리해 테스트에서 monkeypatch.
      `flask`는 `cmd_serve` 안에서 지연 import(다른 명령 시동 시간 유지, T10c와 같은 방침).
    - README에 `serve` 사용법 한 줄 추가(test_readme의 서브커맨드 대조 통과용).
    - 스크린샷: `uv run rss-wiki serve`로 띄운 홈(빈 상태)을 라이트·다크로 캡처해 `docs/screens/home-light.png`, `docs/screens/home-dark.png` 저장(Playwright 등 도구 재량).
  - touch: `pyproject.toml`, `uv.lock`, `src/rss_wiki/web/`(신규: `__init__.py`, `templates/`, `static/style.css`), `src/rss_wiki/cli.py`, `README.md`, `tests/test_web.py`(신규), `tests/test_readme.py`(필요 시), `docs/screens/`(신규)
  - acceptance:
    - `uv run pytest tests/test_web.py` 통과 (Flask 테스트 클라이언트, 네트워크 없음):
      - 빈 DB `GET /` → 200, 본문에 "등록된 피드가 없습니다"·`lang="ko"`·`/static/style.css` 링크 포함
      - 피드 1건(직접 INSERT) → 200, 빈 상태 문구 없음, 피드 수 1 표시
      - `GET /static/style.css` → 200, `:root`·`--color-bg`·`prefers-color-scheme: dark` 포함
      - `collect_status`가 `DatabaseError`를 던지게 monkeypatch → 500, 오류 메시지 포함·`Traceback` 미포함
      - `main([... "serve", "--port", "8123"])`에서 monkeypatch한 `run_server`가 `host == "127.0.0.1"`, `port == 8123`으로 호출되고 종료 코드 0
    - `uv run rss-wiki serve --help` 종료 코드 0
    - `docs/screens/home-light.png`, `docs/screens/home-dark.png` 존재
    - `uv run pytest` 전체 통과 (T16a 이후 261건 회귀 없음, `tests/test_summarize_run.py`의 T16a 신규 2건 포함)

- [x] T18. 피드 관리 화면(목록·등록·삭제)과 내비 정리 (T17 REVIEW 메모 2·3)
  - 메모(Planner): PRD 5장 "피드 관리: 피드 목록, 등록, 삭제". 라우트는 `feeds.list_feeds`·`add_feed`·`remove_feed`만 호출하고 SQL을 새로 두지 않음.
  - 내용:
    - (src, web/__init__.py) `create_app(config, *, http_client_factory=None)`: 기본값은 `HttpClient(timeout=config.http_timeout, max_retries=config.max_retries)`를 만드는 함수
      (web이 cli를 import하지 않도록, 자체 결정). 테스트는 MockTransport·sleep 스텁 클라이언트를 돌려주는 팩토리를 주입.
      `app.secret_key = os.urandom(32)`(flash 용, 프로세스마다 새로 생성, 로컬 전용이라 저장하지 않음, 자체 결정).
    - `GET /feeds`: `list_feeds` 결과 표(id·이름·URL·마지막 수집 시각·상태, 값 없으면 `-`) + 등록 폼(`url` 필수, `name` 선택). 피드 0개면 빈 상태 안내.
    - `POST /feeds`: `add_feed` 호출. 성공 → flash 성공 메시지 후 `/feeds`로 303 리다이렉트. `FeedError` → flash 오류 메시지 후 303(PRG 패턴 하나로 통일, 자체 결정).
      빈 url → `add_feed` 호출 없이 오류 flash. 등록 중 HTTP 클라이언트는 요청 안에서 만들고 닫음.
    - `POST /feeds/<int:feed_id>/delete`: `remove_feed(conn, str(feed_id))`. 성공/`FeedError` 모두 flash 후 303. 삭제 버튼은 `<form method="post">`(GET 삭제 금지).
    - POST 요청에 `Origin` 헤더가 있고 요청 호스트와 다르면 403 (자체 결정: 로컬 서버에 대한 교차 사이트 POST 차단, CSRF 토큰보다 단순).
    - `DatabaseError`는 기존 errorhandler(500)로 처리. flash 메시지는 `base.html`에 성공/오류 스타일(토큰 색 `--color-accent`/`--color-danger`)로 표시.
    - (메모 2) `base.html` 내비: `피드`는 `/feeds` 링크, 아직 없는 `수집하기`·`글`은 링크 대신 `<span class="nav-disabled" aria-disabled="true">… (준비 중)</span>`으로 표시 (T19·T20에서 링크로 복원).
      현재 화면은 `aria-current="page"`로 강조.
    - 새 스타일은 기존 토큰만 사용(표는 640px 이하에서 가로 스크롤 또는 카드형, Generator 재량).
    - (tests, 메모 3) `test_home_with_feed`에 `data-count="articles"`·`data-count="pending"` 값 단언, DatabaseError 테스트에 `caplog`(logger `rss_wiki.web`, ERROR) 레코드 단언 추가.
    - 스크린샷: T17 재시도(`docs/screens/home-{light,dark}.png`)와 함께 `docs/screens/feeds-{light,dark}.png`(피드 1건 이상 + flash 표시 상태 권장). 권한이 거부되면 T17에 `BLOCKED(2회째)`를 기록하고 이 항목은 스크린샷 없이 완료 처리 가능
      (피드 화면 스크린샷은 T17과 같은 차단 요인으로 묶어 추적, Planner).
  - touch: `src/rss_wiki/web/__init__.py`, `src/rss_wiki/web/templates/`(base.html, feeds.html 신규), `src/rss_wiki/web/static/style.css`, `tests/test_web.py`, `docs/screens/`(가능할 때만)
  - acceptance:
    - `uv run pytest tests/test_web.py` 통과 (Flask 테스트 클라이언트, MockTransport, 네트워크 없음), 신규:
      - 빈 DB `GET /feeds` → 200, 빈 상태 문구·등록 폼(`method="post"`, `name="url"`) 포함
      - `POST /feeds`(url=rss2.xml 제공 MockTransport) → 303, `Location`이 `/feeds`, feeds 행 1건, 리다이렉트 따라가면 성공 메시지와 피드 이름 표시
      - 같은 URL 재등록 → 303, 따라가면 오류 메시지에 URL 포함, feeds 행 1건 유지
      - HTML 응답(not_feed.html) 등록 → 오류 메시지, feeds 행 0건 / 빈 url → 오류 메시지, HTTP 요청 0회
      - `POST /feeds/<id>/delete` → 303, 행 삭제 / 없는 id → 오류 메시지 / `GET /feeds/<id>/delete` → 405
      - `Origin: https://evil.example` 헤더로 `POST /feeds` → 403, feeds 행 0건
      - `GET /` 본문에 `/feeds` 링크가 있고 `/run`·`/articles` 링크(`href="/run"`, `href="/articles"`)는 없음, `준비 중` 포함
      - 메모 3 단언(data-count 값, caplog ERROR)
    - `uv run pytest` 전체 통과 (T17 이후 266건 회귀 없음)
  - 결과: PASS 12/15 (전체 276건). 메모 2·3·4·6은 T18a로 이관, 메모 5(등록 대기 시간, 선택)는 T19 메모로 이관, 메모 1(스크린샷)은 T17로 추적.

- [x] T18a. 홈 안내 링크·삭제 확인·웹 DB 오류 일관 처리·피드 화면 테스트 보강 (T18 REVIEW 메모 2·3·4·6)
  - 내용:
    - (src, home.html, 메모 2) 빈 상태 안내의 "웹 피드 관리 화면은 곧 추가됩니다" 문구를 지우고 `<a href="/feeds">피드 관리 화면</a>`에서 등록하라는 안내로 교체.
    - (src, feeds.html, 메모 3) 삭제 폼에 `onsubmit="return confirm('피드 「{{ 이름 }}」을(를) 삭제할까요? 기존 글은 유지됩니다.')"` 형태의 확인 추가
      (자체 결정: JS 한 줄로 가장 단순, JS가 꺼져 있으면 기존처럼 바로 삭제). 이름은 Jinja2 자동 이스케이프를 거치되 JS 문자열 안이므로 `|tojson` 사용.
    - (src, web/__init__.py, 메모 4) `@app.errorhandler(sqlite3.Error)` 추가: `log.error("웹 요청 중 DB 오류: %s", exc)` 후 `error.html` 500
      (자체 결정: feeds.py를 고치지 않고 웹 계층에서 일관 처리, 최소 변경). 기존 `DatabaseError` 핸들러는 유지.
    - (src, web/__init__.py, 메모 6) 성공 flash는 저장된 피드 이름을 표시: `add_feed` 후 `list_feeds`에서 해당 id의 name을 찾아 `피드를 등록했습니다 (id=N): <name>` (자체 결정, SQL 신규 금지).
    - (tests, 메모 6) not_feed 등록 → 따라간 화면의 오류 메시지에 등록 URL 포함, 삭제 성공 → `Location`이 `/feeds`이고 따라가면 "삭제했습니다"·"기존 글은 유지" 포함.
    - 스크린샷 재시도(T17, 3회째 시도): `docs/screens/home-{light,dark}.png`, `docs/screens/feeds-{light,dark}.png`. 권한이 다시 거부되면 T17에 `BLOCKED(3회째)`를 기록하고
      이 항목의 나머지는 완료 처리(다음 Planner가 HALT로 사람에게 브라우저 도구 권한을 요청함). 다른 우회 수단(새 캡처 의존성 설치 등)은 쓰지 않음.
  - touch: `src/rss_wiki/web/__init__.py`, `src/rss_wiki/web/templates/home.html`, `src/rss_wiki/web/templates/feeds.html`, `tests/test_web.py`, `docs/screens/`(가능할 때만)
  - acceptance:
    - `uv run pytest tests/test_web.py` 통과, 신규:
      - 빈 DB `GET /` → 본문에 `href="/feeds"` 포함, `곧 추가됩니다` 미포함
      - 피드 1건 `GET /feeds` → 삭제 폼에 `onsubmit=` 와 `confirm(` 포함
      - `monkeypatch`로 `rss_wiki.web.add_feed`가 `sqlite3.OperationalError("database is locked")`를 던지게 함 → `POST /feeds` 500, 본문에 `database is locked` 포함·`Traceback` 미포함, caplog(`rss_wiki.web`, ERROR) 레코드 1건 이상
      - `--name` 없이 등록 성공 → 따라간 flash에 피드 제목(rss2.xml의 채널 제목) 포함
      - not_feed 등록 → 오류 flash에 등록 URL 포함 / 삭제 성공 → 303·`Location` `/feeds`·"기존 글은 유지" 포함
    - `uv run pytest` 전체 통과 (T18 이후 276건 회귀 없음)
  - 결과: PASS 13/15 (전체 282건). 메모 2~4는 T18b로 이관. 메모 1(스크린샷)은 T17 BLOCKED(3회째)로 이어져 docs/HALT 생성 (Planner, 2026-11-03).

- [ ] T18b. 피드 화면 테스트 정밀화·웹 DB 오류 핸들러 통합 (T18a REVIEW 메모 2~4) — **다음** (HALT 해제 뒤, T17 스크린샷 재시도와 함께)
  - 내용:
    - (tests, 메모 2) `test_add_without_name_flash_shows_feed_title`의 제목 단언을 `class="flash flash-success"` div 내용으로 좁힘(정규식으로 내용 추출 후 단언).
    - (tests, 메모 3) 이름이 `Tom's "quote" </script><b>x`인 피드를 직접 INSERT하고 `/feeds`의 삭제 폼 `onsubmit` 속성을 뽑아 `html.unescape` 후
      `confirm(` 인자를 `json.loads`로 복원했을 때 원래 이름이 들어 있음을 단언. 페이지에 원문 `<b>x`가 없음도 단언.
    - (src, 메모 4) web/__init__.py의 `DatabaseError`·`sqlite3.Error` 핸들러를 함수 하나로 합치고 `app.register_error_handler`를 두 번 호출(동작 변화 없음).
    - (tests, 메모 4) `monkeypatch`로 `rss_wiki.web.list_feeds`가 `sqlite3.OperationalError`를 던지게 하면 `GET /feeds` → 500, `Traceback` 미포함.
    - 스크린샷(T17): `docs/screens/home-{light,dark}.png`, `feeds-{light,dark}.png`. 성공하면 T17을 완료로 표시.
  - touch: `src/rss_wiki/web/__init__.py`, `tests/test_web.py`, `docs/screens/`
  - acceptance:
    - `uv run pytest tests/test_web.py` 통과 (신규 2건: confirm 이스케이프 복원, `/feeds` GET DB 오류 → 500 / flash 범위 단언 수정)
    - `docs/screens/home-light.png`, `home-dark.png`, `feeds-light.png`, `feeds-dark.png` 존재
    - `uv run pytest` 전체 통과 (T18a 이후 282건 회귀 없음, 284건)

  - 이후 항목(예정): T19 수집하기(`run` 백그라운드 스레드 + 폴링 진행 표시; T18 메모 5: 웹 피드 등록 대기 시간도 이 방식과 맞출지 검토), T20 글 목록/상세/태그별 보기, 각 화면 라이트·다크 스크린샷.
