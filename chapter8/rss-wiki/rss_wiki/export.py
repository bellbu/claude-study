"""현재 위키 페이지를 Markdown 파일로 내보낸다 (백업·다른 도구에서 열람용)."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def slugify(name: str) -> str:
    slug = INVALID.sub("-", name.strip())
    slug = re.sub(r"[\s-]+", "-", slug).strip("-.")
    return slug or "topic"


def export_markdown(conn: sqlite3.Connection, out_dir: str | Path) -> list[Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = conn.execute(
        "SELECT t.id, t.name, t.description, w.content, w.created_at FROM topics t "
        "JOIN wiki_revisions w ON w.topic_id = t.id AND w.is_current = 1 "
        "WHERE t.merged_into IS NULL AND t.status != 'hidden' ORDER BY t.name"
    ).fetchall()
    names: dict[int, str] = {}
    used: set[str] = set()
    for r in rows:
        slug = slugify(r["name"])
        base, n = slug, 2
        while slug.lower() in used:
            slug, n = f"{base}-{n}", n + 1
        used.add(slug.lower())
        names[r["id"]] = f"{slug}.md"

    def relink(match: re.Match) -> str:
        target = names.get(int(match.group(2)))
        return f"[{match.group(1)}]({target})" if target else match.group(1)

    written = []
    for r in rows:
        body = re.sub(r"\[([^\]]+)\]\(/topics/(\d+)\)", relink, r["content"])
        text = f"# {r['name']}\n\n> {r['description']}  \n> 갱신: {r['created_at']}\n\n{body}"
        path = out / names[r["id"]]
        path.write_text(text, encoding="utf-8")
        written.append(path)
    index = "# RSS Wiki\n\n" + "\n".join(f"- [{r['name']}]({names[r['id']]})" for r in rows) + "\n"
    (out / "index.md").write_text(index, encoding="utf-8")
    return written
