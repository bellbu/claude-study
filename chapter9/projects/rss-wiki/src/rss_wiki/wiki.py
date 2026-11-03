"""Wiki generation: per-article summary Markdown (PRD 4.4). Reads the DB only."""

import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from rss_wiki.db import DatabaseError

MAX_SLUG_CHARS = 60
RECENT_LIMIT = 20
_RESERVED_NAMES = frozenset(
    ["con", "prn", "aux", "nul"]
    + [f"com{i}" for i in range(1, 10)]
    + [f"lpt{i}" for i in range(1, 10)]
)

_NON_WORD = re.compile(r"\W+")
_YEAR_MONTH = re.compile(r"^\d{4}-\d{2}$")


def slugify(title: str | None, article_id: int) -> str:
    """File-name slug: normalized title (max 60 chars) + ``-{article_id}``.

    The id suffix keeps slugs unique for identical titles and stays deterministic.
    """
    text = unicodedata.normalize("NFKC", title or "").lower()
    text = _NON_WORD.sub("-", text).strip("-")
    text = text[:MAX_SLUG_CHARS].rstrip("-")
    return f"{text or 'article'}-{article_id}"


def article_relpath(row) -> PurePosixPath:
    """``articles/YYYY/MM/<slug>.md``; year-month from published_at, else fetched_at."""
    month = (row["published_at"] or "")[:7]
    if not _YEAR_MONTH.match(month):
        month = (row["fetched_at"] or "")[:7]
    if not _YEAR_MONTH.match(month):
        return PurePosixPath("articles", "unknown", f"{slugify(row['title'], row['id'])}.md")
    year, _, mm = month.partition("-")
    return PurePosixPath("articles", year, mm, f"{slugify(row['title'], row['id'])}.md")


def _quote(value: str | None) -> str:
    # A JSON string is a valid YAML double-quoted scalar, so colons/quotes/newlines are safe.
    return "null" if value is None else json.dumps(value, ensure_ascii=False)


def one_line(text: str | None) -> str:
    """Collapse all whitespace (including CR/LF) into single spaces; None -> ''."""
    return " ".join((text or "").split())


def _source_link(url: str | None) -> str:
    """Markdown link with a CommonMark angle-bracket destination; ``-`` if no url."""
    if not url:
        return "-"
    label = re.sub(r"([\\\[\]])", r"\\\1", one_line(url))
    dest = url.replace("<", "%3C").replace(">", "%3E")
    dest = re.sub(r"\s", "%20", dest)
    return f"[{label}](<{dest}>)"


