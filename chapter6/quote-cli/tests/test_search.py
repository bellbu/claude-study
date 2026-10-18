import json
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import main  # noqa: E402

DATA = [
    {"text": "천 리 길도 한 걸음부터.", "author": "노자"},
    {"text": "Stay hungry, stay foolish.", "author": "Steve Jobs"},
    {"text": "실패는 성공의 어머니이다.", "author": "토머스 에디슨"},
]


@pytest.fixture
def quotes_file(tmp_path, monkeypatch):
    """마이그레이션 원본 JSON(tmp)과 빈 DB 경로(tmp)를 지정합니다."""
    path = tmp_path / "quotes.json"
    path.write_text(json.dumps(DATA, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(main, "QUOTES_FILE", path)
    monkeypatch.setattr(main, "DB_FILE", tmp_path / "quotes.db")
    return path


def _db_rows(db_path):
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT text, author FROM quotes ORDER BY id").fetchall()
    conn.close()
    return rows


def test_search_matches_text(quotes_file):
    result = main.search_quotes("걸음")
    assert result == [{"text": "천 리 길도 한 걸음부터.", "author": "노자"}]


def test_search_ignores_case(quotes_file):
    assert len(main.search_quotes("STAY")) == 1


def test_search_does_not_match_author(quotes_file):
    assert main.search_quotes("노자") == []


def test_search_empty_keyword_raises(quotes_file):
    with pytest.raises(ValueError):
        main.search_quotes("   ")


def test_cli_prints_matches(quotes_file, capsys):
    assert main.main(["--search", "성공"]) == 0
    assert capsys.readouterr().out.strip() == "실패는 성공의 어머니이다. - 토머스 에디슨"


def test_cli_no_match_message(quotes_file, capsys):
    assert main.main(["--search", "없는말"]) == 0
    assert "없습니다" in capsys.readouterr().out


def test_cli_empty_keyword_exits_with_error(quotes_file):
    with pytest.raises(SystemExit) as exc:
        main.main(["--search", ""])
    assert exc.value.code == 2


def test_cli_without_search_runs_server(quotes_file, monkeypatch):
    called = []
    monkeypatch.setattr(main.mcp, "run", lambda: called.append(True))
    assert main.main([]) == 0
    assert called == [True]


def test_search_skips_entry_without_text(quotes_file):
    data = json.loads(quotes_file.read_text(encoding="utf-8"))
    data.append({"author": "작자 미상"})
    quotes_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    assert len(main.search_quotes("걸음")) == 1
    assert len(main.load_quotes()) == 3


def test_migrates_from_json_on_first_use(quotes_file):
    dup = DATA + [DATA[0]]  # 중복도 그대로 가져와야 함
    quotes_file.write_text(json.dumps(dup, ensure_ascii=False), encoding="utf-8")
    assert main.load_quotes() == dup
    assert _db_rows(main.DB_FILE) == [(q["text"], q["author"]) for q in dup]


def test_no_double_migration(quotes_file):
    main.load_quotes()
    assert len(main.load_quotes()) == 3
    assert len(_db_rows(main.DB_FILE)) == 3


def test_migration_skipped_when_db_has_rows(quotes_file):
    main.add_quote("첫 명언", "누군가")  # 테이블이 비어 있을 때만 마이그레이션
    quotes_file.write_text(json.dumps([DATA[0]], ensure_ascii=False), encoding="utf-8")
    assert len(main.load_quotes()) == 4


def test_works_without_json_file(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "QUOTES_FILE", tmp_path / "none.json")
    monkeypatch.setattr(main, "DB_FILE", tmp_path / "quotes.db")
    assert main.load_quotes() == []
    assert main.add_quote("새 명언", "작가") == "명언을 추가했습니다. 현재 1개입니다."


def test_add_quote_inserts_and_returns_count(quotes_file):
    msg = main.add_quote("오늘 할 일을 내일로 미루지 마라.", "벤저민 프랭클린")
    assert msg == "명언을 추가했습니다. 현재 4개입니다."
    assert main.load_quotes()[-1] == {
        "text": "오늘 할 일을 내일로 미루지 마라.",
        "author": "벤저민 프랭클린",
    }
    assert quotes_file.read_text(encoding="utf-8") == json.dumps(DATA, ensure_ascii=False)


def test_add_quote_is_parameterized(quotes_file):
    tricky = "'); DROP TABLE quotes; --"
    main.add_quote(tricky, "O'Reilly")
    assert main.load_quotes()[-1] == {"text": tricky, "author": "O'Reilly"}


def test_all_quotes_returns_valid_json(quotes_file):
    raw = main.all_quotes()
    assert json.loads(raw) == DATA
    assert "걸음" in raw  # ensure_ascii=False


def test_cli_db_error_exits_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(main, "QUOTES_FILE", tmp_path / "none.json")
    monkeypatch.setattr(main, "DB_FILE", tmp_path)  # 디렉터리 → DB 열기 실패
    assert main.main(["--search", "걸음"]) == 1
    assert "읽을 수 없습니다" in capsys.readouterr().err


def test_cli_broken_json_migration_exits_1(quotes_file, capsys):
    quotes_file.write_text("{broken", encoding="utf-8")
    assert main.main(["--search", "걸음"]) == 1
    assert "읽을 수 없습니다" in capsys.readouterr().err


def test_cli_invalid_utf8_migration_exits_1(quotes_file, capsys):
    quotes_file.write_bytes(b"\xff\xfe\x00broken")
    assert main.main(["--search", "걸음"]) == 1
    assert "읽을 수 없습니다" in capsys.readouterr().err


def test_cli_non_list_json_migration_exits_1(quotes_file, capsys):
    quotes_file.write_text("null", encoding="utf-8")
    assert main.main(["--search", "걸음"]) == 1
    assert "읽을 수 없습니다" in capsys.readouterr().err
    assert main.DB_FILE.exists()  # 스키마는 만들어졌지만 행은 없음(다음 실행 시 재시도)
    assert _db_rows(main.DB_FILE) == []
