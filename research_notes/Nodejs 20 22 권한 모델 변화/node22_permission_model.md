# Node.js 22.x Permission Model (22.0.0 to 22.23.3)

Sources used: the official v22 docs (permissions.html, cli.html, process.html) at latest-v22.x (v22.23.3) and at v22.0.0; CHANGELOG_V22.md; node `src/node_options.cc` at tags v22.12.0, v22.13.0 and the v22.x branch; and nodejs.org security release posts. Latest 22.x at time of research: **22.23.3 (2026-09-23, 'Jod' LTS)**.

## 1. CLI flags in v22 and the --experimental-permission to --permission rename

### Takeaway
In 22.0.0 to 22.12.0 the model was turned on with `--experimental-permission`. **22.13.0 (2025-01-07)** renamed it to `--permission`, backporting the stabilization PR #56201 that first landed in 23.5.0 (2024-12-19). `--experimental-permission` still works as an alias. The `--allow-*` flags in 22.x are `--allow-fs-read`, `--allow-fs-write`, `--allow-child-process`, `--allow-worker`, `--allow-addons` and `--allow-wasi`. There is no `--allow-net` and no `--permission-audit`.

### Cited Findings
- 22.13.0 (2025-01-07, LTS): Notable Change "Stabilize Permission Model: Upgrades the Permission Model status from Active Development to Stable", commit 57bb983215 "(SEMVER-MINOR) src,lib: stabilize permission model" (#56201) — [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.13.0)
- The same PR #56201 (commit efcc5d90c5) landed first in **23.5.0 (2024-12-19)** — [CHANGELOG_V23](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V23.md)
- At v22.12.0, `node_options.cc` defines only `AddOption("--experimental-permission", ...)`. At v22.13.0 it defines `AddOption("--permission", "enable the permission system", &EnvironmentOptions::permission, kAllowedInEnvvar, false)` plus `AddAlias("--experimental-permission", "--permission")`. The alias is still in the current v22.x branch — [node v22.12.0 src/node_options.cc](https://github.com/nodejs/node/blob/v22.12.0/src/node_options.cc), [node v22.13.0 src/node_options.cc](https://github.com/nodejs/node/blob/v22.13.0/src/node_options.cc), [v22.x branch](https://github.com/nodejs/node/blob/v22.x/src/node_options.cc)
- The current v22 cli.html has a History entry for `--permission`: "v22.13.0 Permission Model is now stable", "v20.0.0 Added in". It lists only `--permission`, `--allow-fs-read`, `--allow-fs-write`, `--allow-child-process`, `--allow-worker`, `--allow-addons` and `--allow-wasi` as permission flags. `--experimental-permission` no longer has its own doc section — [Node v22 CLI docs](https://nodejs.org/docs/latest-v22.x/api/cli.html#--permission)
- Text of `--permission` in v22: "Enable the Permission Model for current process. When enabled, the following permissions are restricted: File System (--allow-fs-read, --allow-fs-write), Child Process (--allow-child-process), Worker Threads (--allow-worker), WASI (--allow-wasi), Addons (--allow-addons)" — [Node v22 CLI docs](https://nodejs.org/docs/latest-v22.x/api/cli.html#--permission)
- Flag "Added in" versions from v22 cli.html:
  - `--allow-fs-read` and `--allow-fs-write`: v20.0.0
  - `--allow-child-process`: v20.0.0
  - `--allow-worker`: v20.0.0
  - `--allow-addons`: v21.6.0 / v20.12.0, so it is already present in 22.0.0
  - `--allow-wasi`: **v22.3.0** (commit 75e5612fae "src,permission: --allow-wasi & prevent WASI exec", #53124, 22.3.0 released 2024-06-11)

  — [Node v22 CLI docs](https://nodejs.org/docs/latest-v22.x/api/cli.html); [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.3.0)
- From 22.13.0, `initializePermission()` in `pre_execution.js` does the following when `--permission` is set:
  - replaces `process.binding` with a function that throws `ERR_ACCESS_DENIED`
  - calls `ObjectFreeze(require('path'))` ("Guarantee path module isn't monkey-patched to bypass permission model")
  - emits a `SecurityWarning` "The flag X must be used with extreme caution. It could invalidate the permission model." for `--allow-addons`, `--allow-child-process`, `--allow-wasi` and `--allow-worker`
  - warns "Passing a comma-separated list of paths is no longer valid" for `--allow-fs-*`

  — [node v22.13.0 lib/internal/process/pre_execution.js](https://github.com/nodejs/node/blob/v22.13.0/lib/internal/process/pre_execution.js)
- The 22.x changelog never mentions `allow-net` or `permission-audit`. The v22 cli.html has no such flags — [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md); [Node v22 CLI docs](https://nodejs.org/docs/latest-v22.x/api/cli.html)
- Security posts list the UDS/`--allow-net` permission bypasses (CVE-2026-21636, CVE-2026-21711, CVE-2026-48936) as affecting only 25.x or 26.x, and call `--allow-net` "experimental" there. This confirms network permission exists only on newer lines, not 22.x — [Jan 2026 security release](https://nodejs.org/en/blog/vulnerability/december-2025-security-releases); [Mar 2026 security release](https://nodejs.org/en/blog/vulnerability/march-2026-security-releases); [Jun 2026 security release](https://nodejs.org/en/blog/vulnerability/june-2026-security-releases)

### Inferences
- For 20 vs 22: 22.x has every 20.x flag plus `--allow-wasi` (22.3.0). `--allow-addons` arrived on 20.x in 20.12.0 too. 22.x never got network permission.
- Scripts that use `--experimental-permission` keep working on 22.13.0+ because of the alias. Docs and tests moved to `--permission` (commits 8718135a5d #56239 and 48b72f1195 #56685).

### Gaps
- No official doc states whether `--experimental-permission` will ever be removed or deprecated on 22.x. It is only kept as a silent alias in the source.
- I did not confirm whether the alias prints any deprecation warning. The source shows a plain `AddAlias`, which suggests it does not.

## 2. Stability index: 22.0.0 vs latest 22.x

### Takeaway
At 22.0.0 the Permission Model was **Stability: 1.1 - Active development** and printed an ExperimentalWarning. From **22.13.0** it is **Stability: 2 - Stable** ("no longer experimental"). It skipped the "1.2 Release candidate" level. Some individual flags (`--allow-child-process`, `--allow-worker`, `--allow-addons`, `--allow-wasi`) are still labelled 1.1 in the v22 cli.html.

### Cited Findings
- The v22.0.0 permissions.html, "Process-based permissions > Permission Model", says "Stability: 1.1 - Active development" and "The API exists behind a flag --experimental-permission". Its example output shows "ExperimentalWarning: Permission is an experimental feature" — [Node v22.0.0 permissions docs](https://nodejs.org/docs/v22.0.0/api/permissions.html)
- The v22.12.0 permissions.html still says "Stability: 1.1 - Active development" — [Node v22.12.0 permissions docs](https://nodejs.org/docs/v22.12.0/api/permissions.html)
- The latest v22 (22.23.3) permissions.html says "Stability: 2 - Stable". Its History says "v22.13.0: This feature is no longer experimental", and Added in is v20.0.0 — [Node v22 permissions docs](https://nodejs.org/docs/latest-v22.x/api/permissions.html)
- `--allow-fs-read` and `--allow-fs-write` History: "v22.13.0 Permission Model and --allow-fs flags are stable" — [Node v22 CLI docs](https://nodejs.org/docs/latest-v22.x/api/cli.html#--allow-fs-read)
- In the latest v22 cli.html, `--allow-child-process`, `--allow-worker`, `--allow-addons` and `--allow-wasi` each still show "Stability: 1.1 - Active development" — [Node v22 CLI docs](https://nodejs.org/docs/latest-v22.x/api/cli.html)
- The v22.0.0 permissions.html also lists the old module-based "Policies" as "Stability: 0 - Deprecated: Will be removed shortly". These are separate from the Permission Model — [Node v22.0.0 permissions docs](https://nodejs.org/docs/v22.0.0/api/permissions.html)

### Inferences
- "Stable" covers the core model and fs flags. The child-process, worker, addon and WASI escape-hatch flags were left at 1.1.

### Gaps
- None significant.

## 3. New or changed features across 22.x (addons, WASI, workers, child processes, has(), config file, audit)

### Takeaway
Main 22.x changes:
- 22.1.0: async errors on async APIs
- 22.3.0: `--allow-wasi`, and `process.chdir` is handled
- 22.7.0: Buffer support in `permission.has`
- 22.13.0: stable status and the rename
- 22.13.1: InternalWorker blocked (CVE)
- 22.16.0: more descriptive `ERR_ACCESS_DENIED`; experimental config file added
- 22.17.0: implicit read access to the entrypoint
- 22.18.0: flags propagate to spawned children via `NODE_OPTIONS`; `permission.has('addon')`
- 22.22.1: `permission.has` empty-parameter fix

The model still does not carry over to worker threads. `--allow-net` and a permission audit mode are absent.

### Cited Findings
- 22.0.0: "fs,permission: make handling of buffers consistent" (Tobias Nießen, #52348) — [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.0.0)
- 22.1.0 (2024-05-02): "src,permission: throw async errors on async APIs" (#52730) — [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.1.0)
- 22.2.0 (2024-05-15): "src,permission: resolve path on fs_permission" (#52761) — [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.2.0)
- 22.3.0 (2024-06-11): `--allow-wasi` and preventing WASI exec (#53124); "src,permission: handle process.chdir on pm" (#53175) — [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.3.0)
- 22.4.0: "src: fix permission inspector crash" (#53389) — [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.4.0)
- 22.5.0: "lib: remove path.resolve from permissions.js" (#53729); a doc addition explaining wildcards (#53664) — [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.5.0)
- 22.7.0 (2024-08-22): "lib,permission: support Buffer to permission.has" (#54104); "doc: remove module-based permission doc" (#54266), which removed the Policies docs; "doc: add note on weakness of permission model" (#54268) — [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.7.0)
- 22.13.0: "permission: ignore internalModuleStat on module loading" (#55797); "doc: fix relative path mention in --allow-fs" (#55791) — [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.13.0)
- 22.14.0 (2025-02-11): "doc: add note for features using InternalWorker with permission model" (#56706); "doc: add section about using npx with permission model" (#56539); "doc: add history info for Permission Model" (#56707) — [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.14.0)
- 22.16.0 (2025-05-21): "src,permission: make ERR_ACCESS_DENIED more descriptive" (#57585) — [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.16.0)
- 22.17.0 (2025-06-24): "Permissions: implicit allow-fs-read to entrypoint. Node.js permissions model now allows read access to the entry file by default" (#58579). The `--allow-fs-read` History says "v22.17.0 Entrypoints of your application are allowed to be read implicitly". The docs add that "The initializer module and custom --require modules has a implicit read permission" — [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.17.0); [Node v22 CLI docs](https://nodejs.org/docs/latest-v22.x/api/cli.html#--allow-fs-read)
- 22.18.0 (2025-07-31): "(SEMVER-MINOR) permission: propagate permission model flags on spawn" (#58853); "(SEMVER-MINOR) src,permission: add support to permission.has(addon)" (#58951); "src: pass resource on permission checks for spawn" (#58758); "enhance permission model debug" (#58898) — [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.18.0)
- `--allow-child-process` History, v22.18.0: "When spawning process with the permission model enabled. The flags are inherit to the child Node.js process through NODE_OPTIONS environment variable." The docs also say "child_process.fork() ... inherits the execution arguments from the parent process ... any child process created using child_process.fork() will automatically receive all relevant Permission Model flags. This behavior also applies to child_process.spawn(), but ... the flags are propagated via the NODE_OPTIONS environment variable" — [Node v22 CLI docs](https://nodejs.org/docs/latest-v22.x/api/cli.html#--allow-child-process)
- 22.22.1 (2026-03-05): "src,permission: fix permission.has on empty param" (#60674); "add debug log on is_tree_granted" (#60668) — [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.22.1)
- Workers: the v22.0.0 docs said "The model does not inherit to a child node process or a worker thread." The latest v22 docs say only "The model does not inherit to a worker thread." Child-process inheritance changed in 22.18.0 — [Node v22.0.0 permissions docs](https://nodejs.org/docs/v22.0.0/api/permissions.html); [Node v22 permissions docs](https://nodejs.org/docs/latest-v22.x/api/permissions.html)
- `process.permission.has(scope[, reference])` (Added in v20.0.0) returns a boolean. Without a reference it checks the global scope; for example `has('fs.read')` checks for ALL fs read permission. The documented scopes in the v22 process.html are `fs`, `fs.read`, `fs.write`, `child` and `worker`. The addon scope added in 22.18.0 is not listed there. The API "is available through the --permission flag" — [Node v22 process docs](https://nodejs.org/docs/latest-v22.x/api/process.html#processpermission)
- Config file: `--experimental-config-file` and `--experimental-default-config-file` (node.config.json) were added in **v22.16.0** at "Stability: 1.0 - Early development". The `nodeOptions` field supports "only flags that are allowed in NODE_OPTIONS". Priority order: NODE_OPTIONS/CLI, then the config file, then dotenv NODE_OPTIONS. The docs say "NEVER use untrusted configuration files." The v22 docs describe no permission-specific config section — [Node v22 CLI docs](https://nodejs.org/docs/latest-v22.x/api/cli.html#--experimental-config-fileconfig)
- `--permission` and `--allow-fs-*` are registered with `kAllowedInEnvvar` — [node v22.x src/node_options.cc](https://github.com/nodejs/node/blob/v22.x/src/node_options.cc)
- npx usage (doc added in 22.14.0): `npx --node-options="--permission --allow-fs-read=$(npm config get cache)" package-name` — [Node v22 permissions docs](https://nodejs.org/docs/latest-v22.x/api/permissions.html)

### Inferences
- Because `--permission` is NODE_OPTIONS-allowed, it can probably be set through `nodeOptions` in node.config.json on 22.16.0+. The v22 docs do not show this explicitly.
- 22.18.0 is the line where child processes started inheriting restrictions. Before that, a child spawned with `--allow-child-process` ran unrestricted.

### Gaps
- No `--permission-audit` or similar audit/report-only mode found in 22.x docs or changelog.
- No `--allow-net` in 22.x. Network permission belongs to 25.x+ (see the security posts above). I did not confirm the exact 25.x version it was added in.
- I did not verify a dedicated "permission" namespace in the node.config.json schema for 22.x.

## 4. Path syntax changes

### Takeaway
Comma-separated paths were removed in v20.7.0, before 22.0. 22.x requires one `--allow-fs-*` flag per path and warns if a single flag contains commas. Wildcards (`*`) are **still supported** in 22.x: everything after `*` is ignored, and existing directories get an implicit trailing `/*`. Relative paths were "not supported" per the 22.0.0 docs but are documented as supported (resolved against cwd) in later 22.x docs.

### Cited Findings
- `--allow-fs-read` and `--allow-fs-write` History: "v20.7.0 Paths delimited by comma (,) are no longer allowed." Text: "Multiple paths can be allowed using multiple --allow-fs-read flags", and "When passing a single flag with a comma a warning will be displayed" — [Node v22 CLI docs](https://nodejs.org/docs/latest-v22.x/api/cli.html#--allow-fs-write)
- The v22.0.0 permissions.html still (wrongly) listed "Paths delimited by comma (,)" as valid. That mention was removed by "doc: remove comma delimiter mention on permissions doc" (#58297) in 22.17.0 — [Node v22.0.0 permissions docs](https://nodejs.org/docs/v22.0.0/api/permissions.html); [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.17.0)
- Wildcards in latest v22: `--allow-fs-read=/home/test*` matches `/home/test/file1` and `/home/test2`. "After passing a wildcard character (*) all subsequent characters will be ignored", so `/home/*.js` acts like `/home/*`. An existing directory such as `/home/test/files` "will be treated as /home/test/files/*". To allow a folder that does not exist yet, include `/*` explicitly — [Node v22 permissions docs](https://nodejs.org/docs/latest-v22.x/api/permissions.html)
- Relative paths: the v22.0.0 "Limitations and Known Issues" said "Relative paths are not supported through the CLI (--allow-fs-*)". The latest v22 docs list valid arguments as `*`, relative paths (resolved against the cwd) and absolute paths. The relative-path doc fix is #55791 in 22.13.0, and path resolution is #52761 in 22.2.0 — [Node v22.0.0 permissions docs](https://nodejs.org/docs/v22.0.0/api/permissions.html); [Node v22 permissions docs](https://nodejs.org/docs/latest-v22.x/api/permissions.html); [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md)
- 22.0.0 Known Issue (later removed from the docs): "When the permission model is enabled, Node.js may resolve some paths differently than when it is disabled." — [Node v22.0.0 permissions docs](https://nodejs.org/docs/v22.0.0/api/permissions.html)

### Inferences
- I found no evidence that wildcard support was removed in 22.x. If a newer line removed it, that is not part of 22.x.
- CVE-2026-58043, the radix-tree prefix-boundary over-grant fixed in 22.23.2, relates to how the path/prefix tree matches grants.

### Gaps
- I did not confirm whether path matching semantics changed after the CVE-2026-58043 fix beyond "avoid granting radix split nodes".

## 5. Documented limitations and caveats in the v22 docs

### Takeaway
The v22 docs call the model a "seat belt", not a security boundary against malicious code. The documented caveats:
- Restrictions do not carry over to workers.
- Flags that read files before the environment is set up (`--env-file`, `--openssl-config`) are not subject to the model, and neither are V8 flags set via `v8.setFlagsFromString`.
- OpenSSL engines cannot be loaded at runtime.
- SQLite extensions cannot be loaded.
- Existing file descriptors bypass the model.
- The fs check covers only `node:fs` (e.g. not `node:sqlite`).
- Symlinks are followed outside the granted paths.

### Cited Findings
- "The permission model implements a "seat belt" approach, which prevents trusted code from unintentionally changing files or using resources that access has not explicitly been granted to. It does not provide security guarantees in the presence of malicious code." "Node.js trusts any code it is asked to run." — [Node v22 permissions docs](https://nodejs.org/docs/latest-v22.x/api/permissions.html)
- Restricted when `--permission` is on: fs module access, spawning processes, `node:worker_threads`, native addons, WASI, and the runtime inspector — [Node v22 permissions docs](https://nodejs.org/docs/latest-v22.x/api/permissions.html)
- Constraints, quoted from the docs:
  - "The model does not inherit to a worker thread."
  - "certain flags such as --env-file or --openssl-config are designed to read files before environment initialization. As a result, such flags are not subject to the rules of the Permission Model. The same applies for V8 flags that can be set via runtime through v8.setFlagsFromString."
  - "OpenSSL engines cannot be requested at runtime ... affecting the built-in crypto, https, and tls modules."
  - "Run-Time Loadable Extensions cannot be loaded ... affecting the sqlite module."
  - "Using existing file descriptors via the node:fs module bypasses the Permission Model."

  — [Node v22 permissions docs](https://nodejs.org/docs/latest-v22.x/api/permissions.html)
- The fs restriction applies to `node:fs` only and "does not guarantee that users will not be able to access the file system through other means, such as through the node:sqlite module." — [Node v22 permissions docs](https://nodejs.org/docs/latest-v22.x/api/permissions.html)
- Known issue: "Symbolic links will be followed even to locations outside of the set of paths that access has been granted to. Relative symbolic links may allow access to arbitrary files and directories ... you must ensure that no paths to which access has been granted contain relative symbolic links." — [Node v22 permissions docs](https://nodejs.org/docs/latest-v22.x/api/permissions.html)
- Denied operations throw `ERR_ACCESS_DENIED` with `permission` (e.g. 'FileSystemRead', 'ChildProcess', 'WorkerThreads', 'WASI') and `resource` properties. Native addons throw `ERR_DLOPEN_DISABLED` — [Node v22 permissions docs](https://nodejs.org/docs/latest-v22.x/api/permissions.html); [Node v22 CLI docs](https://nodejs.org/docs/latest-v22.x/api/cli.html#--allow-addons)

### Inferences
- The v22.0.0 docs had a shorter list: no WASI, no sqlite, no fd-bypass, no `v8.setFlagsFromString` note. These caveats were added during the 22.x line, mostly alongside the CVE fixes.

### Gaps
- I did not identify the exact 22.x versions where each individual caveat sentence first appeared.

## 6. Security releases and CVEs affecting the permission model on 22.x

### Takeaway
There were at least 15 permission-model CVEs on 22.x, fixed in 22.4.1, 22.13.1, 22.22.0, 22.22.2, 22.23.0 and 22.23.2. Most are Low. The High ones are:
- CVE-2025-23083: InternalWorker leak via `diagnostics_channel`
- CVE-2025-55130: symlink bypass
- CVE-2026-58043: radix-tree over-grant

### Cited Findings
- **22.4.1 (2024-07-08)**, all Low, affecting 20.x and 22.x:
  - CVE-2024-22018: `fs.lstat` bypasses the permission model (stats of unreadable files)
  - CVE-2024-36137: `fs.fchown`/`fchmod` bypass via a read-only fd
  - CVE-2024-37372: improper processing of Windows UNC paths

  The parallel 20.x fix is 20.15.1 — [July 2024 security release](https://nodejs.org/en/blog/vulnerability/july-2024-security-releases); [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.4.1)
- **22.13.1 (2025-01-21)**: CVE-2025-23083 (High), "Worker permission bypass via InternalWorker leak in diagnostics". `diagnostics_channel` could grab an internal worker's constructor and reuse it. It affected 20.x, 22.x and 23.x and was fixed in 20.18.2, 22.13.1 and 23.6.1 — [January 2025 security release](https://nodejs.org/en/blog/vulnerability/january-2025-security-releases)
- **22.22.0 (2026-01-13)**:
  - CVE-2025-55130 (High), "Bypass File System Permissions using crafted symlinks". Relative symlink chains escape `--allow-fs-read`/`--allow-fs-write`. Fix: "require full read and write to symlink APIs".
  - CVE-2025-55132 (Low), "fs.futimes() Bypasses Read-Only Permission Model". Fix: futimes is disabled under the permission model.

  Both affected 20.x/22.x/24.x/25.x and were fixed in 20.20.0, 22.22.0, 24.13.0 and 25.3.0 — [January 2026 security release](https://nodejs.org/en/blog/vulnerability/december-2025-security-releases); [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.22.0)
- **22.22.2 (2026-03-24)**, both affecting 20/22/24/25 and fixed in 20.20.2, 22.22.2, 24.14.1 and 25.8.2:
  - CVE-2026-21715 (Low): `fs.realpathSync.native()` lacked read checks, allowing file-existence disclosure and symlink-target resolution.
  - CVE-2026-21716 (Low): incomplete fix for CVE-2024-36137. Promise-based `FileHandle.chmod()`/`chown()` were unpatched.

  — [March 2026 security release](https://nodejs.org/en/blog/vulnerability/march-2026-security-releases)
- **22.23.0 (2026-06-18)**, both affecting 22/24/26 and fixed in 22.23.0, 24.17.0 and 26.3.1:
  - CVE-2026-48617 (Low): bypass via `process.report.writeReport()` path misvalidation (`process.chdir` handling).
  - CVE-2026-48935 (Low): `FileHandle.utimes()` in the promises API modified metadata on read-only paths.

  — [June 2026 security release](https://nodejs.org/en/blog/vulnerability/june-2026-security-releases)
- **22.23.2 (2026-07-29)**, all affecting 22/24/26 and fixed in 22.23.2, 24.18.1 and 26.5.1:
  - CVE-2026-58043 (High): radix-tree prefix boundary handling lets someone with access to one path read or write paths outside the allowlist. Fix: "avoid granting radix split nodes".
  - CVE-2026-56847 (Low): `trace_events.createTracing().enable()` writes outside `--allow-fs-write`.
  - CVE-2026-58039 (Low): `process.report` writes outside `--allow-fs-write`.

  — [July 2026 security release](https://nodejs.org/en/blog/vulnerability/july-2026-security-releases); [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.23.2)
- Not on 22.x: the UDS / `--allow-net` bypasses CVE-2026-21636 (25.x), CVE-2026-21711 (25.x) and CVE-2026-48936 (26.x) — [January 2026](https://nodejs.org/en/blog/vulnerability/december-2025-security-releases), [March 2026](https://nodejs.org/en/blog/vulnerability/march-2026-security-releases), [June 2026](https://nodejs.org/en/blog/vulnerability/june-2026-security-releases)
- The 22.23.3 (2026-09-23) changelog has no permission entries — [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md)

### Inferences
- The February 2024 permission CVEs (Buffer path traversal, etc., e.g. CVE-2024-21891/21896) predate 22.0.0 (2024-04-24). I did not verify them here. 22.0.0 shipped with "make handling of buffers consistent" (#52348), and later Buffer tests were added (#55734, 22.12.0).
- 20.x got its last permission fixes in 20.20.2 (March 2026). The June and July 2026 CVEs list only 22/24/26, consistent with 20.x being EOL by then. Several 22.x fixes (CVE-2026-48617, 48935, 58043, 56847, 58039) therefore have no 20.x counterpart.
- Recurring pattern: fd-based and promise-based APIs (fchmod/fchown → FileHandle.chmod/chown; futimes → FileHandle.utimes) and diagnostic writers (report, trace events) are the typical bypass surfaces.

### Gaps
- No CVSS scores were collected. Only the Node.js severity labels are given.
- I did not verify whether any December 2025 advisory (the URL slug "december-2025") was a separate release. Its content is the January 13, 2026 release.
