"""명언 출력 CLI.

사용법:
    python quote.py          무작위 명언 하나 출력
    python quote.py --list   전체 명언 목록 출력
"""

import argparse
import json
import random
import sys
from pathlib import Path

QUOTES_FILE = Path(__file__).with_name("quotes.json")


def load_quotes(path=QUOTES_FILE):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def format_quote(quote):
    return f'"{quote["text"]}" - {quote["author"]}'


def main():
    # Windows 콘솔에서 한글이 깨지지 않도록 UTF-8로 출력
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="명언을 출력합니다.")
    parser.add_argument("--list", action="store_true", help="전체 명언 목록을 출력합니다.")
    args = parser.parse_args()

    quotes = load_quotes()
    if not quotes:
        print("등록된 명언이 없습니다.", file=sys.stderr)
        return 1

    if args.list:
        for i, quote in enumerate(quotes, start=1):
            print(f"{i}. {format_quote(quote)}")
    else:
        print(format_quote(random.choice(quotes)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