def render_article(row, tags: list[str]) -> str:
    """Render front matter and body for one summarized article (LF line endings)."""
    title = row["title"]
    front = [
        "---",
        f"title: {_quote(title)}",
        f"url: {_quote(row['url'])}",
        f"feed: {_quote(row['feed_name'])}",
        f"published: {_quote(row['published_at'])}",
        f"summarized: {_quote(row['summarized_at'])}",
        f"model: {_quote(row['model'])}",
        f"tags: {json.dumps(sorted(tags), ensure_ascii=False)}",
        "---",
    ]
    key_points = json.loads(row["key_points"]) if row["key_points"] else []
    items = [one_line(point) for point in key_points]
    tldr = (row["tldr"] or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    body = [
        f"# {one_line(title) or '(제목 없음)'}",
        "",
        "## TL;DR",
        "",
        tldr,
        "",
        "## 핵심 포인트",
        "",
        *[f"- {item}" for item in items if item],
        "",
        "## 원문",
        "",
        _source_link(row["url"]),
    ]
    return "\n".join([*front, "", *body]) + "\n"


def load_done_articles(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Articles with a done summary joined with their feed name, ordered by id."""
    cur = conn.execute(
        """
        SELECT a.id, a.title, a.url, a.published_at, a.fetched_at,
               f.name AS feed_name, s.tldr, s.key_points, s.model, s.summarized_at
        FROM articles a
        JOIN summaries s ON s.article_id = a.id
        LEFT JOIN feeds f ON f.id = a.feed_id
        WHERE s.status = 'done'
        ORDER BY a.id
        """
    )
    cur.row_factory = sqlite3.Row
    return cur.fetchall()


def load_article_tags(conn: sqlite3.Connection, article_id: int) -> list[str]:
    """Sorted tag names of one article."""
    rows = conn.execute(
        "SELECT t.name FROM article_tags at JOIN tags t ON t.id = at.tag_id "
        "WHERE at.article_id = ? ORDER BY t.name",
        (article_id,),
    ).fetchall()
    return [r[0] for r in rows]


def _write_if_changed(path: Path, text: str) -> None:
    data = text.encode("utf-8")
    if not (path.is_file() and path.read_bytes() == data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def _load_done_with_tags(conn: sqlite3.Connection) -> list[tuple[sqlite3.Row, list[str]]]:
    return [(row, load_article_tags(conn, row["id"])) for row in load_done_articles(conn)]


def _write_article_files(wiki_dir: Path, items: list[tuple[sqlite3.Row, list[str]]]) -> list[Path]:
    paths: list[Path] = []
    for row, tags in items:
        path = Path(wiki_dir) / article_relpath(row)
        _write_if_changed(path, render_article(row, tags))
        paths.append(path)
    return paths


def write_articles(conn: sqlite3.Connection, wiki_dir: Path) -> list[Path]:
    """Write one Markdown file per done article; return paths in id order.

    Files are UTF-8 with LF endings regardless of OS. Unchanged files are not rewritten.
    """
    return _write_article_files(wiki_dir, _load_done_with_tags(conn))


def topic_filenames(tags: list[str]) -> dict[str, str]:
    """Tag -> ``<name>.md``. Same rule as slugify (no id suffix); collisions and
    Windows reserved names get ``-2``, ``-3``... in tag-name order (deterministic)."""
    result: dict[str, str] = {}
    used: set[str] = set()
    for tag in sorted(set(tags)):
        text = unicodedata.normalize("NFKC", tag).lower()
        text = _NON_WORD.sub("-", text).strip("-")
        text = text[:MAX_SLUG_CHARS].rstrip("-") or "tag"
        name, n = text, 1
        while name in used or name in _RESERVED_NAMES:
            n += 1
            name = f"{text}-{n}"
        used.add(name)
        result[tag] = f"{name}.md"
    return result


def _recency_key(row) -> tuple[str, int]:
    return (row["published_at"] or row["fetched_at"] or "", row["id"])


def _escape_label(text: str) -> str:
    return re.sub(r"([\\\[\]])", r"\\\1", text)


def _entry_line(row, prefix: str) -> str:
    title = _escape_label(one_line(row["title"])) or "(제목 없음)"
    return f"- [{title}](<{prefix}{article_relpath(row).as_posix()}>) — {one_line(row['tldr'])}"


def render_topic(tag: str, entries: list) -> str:
    """Topic page: article links newest first, each with a one-line TL;DR."""
    ordered = sorted(entries, key=_recency_key, reverse=True)
    lines = [f"# {one_line(tag)}", "", f"글 {len(ordered)}건", ""]
    lines += [_entry_line(row, "../") for row in ordered]
    return "\n".join(lines) + "\n"


def render_index(tag_counts: list[tuple[str, str, int]], recent: list) -> str:
    """Index page. ``tag_counts`` items are (tag, topic filename, article count)."""
    tags = sorted(tag_counts, key=lambda t: (-t[2], t[0]))
    newest = sorted(recent, key=_recency_key, reverse=True)[:RECENT_LIMIT]
    lines = ["# rss-wiki", "", "## 태그", ""]
    lines += [f"- [{_escape_label(one_line(t))}](<topics/{fn}>) ({n})" for t, fn, n in tags] or ["(없음)"]
    lines += ["", "## 최근 요약", ""]
    lines += [_entry_line(row, "") for row in newest] or ["(없음)"]
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class BuildResult:
    articles: int
    topics: int
    removed: int


def _prune(wiki_dir: Path, keep: set[Path]) -> int:
    """Delete ``.md`` files under articles/ and topics/ not in ``keep``; drop empty article dirs."""
    removed = 0
    for sub in ("articles", "topics"):
        root = wiki_dir / sub
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.md")):
            if path.is_file() and path not in keep:
                path.unlink()
                removed += 1
    articles = wiki_dir / "articles"
    if articles.is_dir():
        for d in sorted((p for p in articles.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
            if not any(d.iterdir()):
                d.rmdir()
    return removed


def build_wiki(conn: sqlite3.Connection, wiki_dir: Path) -> BuildResult:
    """Regenerate article pages, topic pages and index.md from the DB (idempotent)."""
    wiki_dir = Path(wiki_dir)
    try:
        items = _load_done_with_tags(conn)
    except sqlite3.Error as exc:
        raise DatabaseError(f"위키 조회 실패: {exc}") from exc
    rows = [row for row, _ in items]
    by_tag: dict[str, list] = {}
    for row, tags in items:
        for tag in tags:
            by_tag.setdefault(tag, []).append(row)
    article_paths = _write_article_files(wiki_dir, items)
    names = topic_filenames(list(by_tag))
    keep = set(article_paths)
    for tag, entries in by_tag.items():
        path = wiki_dir / "topics" / names[tag]
        _write_if_changed(path, render_topic(tag, entries))
        keep.add(path)
    counts = [(tag, names[tag], len(entries)) for tag, entries in by_tag.items()]
    index = wiki_dir / "index.md"
    _write_if_changed(index, render_index(counts, rows))
    removed = _prune(wiki_dir, keep)
    return BuildResult(articles=len(article_paths), topics=len(by_tag), removed=removed)
