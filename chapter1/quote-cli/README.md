# quote-cli

터미널에서 명언을 출력하는 간단한 Python CLI입니다. 인수 없이 실행하면 무작위 명언 하나를, `--list`를 주면 전체 명언 목록을 출력합니다.

## 프로젝트 구조

```
quote-cli/
├── quote.py        # CLI 본체
├── quotes.json     # 명언 데이터
├── test_quote.py   # pytest 테스트
└── README.md
```

## 요구 사항

- Python 3.8 이상
- 테스트 실행 시 [pytest](https://docs.pytest.org/)

`quote.py` 자체는 표준 라이브러리만 사용하므로 별도 패키지 없이 실행됩니다.

## 설치

1. 프로젝트 폴더로 이동합니다.

   ```bash
   cd quote-cli
   ```

2. (선택) 가상 환경을 만들고 활성화합니다.

   ```bash
   python -m venv .venv
   # Windows (PowerShell)
   .venv\Scripts\Activate.ps1
   # macOS / Linux
   source .venv/bin/activate
   ```

3. 테스트를 실행하려면 pytest를 설치합니다.

   ```bash
   python -m pip install pytest
   ```

## 사용법

### 무작위 명언 출력

```bash
python quote.py
```

```
"천 리 길도 한 걸음부터." - 노자
```

실행할 때마다 다른 명언이 나올 수 있습니다.

### 전체 목록 출력

```bash
python quote.py --list
```

```
1. "천 리 길도 한 걸음부터." - 노자
2. "배움에는 왕도가 없다." - 유클리드
3. "나는 생각한다, 고로 존재한다." - 르네 데카르트
4. "상상력은 지식보다 중요하다." - 알베르트 아인슈타인
5. "단순함은 궁극의 정교함이다." - 레오나르도 다빈치
6. "실패는 성공의 어머니이다." - 토머스 에디슨
7. "오늘 할 수 있는 일을 내일로 미루지 마라." - 벤저민 프랭클린
```

### 도움말

```bash
python quote.py --help
```

## 명언 추가하기

`quotes.json`에 `text`와 `author`를 가진 항목을 추가하면 됩니다. 파일은 UTF-8로 저장하세요.

```json
[
  {"text": "천 리 길도 한 걸음부터.", "author": "노자"},
  {"text": "새로 추가할 명언", "author": "인물 이름"}
]
```

목록이 비어 있으면 `등록된 명언이 없습니다.`를 출력하고 종료 코드 1로 끝납니다.

## 테스트

```bash
python -m pytest test_quote.py -v
```

테스트는 다음을 확인합니다.

- `quotes.json`의 모든 항목에 `text`와 `author`가 있는지
- 인수 없이 실행하면 `quotes.json`에 있는 명언이 정확히 한 줄 출력되는지
- `--list`로 실행하면 전체 항목이 번호와 함께 순서대로 출력되는지
- 명언 목록이 비어 있으면 오류 메시지와 함께 종료 코드 1을 반환하는지

> Windows에서 `pytest` 명령을 바로 쓰려면 pytest 설치 경로(`...\Python312\Scripts`)가 PATH에 있어야 합니다. `python -m pytest`는 PATH 설정과 관계없이 동작합니다.
