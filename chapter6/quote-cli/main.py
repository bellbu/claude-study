import argparse
import json
import random
import sqlite3
import sys
from contextlib import closing, contextmanager
from pathlib import Path
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("quote")  # ① 서버 객체 생성

DB_FILE = Path(__file__).parent / "quotes.db"
QUOTES_FILE = Path(__file__).parent / "quotes.json"  # 최초 1회 마이그레이션 원본

SCHEMA = """
CREATE TABLE IF NOT EXISTS quotes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    author TEXT NOT NULL
)
"""


class MigrationError(Exception):
    """quotes.json 형식이 잘못되어 마이그레이션할 수 없을 때 발생합니다."""


def _migrate_from_json(conn: sqlite3.Connection) -> None:
    """테이블이 비어 있고 quotes.json이 있으면 그 내용을 순서대로 가져옵니다."""
    if conn.execute("SELECT 1 FROM quotes LIMIT 1").fetchone():
        return
    if not QUOTES_FILE.exists():
        return
    conn.execute("BEGIN IMMEDIATE")  # 동시 실행 시 이중 마이그레이션 방지(쓰기 잠금)
    try:
        if not conn.execute("SELECT 1 FROM quotes LIMIT 1").fetchone():
            data = json.loads(QUOTES_FILE.read_text(encoding="utf-8"))
            if not isinstance(data, list):  # null·숫자 등 목록이 아니면 중단
                raise MigrationError("quotes.json의 최상위 값이 목록이 아닙니다.")
            rows = [
                (q["text"], q["author"])
                for q in data
                if isinstance(q, dict)
                and isinstance(q.get("text"), str)
                and isinstance(q.get("author"), str)
            ]  # text/author가 없는 항목은 건너뜀
            conn.executemany("INSERT INTO quotes (text, author) VALUES (?, ?)", rows)
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


@contextmanager
def _connect():
    """DB 연결을 열고(스키마 준비·마이그레이션 포함) 사용 후 반드시 닫습니다."""
    with closing(sqlite3.connect(DB_FILE)) as conn:  # closing: 연결 닫기 보장
        conn.execute(SCHEMA)
        conn.commit()
        _migrate_from_json(conn)
        with conn:  # with conn: 성공 시 commit, 예외 시 rollback(닫지는 않음)
            yield conn


def load_quotes() -> list:
    with _connect() as conn:
        rows = conn.execute("SELECT text, author FROM quotes ORDER BY id").fetchall()
    return [{"text": text, "author": author} for text, author in rows]


def search_quotes(keyword: str) -> list:
    """명언 본문에 키워드가 포함된 항목만 반환합니다(대소문자 무시)."""
    needle = keyword.strip().casefold()
    if not needle:
        raise ValueError("검색 키워드가 비어 있습니다.")
    return [q for q in load_quotes() if needle in str(q.get("text", "")).casefold()]


@mcp.tool()  # ② 무작위 명언 반환 도구
def get_random_quote() -> str:
    """무작위 명언 한 개를 반환합니다."""
    quote = random.choice(load_quotes())
    return f'{quote["text"]} - {quote["author"]}'


@mcp.tool()  # ③ 명언 추가 도구(쓰기)
def add_quote(text: str, author: str) -> str:
    """새 명언을 명언 목록에 추가합니다."""
    with _connect() as conn:
        conn.execute("INSERT INTO quotes (text, author) VALUES (?, ?)", (text, author))
        (count,) = conn.execute("SELECT COUNT(*) FROM quotes").fetchone()
    return f"명언을 추가했습니다. 현재 {count}개입니다."


@mcp.resource("quote://all")  # ④ 리소스
def all_quotes() -> str:
    """전체 명언 목록을 반환합니다."""
    return json.dumps(load_quotes(), ensure_ascii=False, indent=2)


@mcp.prompt()  # ⑤ 프롬프트
def quote_post(topic: str) -> str:
    """명언을 인용한 짧은 글을 작성합니다."""
    return (
        f"등록된 명언 중 '{topic}' 주제와 가장 어울리는 것을 quote://all에서 고르고, "
        "그 명언을 인용한 세 문단 분량의 짧은 글을 작성해주세요."
    )


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description="명언 MCP 서버 / 명언 검색")
    parser.add_argument(
        "--search", metavar="키워드", help="명언 본문에 키워드가 포함된 항목만 출력합니다."
    )
    args = parser.parse_args(argv)

    if args.search is None:
        mcp.run()  # ⑥ stdio 전송으로 서버 실행
        return 0

    try:
        results = search_quotes(args.search)
    # JSONDecodeError·UnicodeDecodeError는 ValueError의 하위 클래스이므로 먼저 잡음
    except (
        sqlite3.Error,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        MigrationError,
    ) as e:
        print(f"명언 DB를 읽을 수 없습니다: {e}", file=sys.stderr)
        return 1
    except ValueError as e:
        parser.error(str(e))
    if not results:
        print(f"'{args.search}'(이)가 포함된 명언이 없습니다.")
        return 0
    for quote in results:
        print(f'{quote["text"]} - {quote["author"]}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
