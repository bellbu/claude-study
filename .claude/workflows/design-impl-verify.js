export const meta = {
  name: 'quote-cli-sqlite-migration',
  description: 'Switch quote-cli storage from quotes.json to SQLite, then review, test and fix',
  phases: [
    { title: 'Implement', detail: 'one agent rewrites main.py storage + tests' },
    { title: 'Verify', detail: 'code review and test run in parallel' },
    { title: 'Fix', detail: 'apply confirmed issues, rerun tests' },
  ],
}

const DIR = 'C:\\Projects\\claude-study\\chapter6\\quote-cli'
const COMMON = `
Project: ${DIR} (Python 3.14, run with uv; tests: \`uv run pytest -q tests\`). main.py is a stdio MCP server (MCPServer "quote") launched by .mcp.json as \`uv run main.py\`, plus a \`--search <keyword>\` CLI option. Tests live in tests/test_search.py.
Rules: Do not commit or push. Do not delete quotes.json. Do not touch .claude/ or .mcp.json. If a hook blocks a command, stop and report it — do not work around it. Match the existing code style (Korean docstrings/messages, short comments like "# ② ...").
Note: main.py has CRLF line endings and may lack a trailing newline — prefer the Edit tool over regex/sed replacements, and confirm edits actually applied.`

const SPEC = `
Goal: replace JSON file storage with SQLite (stdlib sqlite3, no new dependencies).
- DB file: quotes.db next to main.py, module constant DB_FILE (tests monkeypatch it). Keep QUOTES_FILE only as the one-time migration source.
- Schema: table quotes(id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, author TEXT NOT NULL). Create if not exists.
- One-time migration: when the table is empty and quotes.json exists, import its entries in order (keep duplicates as-is). Never import twice.
- load_quotes() keeps returning a list of {"text","author"} dicts ordered by id, so get_random_quote / search_quotes / CLI keep working.
- add_quote inserts one row (parameterized SQL) and returns the same message format with the new count.
- quote://all resource keeps returning a JSON array string (ensure_ascii=False, indent=2) of {"text","author"}.
- search_quotes may filter in Python or SQL, but must keep current semantics: case-insensitive (casefold) substring match on text only, blank keyword -> ValueError.
- CLI error handling: replace the (OSError, json.JSONDecodeError) catch with sqlite3.Error/OSError as appropriate, still exit 1 with the "명언 파일을 읽을 수 없습니다" style message (adjust wording to DB if sensible).
- Close connections properly (use a helper/context manager; note sqlite3's "with conn" only commits, it does not close).
- Out of scope: input length validation for add_quote (user hasn't decided yet).
- Add quotes.db to a .gitignore in the project dir (create if missing).`

phase('Implement')
const impl = await agent(`${COMMON}\n${SPEC}\n
Implement this in main.py and update tests/test_search.py: fixture should point DB_FILE at a tmp_path db (and QUOTES_FILE at a tmp json for migration tests). Add tests for: migration from json on first use, no double migration on second load, add_quote inserts and returns count, quote://all returns valid JSON, CLI exit 1 on DB error. Keep all existing test intentions. Run \`uv run pytest -q tests\` until green. Return a concise summary: files changed, design choices, final pytest output line.`,
  { label: 'implement-sqlite', phase: 'Implement' })

phase('Verify')
const ISSUES = {
  type: 'object',
  properties: {
    issues: { type: 'array', items: { type: 'object', properties: {
      severity: { type: 'string', enum: ['high', 'medium', 'low'] },
      location: { type: 'string' },
      problem: { type: 'string' },
      fix: { type: 'string' },
    }, required: ['severity', 'location', 'problem', 'fix'] } },
    summary: { type: 'string' },
  },
  required: ['issues', 'summary'],
}
const [review, test] = await parallel([
  () => agent(`${COMMON}\n${SPEC}\nImplementer's summary:\n${impl}\n
Review main.py and tests/test_search.py against the spec above: correctness of migration (including double-import), connection handling, SQL injection, behavior regressions for MCP tools/resource/CLI, error handling, missing tests. Report only real problems with file:line and a concrete fix. Do not modify files.`,
    { label: 'review', phase: 'Verify', agentType: 'code-reviewer', schema: ISSUES }),
  () => agent(`${COMMON}\nDo not modify any files. In ${DIR} run, with PYTHONIOENCODING=utf-8 set:
1) uv run pytest -v tests
2) Using a scratch copy: copy main.py and quotes.json into a fresh temp directory (NOT the project dir), then from there run \`uv run --project "${DIR}" python main.py --search 걸음\`, \`--search 없는말\`, \`--search ""\` and run the --search 걸음 command a second time; report each output and exit code, and confirm quotes.db was created in the temp dir and that the second run did not duplicate results (row count unchanged — check with python -c using sqlite3).
3) Confirm running main.py with no args and stdin closed exits cleanly.
Report any failure as an issue.`,
    { label: 'test-run', phase: 'Verify', agentType: 'general-purpose', schema: ISSUES }),
])

const issues = [...(review?.issues || []), ...(test?.issues || [])]
const toFix = issues.filter(i => i.severity !== 'low')
log(`review: ${review?.issues?.length ?? 'n/a'} issues, test: ${test?.issues?.length ?? 'n/a'} issues; fixing ${toFix.length} high/medium (low left for report)`)

phase('Fix')
let fix = 'skipped: no high/medium issues'
if (toFix.length) {
  fix = await agent(`${COMMON}\n${SPEC}\nFix these issues found in review/testing (verify each is real first; skip and explain any that are not):\n${JSON.stringify(toFix, null, 2)}\nThen run \`uv run pytest -q tests\` and return: what you fixed, what you skipped and why, final pytest output line.`,
    { label: 'fix', phase: 'Fix' })
}

return { impl, review, test, fix }
