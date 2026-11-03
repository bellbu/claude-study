# 결정: 본문 추출 라이브러리

RSS 본문이 기준값(500자)보다 짧을 때 원문 페이지에서 본문을 추출할 방법.

- A: trafilatura (본문 추출 전용, 다국어 품질 좋음, 의존성 다소 많음)
- B: readability-lxml (Readability 알고리즘 포팅)
- C: BeautifulSoup 휴리스틱 (`<article>`/`<main>`/가장 긴 텍스트 블록 선택)

합의: A (시도 1회)
반영: PRD 10장 (2026-10-29, 정리 완료)
