# Node.js 20.x Permission Model (v20.0.0 – v20.20.2): Baseline

Status note: Node.js 20 "Iron" started 2023-04-18, entered LTS 2023-10-24, maintenance 2024-10-22, and reached **End-of-Life on 2026-04-30** ([Node.js Release schedule.json](https://raw.githubusercontent.com/nodejs/Release/main/schedule.json)). The last 20.x release in the official changelog is **20.20.2 (2026-03-24)** ([CHANGELOG_V20.md](https://raw.githubusercontent.com/nodejs/node/main/doc/changelogs/CHANGELOG_V20.md)). The "latest-v20.x" docs render as "Node.js v20.20.2 Documentation" ([cli.html v20](https://nodejs.org/docs/latest-v20.x/api/cli.html)). As of 2026-10, 20.x is EOL and gets no more security fixes.

## 1. CLI flags in v20 and when each was introduced or changed

### Takeaway
In v20 the model is enabled only with `--experimental-permission`. There is no unflagged `--permission` in the v20 CLI docs. File-system, child-process and worker flags shipped in 20.0.0. Later 20.x minors added `--allow-addons` (20.12.0) and `--allow-wasi` (20.16.0), and changed the path syntax: multiple flags replaced comma lists in 20.7.0, and relative paths arrived in 20.12.0.

### Cited Findings
- `--experimental-permission`: Added in v20.0.0, Stability 1.1 Active development, no History entries. It restricts file system (`--allow-fs-read`, `--allow-fs-write`), child process (`--allow-child-process`), worker threads (`--allow-worker`), WASI (`--allow-wasi`) and addons (`--allow-addons`) — [Node v20 cli.html](https://nodejs.org/docs/latest-v20.x/api/cli.html)
- The v20 cli.html has no `--permission` flag entry. `--experimental-permission` is the only enabling flag — [Node v20 cli.html](https://nodejs.org/docs/latest-v20.x/api/cli.html)
- The model was introduced in 20.0.0 as "an experimental feature called the Permission Model", behind `--experimental-permission`, which "when enabled will restrict access to all available permissions". It was contributed by Rafael Gonzaga in PR #44004 (SEMVER-MINOR "src,process: add permission model") — [CHANGELOG_V20 (20.0.0)](https://raw.githubusercontent.com/nodejs/node/main/doc/changelogs/CHANGELOG_V20.md)
- 20.0.0 also dropped `process.permission.deny` before release (PR #47335). The final v20 runtime API has only `has()` — [CHANGELOG_V20 (20.0.0)](https://raw.githubusercontent.com/nodejs/node/main/doc/changelogs/CHANGELOG_V20.md)
- `--allow-fs-read` / `--allow-fs-write`: Added in v20.0.0. History entry: "v20.7.0 – Paths delimited by comma (`,`) are no longer allowed." Multiple paths now take repeated flags, and a single flag that contains a comma prints a warning — [Node v20 cli.html](https://nodejs.org/docs/latest-v20.x/api/cli.html)
- 20.7.0 commit: "src,permission: add multiple allow-fs-* flags" (Carlos Espa, PR #49047) — [CHANGELOG_V20 (20.7.0)](https://raw.githubusercontent.com/nodejs/node/main/doc/changelogs/CHANGELOG_V20.md)
- `--allow-child-process`: Added in v20.0.0. Without it, spawning throws `ERR_ACCESS_DENIED` with `permission: 'ChildProcess'` — [Node v20 cli.html](https://nodejs.org/docs/latest-v20.x/api/cli.html)
- `--allow-worker`: Added in v20.0.0. Without it, `new Worker()` throws `ERR_ACCESS_DENIED` with `permission: 'WorkerThreads'` — [Node v20 cli.html](https://nodejs.org/docs/latest-v20.x/api/cli.html)
- `--allow-addons`: **Added in v20.12.0**. Without it, loading a native addon throws `ERR_DLOPEN_DISABLED` ("Cannot load native addon because loading addons is disabled."), not `ERR_ACCESS_DENIED` — [Node v20 cli.html](https://nodejs.org/docs/latest-v20.x/api/cli.html)
- 20.12.0 "Permission Model changes" notable section: the new `--allow-addons` flag (PR #51183, SEMVER-MINOR), and "relative paths are now supported through the `--allow-fs-*` flags", e.g. `--allow-fs-read=./index.js` (PR #50758, "port path.resolve to C++", SEMVER-MINOR) — [CHANGELOG_V20 (20.12.0)](https://raw.githubusercontent.com/nodejs/node/main/doc/changelogs/CHANGELOG_V20.md)
- `--allow-wasi`: **Added in v20.16.0**. Without it, `new WASI()` throws `ERR_ACCESS_DENIED` with `permission: 'WASI'` — [Node v20 cli.html](https://nodejs.org/docs/latest-v20.x/api/cli.html)
- 20.16.0 commit: "(SEMVER-MINOR) src,permission: --allow-wasi & prevent WASI exec" (PR #53124) — [CHANGELOG_V20 (20.16.0)](https://raw.githubusercontent.com/nodejs/node/main/doc/changelogs/CHANGELOG_V20.md)
- 20.6.0: "src,permission: restrict by default when pm enabled" (PR #48907) and "drop repl autocomplete when pm enabled" (PR #48920) — [CHANGELOG_V20 (20.6.0)](https://raw.githubusercontent.com/nodejs/node/main/doc/changelogs/CHANGELOG_V20.md). PR #48907 restricts fs, child processes, worker_threads and the inspector by default under the flag — [nodejs/node#48907](https://github.com/nodejs/node/pull/48907)
- 20.3.1 (security): "src,permission: restrict inspector when pm enabled" — [CHANGELOG_V20 (20.3.1)](https://raw.githubusercontent.com/nodejs/node/main/doc/changelogs/CHANGELOG_V20.md)
- 20.5.1 (security): "lib,permission: restrict process.binding when pm is enabled" — [CHANGELOG_V20 (20.5.1)](https://raw.githubusercontent.com/nodejs/node/main/doc/changelogs/CHANGELOG_V20.md)

### Inferences
- `--allow-addons` (20.12.0) and `--allow-wasi` (20.16.0) are SEMVER-MINOR features that landed in 20.x while it was LTS. They were very likely backported from the Current line (21.x/22.x). The changelog entries are labeled SEMVER-MINOR in LTS releases, but the notes do not name the originating major.
- Before 20.12.0, native addons were not covered by a dedicated allow flag. The 20.12.0 notes call the flag new, but the exact pre-20.12 behavior for addons is not documented here.
- The comma-separator removal in 20.7.0 is a breaking-ish syntax change inside one major (allowed because the feature is experimental).

### Gaps
- No unflagged `--permission` alias in v20 docs. Confirming that `--permission` was never backported to 20.x would need checking every 20.x changelog for it. A grep of CHANGELOG_V20.md for "allow-"/"permission" found no such entry.
- I did not verify the exact originating Current-line versions of `--allow-addons` and `--allow-wasi`.

## 2. Stability index in v20

### Takeaway
The model shipped in 20.0.0 as Stability 1 (Experimental). It was reclassified to **Stability 1.1 – Active development** in 20.10.0, and the final v20 docs show 1.1 on the model and on every `--allow-*` flag.

### Cited Findings
- The v20 permissions.html shows "Permission Model – Added in: v20.0.0 – Stability: 1.1 – Active development". There is no History table for the section — [Node v20 permissions.html](https://nodejs.org/docs/latest-v20.x/api/permissions.html)
- Each of `--experimental-permission`, `--allow-fs-read`, `--allow-fs-write`, `--allow-child-process`, `--allow-worker`, `--allow-addons` and `--allow-wasi` is labeled "Stability: 1.1 – Active development" — [Node v20 cli.html](https://nodejs.org/docs/latest-v20.x/api/cli.html)
- 20.10.0 commit: "doc: move permission model to Active Development" (PR #50068) — [CHANGELOG_V20 (20.10.0)](https://raw.githubusercontent.com/nodejs/node/main/doc/changelogs/CHANGELOG_V20.md)
- 20.18.3: "doc: add history info for Permission Model" (PR #56707) — [CHANGELOG_V20 (20.18.3)](https://raw.githubusercontent.com/nodejs/node/main/doc/changelogs/CHANGELOG_V20.md). The rendered v20 page still has no History table, only "Added in" — [Node v20 permissions.html](https://nodejs.org/docs/latest-v20.x/api/permissions.html)
- Policies (`--experimental-policy`), the separate module-integrity mechanism, are marked Stability 0 – Deprecated ("Will be removed shortly") in the v20 docs — [Node v20 permissions.html](https://nodejs.org/docs/latest-v20.x/api/permissions.html)

### Inferences
- The model was never Stability 2 (Stable) in 20.x.

### Gaps
- The changelog does not state whether 20.0.0 docs used "Stability: 1 – Experimental" or "1.0". The PR title implies a change from plain Experimental to 1.1.

## 3. Runtime API (`process.permission.has`) and ERR_ACCESS_DENIED

### Takeaway
v20 exposes only `process.permission.has(scope[, reference])`, available when the flag is set. The scopes are `fs`, `fs.read`, `fs.write`, `child` and `worker`; there is no `wasi` or `addon` scope in the v20 docs. A denied operation throws `ERR_ACCESS_DENIED`, with `permission` and `resource` properties on the error. A denied addon load throws `ERR_DLOPEN_DISABLED` instead.

### Cited Findings
- `process.permission` (Added in v20.0.0) is available "only through the `--experimental-permission` flag". `process.permission.has(scope[, reference])` (Added in v20.0.0) takes `scope` <string> and an optional `reference` <string>, and returns <boolean>. With no reference, a global scope is assumed: `has('fs.read')` checks for *all* FS read permission — [Node v20 process.html](https://nodejs.org/docs/latest-v20.x/api/process.html)
- Available scopes in v20: `fs` (all file system), `fs.read`, `fs.write`, `child` (child process spawning), `worker` (worker thread spawning) — [Node v20 process.html](https://nodejs.org/docs/latest-v20.x/api/process.html)
- Examples: `process.permission.has('fs.read', './README.md')` and `process.permission.has('fs.write', '/home/rafaelgss/protected-folder')` — [Node v20 process.html](https://nodejs.org/docs/latest-v20.x/api/process.html); [Node v20 permissions.html](https://nodejs.org/docs/latest-v20.x/api/permissions.html)
- 20.2.0: "permission: resolve reference to absolute path only for fs permission" (PR #47930) — [CHANGELOG_V20](https://raw.githubusercontent.com/nodejs/node/main/doc/changelogs/CHANGELOG_V20.md)
- 20.18.0: "lib,permission: support Buffer to permission.has" (PR #54104) — [CHANGELOG_V20 (20.18.0)](https://raw.githubusercontent.com/nodejs/node/main/doc/changelogs/CHANGELOG_V20.md)
- Error shape when the entry file isn't allowed: `Error: Access to this API has been restricted … { code: 'ERR_ACCESS_DENIED', permission: 'FileSystemRead', resource: '/home/user/index.js' }`. The docs say the initializer module itself must be allowed (e.g. `--allow-fs-read=/path/to/index.js`) — [Node v20 permissions.html](https://nodejs.org/docs/latest-v20.x/api/permissions.html); [Node v20 cli.html](https://nodejs.org/docs/latest-v20.x/api/cli.html)
- `permission` values in the docs: `FileSystemRead`, `ChildProcess`, `WorkerThreads`, `WASI`. `FileSystemWrite` is the matching write operation name used in the `--allow-fs-write` text — [Node v20 cli.html](https://nodejs.org/docs/latest-v20.x/api/cli.html)
- 20.14.0: "src,permission: throw async errors on async APIs" (PR #52730). Async fs APIs now report denial through the async error path instead of throwing synchronously — [CHANGELOG_V20 (20.14.0)](https://raw.githubusercontent.com/nodejs/node/main/doc/changelogs/CHANGELOG_V20.md)
- 20.18.0: "src,permission: handle process.chdir on pm" (PR #53175) — [CHANGELOG_V20 (20.18.0)](https://raw.githubusercontent.com/nodejs/node/main/doc/changelogs/CHANGELOG_V20.md)

### Inferences
- The "async errors" change in 20.14.0 is a behavior change for code that catches denial errors from callback or promise fs APIs. Before 20.14.0 those likely threw synchronously.

### Gaps
- The v20 docs do not document a `wasi` or `addon` scope for `has()`, even though `--allow-wasi` and `--allow-addons` exist. It is unverified whether the implementation accepts such scopes in late 20.x.
- The v20 docs do not specify the return value of `has()` when the model is disabled. `process.permission` is described as available only with the flag.

## 4. Path allowlist syntax in v20

### Takeaway
In the final v20 docs, multiple paths are given by repeating `--allow-fs-read` / `--allow-fs-write`. Commas were removed in 20.7.0 and now trigger a warning. `*` grants everything, and a trailing `*` works as a prefix wildcard; anything after `*` is ignored. An existing directory gets an implicit `/*`. Relative paths are supported from 20.12.0.

### Cited Findings
- `*` allows all FileSystemRead or FileSystemWrite operations. Multiple paths use multiple flags, e.g. `--allow-fs-read=/tmp/ --allow-fs-read=/home/.gitignore` — [Node v20 permissions.html](https://nodejs.org/docs/latest-v20.x/api/permissions.html); [Node v20 cli.html](https://nodejs.org/docs/latest-v20.x/api/cli.html)
- "Paths delimited by comma (`,`) are no longer allowed. When passing a single flag with a comma a warning will be displayed" (change in v20.7.0) — [Node v20 cli.html](https://nodejs.org/docs/latest-v20.x/api/cli.html)
- Wildcards: `--allow-fs-read=/home/test*` matches `/home/test/file1` and `/home/test2`. Anything after `*` is ignored, so `/home/*.js` acts like `/home/*`. A directory that exists when the model initializes gets an implicit wildcard (`/home/test/files` becomes `/home/test/files/*`). For a directory that doesn't exist yet, the `*` must be given explicitly — [Node v20 permissions.html](https://nodejs.org/docs/latest-v20.x/api/permissions.html)
- Relative paths: supported from 20.12.0 (`--allow-fs-read=./index.js`) — [CHANGELOG_V20 (20.12.0)](https://raw.githubusercontent.com/nodejs/node/main/doc/changelogs/CHANGELOG_V20.md). 20.19.5 has a doc fix, "doc: fix relative path mention in --allow-fs" (PR #55791) — [CHANGELOG_V20 (20.19.5)](https://raw.githubusercontent.com/nodejs/node/main/doc/changelogs/CHANGELOG_V20.md)
- Wildcard fixes: 20.11.1 "permission: fix wildcard when children > 1" (PR #51209, part of the CVE-2024-21890 fix). 20.17.0 doc: "add additional explanation to the wildcard section" (PR #53664) — [CHANGELOG_V20](https://raw.githubusercontent.com/nodejs/node/main/doc/changelogs/CHANGELOG_V20.md)
- Using with npx (doc added in 20.19.5, PR #56539): `npx --node-options="--permission --allow-fs-read=$(npm prefix -g)" package-name` or `--allow-fs-read=$(npm config get cache)` — [Node v20 permissions.html](https://nodejs.org/docs/latest-v20.x/api/permissions.html); [CHANGELOG_V20 (20.19.5)](https://raw.githubusercontent.com/nodejs/node/main/doc/changelogs/CHANGELOG_V20.md)

### Inferences
- **Doc inconsistency (flag for the report):** the v20 permissions page backports text from newer lines. The npx section uses `--permission`, which the v20 cli.html does not list (v20 needs `--experimental-permission`). The v20.x branch source of permissions.md still says `--allow-fs-*` accept "a comma-delimited list of paths" ([v20.x permissions.md source](https://raw.githubusercontent.com/nodejs/node/v20.x/doc/api/permissions.md)), which contradicts the cli.html History (commas disallowed since 20.7.0) ([Node v20 cli.html](https://nodejs.org/docs/latest-v20.x/api/cli.html)). Treat cli.html plus the changelog as authoritative.
- Between 20.0.0 and 20.6.x, the comma-separated form (`--allow-fs-read=/a,/b`) was the documented way to pass several paths.

### Gaps
- No official statement on whether `--allow-fs-read=*` combined with specific paths is meaningful.
- Windows path and UNC specifics are only in the CVE-2024-37372 fix (see section 6).

## 5. Documented limitations and caveats (v20 docs)

### Takeaway
The v20 docs call the model a "seat belt", not a security boundary against malicious code. Permissions are not inherited by child processes or workers. Pre-init file reads (`--env-file`, `--openssl-config`, V8 flags) bypass it, and so do existing file descriptors. OpenSSL engines are blocked. Symlinks are followed outside the allowlist.

### Cited Findings
- "seat belt" approach: it "prevents trusted code from unintentionally changing files or using resources that access has not explicitly been granted to." It "does not provide security guarantees in the presence of malicious code. Malicious code can bypass the permission model" — [Node v20 permissions.html](https://nodejs.org/docs/latest-v20.x/api/permissions.html). This weakness note was added in 20.18.0 (PR #54268, "doc: add note on weakness of permission model") — [CHANGELOG_V20](https://raw.githubusercontent.com/nodejs/node/main/doc/changelogs/CHANGELOG_V20.md)
- Constraints, verbatim bullets in the v20 docs — [Node v20 permissions.html](https://nodejs.org/docs/latest-v20.x/api/permissions.html):
  - "The model does not inherit to a child node process or a worker thread."
  - Restricted features: native modules, child process, worker threads, inspector protocol, file system access, WASI.
  - `--env-file`, `--openssl-config`, and V8 flags set at runtime via `v8.setFlagsFromString` read before or outside initialization, so they are "not subject to the rules of the Permission Model".
  - "OpenSSL engines cannot be requested at runtime when the Permission Model is enabled, affecting the built-in crypto, https, and tls modules."
  - "Using existing file descriptors via the `node:fs` module bypasses the Permission Model."
- Only Known Issue listed: "Symbolic links will be followed even to locations outside of the set of paths that access has been granted to. Relative symbolic links may allow access to arbitrary files and directories." Users must make sure granted paths contain no relative symlinks — [Node v20 permissions.html](https://nodejs.org/docs/latest-v20.x/api/permissions.html)
- The page says the model doesn't guarantee that the file system can't be reached "through other means, such as through the `node:sqlite` module" — [Node v20 permissions.html](https://nodejs.org/docs/latest-v20.x/api/permissions.html)
- 20.1.0 doc change: "clarify fs permissions only affect fs module" (PR #47782) — [CHANGELOG_V20](https://raw.githubusercontent.com/nodejs/node/main/doc/changelogs/CHANGELOG_V20.md)
- Worker and InternalWorker: 20.18.2 fixed CVE-2025-23083 ("throw on InternalWorker use when permission model is enabled", High), and 20.18.3 added "doc: add note for features using `InternalWorker` with permission model" (PR #56706) — [CHANGELOG_V20](https://raw.githubusercontent.com/nodejs/node/main/doc/changelogs/CHANGELOG_V20.md). This blocks features that rely on InternalWorker (such as module customization hooks or loaders) under the model.
- Related hardening in 20.x: `v8.writeHeapSnapshot` and `process.report` brought under permission (20.5.0, PR #48564). 20.11.0: "permission: do not create symlinks if target is relative" (PR #49156). 20.19.5: "permission: ignore internalModuleStat on module loading" (PR #55797) — [CHANGELOG_V20](https://raw.githubusercontent.com/nodejs/node/main/doc/changelogs/CHANGELOG_V20.md)
- 20.16.0: "src: fix permission inspector crash" (PR #53389) — [CHANGELOG_V20](https://raw.githubusercontent.com/nodejs/node/main/doc/changelogs/CHANGELOG_V20.md)

### Inferences
- The `node:sqlite` caveat on the v20 page is probably a doc backport artifact: `node:sqlite` is a 22.x-era module. This is unverified for 20.x.
- The InternalWorker restriction (20.18.2+) means `--experimental-loader` / `module.register` hooks likely fail under `--experimental-permission` on late 20.x. The changelog names only "InternalWorker", so the exact list of affected features is my reading of it.

### Gaps
- The rendered v20 permissions page does not visibly include the InternalWorker note added by PR #56706. I could not confirm where that note sits in the v20 docs.
- No v20 doc text describes inspector behavior beyond listing it as restricted. `--inspect` interaction is documented only via CVE-2023-30587 and the 20.3.1 fix.

## 6. Security releases and CVEs affecting the permission model on 20.x

### Takeaway
The 20.x line fixed roughly two dozen permission-model CVEs across security releases from 20.3.1 (June 2023) to 20.20.2 (March 2026). Most are path traversal (Buffer, Uint8Array, monkey-patching), uncovered fs APIs (statfs, mkdtemp, lstat, fchown/fchmod, futimes, openAsBlob, watchFile, realpath.native, fs/promises) and escape hatches (inspector, process.binding, OpenSSL engines, InternalWorker, symlinks).

### Cited Findings (all from [CHANGELOG_V20.md](https://raw.githubusercontent.com/nodejs/node/main/doc/changelogs/CHANGELOG_V20.md))
- **20.3.1 (2023-06-20):** CVE-2023-30584 path traversal bypass (High); CVE-2023-30587 bypass via inspector (High); CVE-2023-30582 unauthorized file watching (`fs.watchFile`) (Medium); CVE-2023-30583 bypass via `fs.openAsBlob()` (Medium); CVE-2023-30586 bypass via arbitrary OpenSSL engines (Medium). Also policy CVE-2023-30581 (High, policy, not PM).
- **20.5.1 (2023-08-09):** CVE-2023-32558 `process.binding()` path-traversal bypass (High); CVE-2023-32004 path traversal in a Buffer (High); CVE-2023-32005 `fs.statfs` bypass (Low); CVE-2023-32003 `fs.mkdtemp()`/`mkdtempSync()` bypass (Low). Policy CVEs in the same release: CVE-2023-32002, CVE-2023-32006, CVE-2023-32559.
- **20.8.1 (2023-10-13):** CVE-2023-39331 improper path traversal protection (High); CVE-2023-39332 path traversal through a path stored in a Uint8Array (High). Details are in the [October 2023 Security Releases](https://nodejs.org/en/blog/vulnerability/october-2023-security-releases/) post, as referenced in the changelog. Policy CVE-2023-38552 in the same release.
- **20.11.1 (2024-02-14):** CVE-2024-21891 multiple bypasses via improper path traversal sequence sanitization (Medium); CVE-2024-21890 improper wildcard handling in `--allow-fs-read`/`--allow-fs-write` (Medium); CVE-2024-21896 path traversal by monkey-patching Buffer internals (High).
- **20.15.1 (2024-07-08):** CVE-2024-22018 `fs.lstat` bypass (Low); CVE-2024-36137 `fs.fchown`/`fchmod` bypass (Low; fix "disable fchmod/fchown when pm enabled"); CVE-2024-37372 improper UNC path processing on Windows (Low).
- **20.18.2 (2025-01-21):** CVE-2025-23083 throw on InternalWorker use when the model is enabled (High).
- **20.20.0 (2026-01-13):** CVE-2025-55130 symlink APIs now require full read and write permission; CVE-2025-55132 `futimes` disabled when the model is enabled.
- **20.20.2 (2026-03-24, last 20.x):** CVE-2026-21716 permission check added to `lib/fs/promises`; CVE-2026-21715 permission check added to `realpath.native`.

### Inferences
- The CVE-2025-55132 and CVE-2024-36137 fixes show a pattern: fd-based APIs (`futimes`, `fchmod`, `fchown`) are **disabled outright** under the model, not path-checked, which fits the "existing file descriptors bypass" caveat.
- Since 20.x is EOL (2026-04-30), any permission-model CVE disclosed after 20.20.2 will not be fixed on 20.x.

### Gaps
- Severity ratings for CVE-2025-55130, CVE-2025-55132, CVE-2026-21715 and CVE-2026-21716 are not shown in the 20.x changelog lines I extracted. Check the January 2026 and March 2026 security release blog posts.
- I did not fetch the individual security blog posts; the CVE descriptions above are the changelog's one-line summaries.
