# REVIEW: T18a. 홈 안내 링크·삭제 확인·웹 DB 오류 일관 처리·피드 화면 테스트 보강

대상: IMPL.md의 처리 항목 T18a. T17 스크린샷 재시도는 `BLOCKED(3회째)`로 보고되었습니다. 화면이 있는 항목이므로 5축 15점 만점으로 채점하고, 12점 이상이면 PASS, 8~11점이면 조건부 PASS입니다.

## 직접 실행 결과

- `uv run pytest -x tests/test_web.py`: 21 passed (T18까지 15건 + T18a 신규 6건)
- `uv run pytest`: 282 passed (T18 이후 276건에서 회귀 없음)
- 빈 데이터 디렉터리로 `serve --port 8765`를 띄우고 curl로 확인: `GET /` 200, 빈 상태 안내에 `<a href="/feeds">피드 관리 화면</a>` 표시, `곧 추가됩니다` 없음. `GET /feeds` 200.
- 이스케이프 확인: 이름이 `Tom's "quote" </script><b>x`인 피드를 직접 넣고 `/feeds`를 렌더링했습니다. onsubmit 속성 값은 `&#34;`로 감싸져 속성이 깨지지 않았고, HTML 언이스케이프 결과도 유효한 JS 문자열 리터럴(`"…\"quote\" </script>…"`)이었습니다. 원문 `<b>x`도 페이지에 노출되지 않았습니다. `tojson|forceescape` 결정(feeds.html:32)은 타당합니다.
- 화면을 시각적으로 확인하지 못했습니다. Generator가 Playwright 권한 거부를 3회째 보고했고, Evaluator도 우회 수단을 쓰지 않았습니다. 그래서 화면 완성도는 템플릿·CSS 코드와 curl로 받은 HTML을 근거로 채점했습니다(판단 기준: 디자인 토큰 일관성, 파괴적 동작 보호, 주요 동작 발견 가능성에 관한 일반적인 모범 사례).
- touch 범위: 프로젝트 전체가 git에서 untracked 상태라 diff로 대조할 수 없었습니다. 대신 IMPL.md의 변경 파일 목록과 파일 수정 시각을 대조했습니다. 이번 세션에 수정된 파일은 web/__init__.py, home.html, feeds.html, tests/test_web.py뿐이었고(base.html 07:19, style.css 07:15는 T18 시점), 모두 touch 범위 안입니다.
- docs/decisions/: 12개 주제 모두 `합의:` 줄이 있어 Evaluator의 독립 선택이 필요하지 않습니다.

## 평가 표

| 축 | 점수 | 근거 |
|---|---|---|
| 사양 충족 | 3 | T18a acceptance를 모두 통과했습니다. 홈 `/feeds` 링크와 문구 제거(tests/test_web.py:194-197), confirm 폼(200-203), `sqlite3.OperationalError` 500·Traceback 미노출·caplog(206-216), 이름 없이 등록하면 피드 제목 표시(219-221), not_feed URL 표시(224-227), 삭제 303·Location·안내 문구(230-238)가 해당합니다. 구현은 home.html:9, feeds.html:32, web/__init__.py:72-73, 98-101에 있습니다. 실서버와 이스케이프 시나리오도 직접 확인했습니다. 스크린샷은 TASKS.md:974-975에 따라 BLOCKED를 기록하면 이 항목은 완료할 수 있습니다. |
| 모듈 경계 | 3 | `sqlite3.Error`는 feeds.py를 고치지 않고 웹 계층 errorhandler로 처리했습니다(web/__init__.py:98-101). flash 이름은 SQL을 새로 쓰지 않고 `list_feeds`를 재사용해 얻습니다(72). 변경은 모두 touch 범위 안입니다. 참고로 `DatabaseError` 핸들러와 `sqlite3.Error` 핸들러의 본문이 같습니다(93-101). 감점할 정도는 아닙니다. |
| 테스트 충실도 | 2 | T18 메모에서 지적한 not_feed URL, 삭제 Location·문구, sqlite 오류의 caplog 단언을 보강했습니다. 감점 이유는 다음과 같습니다. ① `test_add_without_name_flash_shows_feed_title`(219-221)은 페이지 전체에서 제목을 찾는데, 제목은 표의 이름 칸(feeds.html:27)에도 나옵니다. 그래서 flash가 제목을 표시하지 않아도 통과합니다. `flash-success` div 안에 있는지 확인해야 합니다. ② confirm 테스트(200-203)는 문자열이 있는지만 봅니다. 따옴표나 `<`가 들어간 이름에서 이스케이프가 맞는지는 검증하지 않습니다(Evaluator가 수동으로 확인했으나 회귀 방지 테스트가 없습니다). ③ `/feeds` GET 경로의 DB 오류는 여전히 테스트하지 않습니다. |
| 운영 고려 | 3 | 새 의존성이 없습니다. DB 오류는 ERROR 로그를 남기고 트레이스백 없이 500 화면을 보여 줍니다(web/__init__.py:95, 100). 연결은 `finally`에서 닫힙니다(76-77). 실행 방법은 IMPL.md와 README(`serve` 행)에 있습니다. 등록 대기 시간 문제(T18 메모 5)는 T19로 이관되어 있어 이번 감점 대상이 아닙니다. |
| 화면 완성도 | 2 | 홈 빈 상태에서 피드 관리 화면으로 가는 링크가 생겨 주요 동작을 찾기 쉬워졌습니다(home.html:9). 삭제에는 이름과 "기존 글은 유지" 안내가 들어간 확인 대화상자가 붙었고(feeds.html:32), 성공 flash에는 저장된 피드 이름이 표시됩니다(web/__init__.py:73). 감점 이유: 렌더링 결과(여백, 타이포그래피, 다크 모드 대비)를 시각적으로 확인하지 못했습니다. 스크린샷 4장(home·feeds × light·dark)이 아직 없습니다. |
| **합계** | **13 / 15** | |

## 합격 여부

**PASS (13/15)** — 화면 항목 기준 12점 이상.

## 다음 사이클 메모

1. (HALT 필요, 사람) T17 스크린샷이 3회 연속 Playwright 권한 거부로 막혔습니다(TASKS.md:899-901). 사람이 `mcp__playwright__browser_navigate`·`browser_emulate_media`·`browser_take_screenshot` 권한을 허용해야 `docs/screens/home-{light,dark}.png`와 `feeds-{light,dark}.png`를 만들 수 있습니다. 그때까지 화면 완성도 축은 2점이 상한입니다.
2. (테스트) tests/test_web.py:219-221의 제목 단언을 `flash-success` div 범위로 좁히세요(예: `re.search(r'class="flash flash-success"[^>]*>([^<]*)<', html)`로 내용을 뽑아 단언).
3. (테스트) 따옴표·`<`가 들어간 이름으로 confirm 속성의 이스케이프를 확인하는 회귀 테스트를 추가하세요(속성을 `html.unescape`한 뒤 `json.loads`로 원래 메시지가 복원되는지 확인).
4. (선택) web/__init__.py:93-101의 두 핸들러를 하나의 함수로 합치세요(`app.register_error_handler`를 두 번 호출). `/feeds` GET에서 DB 오류가 나는 경로의 테스트도 추가하세요.
