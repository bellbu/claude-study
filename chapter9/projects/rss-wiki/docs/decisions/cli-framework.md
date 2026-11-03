# 결정: CLI 프레임워크

PRD 3장의 서브커맨드 CLI(`init`, `feed add/list/remove`, `fetch`, `summarize`, `build`, `run`, `status`)를 무엇으로 구현할지.

- A: argparse (표준 라이브러리, 의존성 없음)
- B: Typer (타입 힌트 기반, 개발 편의)
- C: Click (데코레이터 기반, 성숙한 생태계)

합의: A (시도 1회)
반영: PRD 10장 (2026-10-29, 정리 완료)
