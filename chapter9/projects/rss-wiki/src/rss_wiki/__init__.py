import sys


def main() -> None:
    from rss_wiki.cli import main as cli_main

    sys.exit(cli_main())
