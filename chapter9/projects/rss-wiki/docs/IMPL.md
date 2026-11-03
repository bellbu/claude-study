# IMPL — T18a

## 처리한 항목
T18a 홈 안내 링크·삭제 확인·웹 DB 오류 처리·피드 화면 테스트 보강 (완료). T17 스크린샷 3회째 재시도는 실패.

## 변경 파일
- `src/rss_wiki/web/__init__.py`: `sqlite3.Error` 핸들러(500, ERROR 로그), 등록 flash에 저장된 피드 이름 표시(`list_feeds` 사용)
- `src/rss_wiki/web/templates/home.html`: "곧 추가됩니다" 제거, `/feeds` 링크 안내
- `src/rss_wiki/web/templates/feeds.html`: 삭제 폼 `onsubmit="return confirm(...)"` (`|tojson|forceescape`)
- `tests/test_web.py`: 신규 6건

## 검증
- `uv run pytest` → 282 passed (기존 276 + 신규 6)
- 스크린샷: Playwright `browser_navigate` 권한 거부 → T17에 `BLOCKED(3회째)` 기록. 우회 수단 쓰지 않음.

## 검증 항목(실행 방법)
`uv run rss-wiki serve --port 8000` 후 http://127.0.0.1:8000/ , /feeds

## 결정
- confirm 메시지는 `tojson`을 `forceescape`로 한 번 더 이스케이프해 속성 안의 `"`가 깨지지 않게 함(자체 결정).
- 이름이 없을 때 flash는 `saved or name or url` 순으로 표시.
