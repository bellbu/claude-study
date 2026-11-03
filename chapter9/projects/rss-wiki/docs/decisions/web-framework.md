# 결정: 웹 프레임워크

`rss-wiki serve`(PRD 5장)의 로컬 웹 UI(127.0.0.1 전용, 1인 사용)를 어떤 프레임워크로 만들지.
CLI와 같은 기능 코드(feeds·fetch·summarize_run·wiki, 모두 동기 함수)를 호출하고,
`run` 진행 상황 표시와 서버 렌더링 HTML(디자인 토큰 CSS, 다크 모드, 반응형)이 필요하다.

- A: Flask + Jinja2 (동기 WSGI, 개발 서버로 로컬 실행, `run`은 백그라운드 스레드 + 폴링으로 진행 표시)
- B: FastAPI + Jinja2 + uvicorn (ASGI, 동기 기능 코드는 스레드풀로 호출, SSE 등으로 진행 표시)
- C: 표준 라이브러리 `http.server` + `string.Template` (의존성 없음, 라우팅·폼 처리·템플릿 직접 구현)

합의: A (시도 1회)
반영: PRD 11장 (2026-11-02, 정리 완료)
