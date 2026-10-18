# Node.js permission model: runtime behavior and API differences, 20.x vs 22.x

Method note: I verified everything against the `doc/api/*.md` sources on the `v20.x` and `v22.x` branches of nodejs/node (these are what nodejs.org/docs/latest-v20.x and latest-v22.x render from), `doc/changelogs/CHANGELOG_V20.md` / `CHANGELOG_V22.md` on `main`, PR metadata and diffs from the GitHub API, and the `src/` and `lib/` sources on both branches. Latest releases are **v20.20.2 (2026-03-24, the last 20.x)** and **v22.23.3 (2026-09-23)** — [CHANGELOG_V20](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V20.md#20.20.2); [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.23.3)

## Q1. Entrypoint / `-r` preload implicit read access (22.17.0, PR #58579)

### Takeaway
**Confirmed.** In 22.17.0 and later, the main entrypoint and every `-r`/`--require` module are added to the fs-read allow list automatically. 20.x never got this: its docs still say the initializer module "also needs to be allowed". There is one catch. The v22 permissions page still shows the old `ERR_ACCESS_DENIED` example for `node --permission index.js`, which contradicts the new behavior on the same page.

### Cited Findings
- 22.17.0 changelog lists "**src,permission**: implicit allow-fs-read to app entrypoint (Rafael Gonzaga) #58579". It is also a notable change: "Node.js permissions model now allows read access to the entry file by default." — [CHANGELOG_V22 22.17.0](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.17.0)
- PR #58579 was merged 2025-06-07 with labels `notable-change`, `permission`. Body: "automatically includes in the allow-fs-read list all the app's entrypoints. `--require` and user entry point". The request came from @ErickWendel. It is **not** labelled semver-minor — [PR #58579](https://github.com/nodejs/node/pull/58579)
- v22 cli.md `--allow-fs-read` History: "v22.17.0 … Entrypoints of your application are allowed to be read implicitly." The body says: "The initializer module and custom `--require` modules has a implicit read permission", with the example `node --permission -r custom-require.js -r custom-require-2.js index.js` — [Node v22 CLI --allow-fs-read](https://nodejs.org/docs/latest-v22.x/api/cli.html#--allow-fs-read)
- The v22 permissions page says: "By default the entrypoints of your application are included in the allowed file system read list", and gives a `-r /path/to/custom-require.js` example — [Node v22 permissions](https://nodejs.org/docs/latest-v22.x/api/permissions.html#file-system-permissions)
- **Doc inconsistency (v22):** the same v22 permissions page still opens with `$ node --permission index.js` → `Error: Access to this API has been restricted … code: 'ERR_ACCESS_DENIED', permission: 'FileSystemRead', resource: '/home/user/index.js'`. That example describes pre-22.17 behavior. — [Node v22 permissions](https://nodejs.org/docs/latest-v22.x/api/permissions.html#permission-model)
- **Doc typo (v22):** the cli.md example uses `process.has('fs.read', 'index.js'); // true`. It should be `process.permission.has` — [Node v22 CLI --allow-fs-read](https://nodejs.org/docs/latest-v22.x/api/cli.html#--allow-fs-read)
- v20 cli.md `--allow-fs-read`: "The initializer module also needs to be allowed. Consider the following example: `$ node --experimental-permission index.js` → ERR_ACCESS_DENIED". Its History has only the v20.7.0 comma-removal entry — [Node v20 CLI --allow-fs-read](https://nodejs.org/docs/latest-v20.x/api/cli.html#--allow-fs-read)
- PR #58579 does not appear anywhere in CHANGELOG_V20 (grep of the full file), so it was not backported to 20.x — [CHANGELOG_V20](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V20.md)

### Inferences
- Because the PR is not semver-minor, it shipped as a behavior relaxation inside a minor release. Code that *expected* `ERR_ACCESS_DENIED` on the entrypoint (for example a test asserting that `node --permission index.js` fails) will behave differently on 22.17.0+.
- For a script to be portable across 20.x and 22.x, it should still pass `--allow-fs-read=<entry>` explicitly. Doing so is harmless on 22.17+.

### Gaps
- The docs do not say whether ESM `--import` preload modules or `--loader` targets also get implicit read. The docs and PR mention only `-r`/`--require` and the entrypoint. I did not verify `--import`.

## Q2. Child process propagation on spawn/spawnSync (22.18.0, PR #58853); worker non-inheritance

### Takeaway
**Confirmed, with nuance.** In 22.18.0 and later, `spawn()` and `spawnSync()` (any API routed through `normalizeSpawnArguments`) inject the parent's permission flags into the child's `NODE_OPTIONS`. They skip this when `--permission` is already present in the child's args or `NODE_OPTIONS`. `fork()` already inherited them via `execArgv` before this change, including in 20.x. The v20 doc's claim that the model "does not inherit to a child node process" is therefore misleading for `fork()`. Worker threads do not inherit in either line.

### Cited Findings
- 22.18.0 changelog: "**(SEMVER-MINOR)** **permission**: propagate permission model flags on spawn (Rafael Gonzaga) #58853" — [CHANGELOG_V22 22.18.0](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.18.0)
- PR #58853 (merged 2025-07-02, semver-minor, notable-change): "Previously, only child_process.fork propagated the exec arguments (execvArgs) to the child process. This commit adds support for spawn and spawnSync to propagate permission model flags — except when they are already provided explicitly via arguments or through NODE_OPTIONS." — [PR #58853](https://github.com/nodejs/node/pull/58853)
- v22 cli.md `--allow-child-process` History: "v22.18.0 … When spawning process with the permission model enabled. The flags are inherit to the child Node.js process through NODE_OPTIONS environment variable." The body says `fork()` "will automatically receive all relevant Permission Model flags. This behavior also applies to `child_process.spawn()`, but … the flags are propagated via the `NODE_OPTIONS` environment variable". The docs name only `spawn()`, not `spawnSync()` — [Node v22 CLI --allow-child-process](https://nodejs.org/docs/latest-v22.x/api/cli.html#--allow-child-process)
- v22.x `lib/child_process.js` implementation: inside `normalizeSpawnArguments`, `if (permission.isEnabled()) copyPermissionModelFlagsToEnv(env, 'NODE_OPTIONS', args)`. That function returns early if `args.includes('--permission')` or the target env's `NODE_OPTIONS` already contains `--permission`. Otherwise it copies every `process.execArgv` entry that starts with one of `--allow-fs-read`, `--allow-fs-write`, `--allow-addons`, `--allow-child-process`, `--allow-wasi`, `--allow-worker`, `--permission` — [v22.x lib/child_process.js](https://github.com/nodejs/node/blob/v22.x/lib/child_process.js); [v22.x lib/internal/process/permission.js](https://github.com/nodejs/node/blob/v22.x/lib/internal/process/permission.js)
- v20.x `lib/child_process.js` has no permission-related code at all. The only "permission" matches are in the MIT licence header — [v20.x lib/child_process.js](https://github.com/nodejs/node/blob/v20.x/lib/child_process.js)
- v20 child_process docs: `fork()` `execArgv` "**Default:** `process.execArgv`" — [Node v20 child_process](https://nodejs.org/docs/latest-v20.x/api/child_process.html#child_processforkmodulepath-args-options)
- v20 permissions constraints: "The model does not inherit to a child node process or a worker thread." — [Node v20 permissions](https://nodejs.org/docs/latest-v20.x/api/permissions.html#permission-model-constraints)
- v22 permissions constraints: "The model does not inherit to a worker thread." (The child-process wording was removed.) — [Node v22 permissions](https://nodejs.org/docs/latest-v22.x/api/permissions.html#permission-model-constraints)
- PR #58853 does not appear in CHANGELOG_V20 — [CHANGELOG_V20](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V20.md)

### Inferences
- **Runtime break risk on 22.18+:** a 22.18+ parent running with `--permission --allow-child-process` that spawns `node child.js` now produces a restricted child. Before 22.18, and on all 20.x, that child ran unrestricted. Children that relied on free fs access will start throwing `ERR_ACCESS_DENIED`. The flags are injected into `NODE_OPTIONS` for *every* spawned command, including non-Node binaries. Only Node processes read it, but any Node grandchild launched through a shell or `npx` will also inherit it.
- The early-return check matches only the literal string `--permission`. If the parent was started with the legacy alias `--experimental-permission` and `process.execArgv` keeps that spelling, the copy loop (which matches `startsWith('--permission')`) would copy the `--allow-*` flags but not the enabling flag. **Unverified.** I did not run it, and I don't know whether the option parser rewrites the alias in `execArgv`.
- The v20 statement "does not inherit to a child node process" was inaccurate for `fork()` even on 20.x, because fork reuses `process.execArgv` by default. I infer this from the default and from PR #58853's "Previously, only child_process.fork propagated…". I did not test it on a 20.x binary.

### Gaps
- No official doc explicitly lists `spawnSync`/`execFile`/`exec` as covered. The PR body says spawn and spawnSync, and the code path covers everything that calls `normalizeSpawnArguments`.

## Q3. `process.permission.has()` signature and scopes; 'addon' scope

### Takeaway
The documented signature `has(scope[, reference])` → boolean is **identical in both lines**. Both process.html pages list the same five scopes: `fs`, `fs.read`, `fs.write`, `child`, `worker`. **Confirmed:** the `'addon'` scope was added in 22.18.0 (#58951), but **v22 process.html does not document it**, and neither line documents `wasi` or `inspector`, which exist in source. 22.22.1 (#60674) changed what `has('fs.read'|'fs.write')` returns when called with no reference.

### Cited Findings
- v20 and v22 process.md `process.permission.has(scope[, reference])`: `added: v20.0.0`, with no `changes:` entries in either. `scope {string}`, `reference {string}`, Returns `{boolean}`. Available scopes: "`fs`, `fs.read`, `fs.write`, `child`, `worker`". The only differences are that v22 says "available through the `--permission` flag" and v20 says `--experimental-permission`, plus "Type: {Object}" formatting — [Node v20 process](https://nodejs.org/docs/latest-v20.x/api/process.html#processpermissionhasscope-reference); [Node v22 process](https://nodejs.org/docs/latest-v22.x/api/process.html#processpermissionhasscope-reference)
- 22.18.0: "**(SEMVER-MINOR)** **src,permission**: add support to `permission.has(addon)` #58951". PR body: "This fixes the `permission.has('addon')` when `--allow-addons` is passed". The diff adds an `AddonPermission` class with "a single state — Once denied, it's always denied" and applies the deny in `env.cc` when `!options_->allow_addons` — [CHANGELOG_V22 22.18.0](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.18.0); [PR #58951](https://github.com/nodejs/node/pull/58951)
- Source scopes. v20.x `permission_base.h`: `fs`, `fs.read`, `fs.write`, `child`, `wasi`, `worker`, `inspector`. v22.x adds `addon`, and each scope now carries a suggested flag string. There is **no `net` scope in either line**, although the main-branch PR diff references `NET_PERMISSIONS`, so `net` exists only on main/newer lines — [v20.x permission_base.h](https://github.com/nodejs/node/blob/v20.x/src/permission/permission_base.h); [v22.x permission_base.h](https://github.com/nodejs/node/blob/v22.x/src/permission/permission_base.h)
- Buffer as `reference`: "lib,permission: support Buffer to permission.has #54104" is in 20.18.0 (CHANGELOG_V20) and 22.7.0. The v22 JS wrapper validates `reference` as string or Buffer, with "TODO: add support for WHATWG URLs and Uint8Arrays". process.md still types `reference` as `{string}` only — [CHANGELOG_V20](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V20.md#20.18.0); [v22.x internal/process/permission.js](https://github.com/nodejs/node/blob/v22.x/lib/internal/process/permission.js)
- 22.22.1: "src,permission: fix permission.has on empty param #60674" (merged 2025-11-16). The diff in `fs_permission.cc` makes `has('fs.read')` / `has('fs.write')` with an empty reference return exactly `allow_all_in_` / `allow_all_out_`, instead of the previous compound expression that also consulted the granted tree. The test flags were changed to add `--allow-fs-write=.` — [CHANGELOG_V22 22.22.1](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.22.1); [PR #60674](https://github.com/nodejs/node/pull/60674)
- #58951 and #60674 do not appear in CHANGELOG_V20 — [CHANGELOG_V20](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V20.md)

### Inferences
- On 20.x, `process.permission.has('addon')` has no matching scope in `PermissionScope`, so it cannot report addon status meaningfully. On 22.18+ it returns `false` unless `--allow-addons` is passed. I have not run this, so I can't say whether 20.x returns false or throws for an unknown scope.
- Since 22.22.1, `has('fs.write')` with no reference means "is *all* write allowed (`*`)?". This matches the documented "check if the process has ALL file system read permissions". On 20.x and on 22.x before 22.22.1, code that relied on the buggy result may have seen `true` with only partial grants. That is inferred from the diff and was not tested.

### Gaps
- No official doc lists `addon`, `wasi`, or `inspector` as `has()` scopes. They exist only in the changelog and source.

## Q4. ERR_ACCESS_DENIED message changes (22.16.0) and error codes/properties

### Takeaway
**Confirmed:** 22.16.0 (#57585) appended a flag suggestion to the message. errors.html is unchanged between the lines and documents neither the message text nor the `permission`/`resource` properties. Those properties appear only in examples in cli.html and permissions.html. Native addons use `ERR_DLOPEN_DISABLED` in both lines.

### Cited Findings
- 22.16.0: "**src,permission**: make ERR\_ACCESS\_DENIED more descriptive (Rafael Gonzaga) #57585" — [CHANGELOG_V22 22.16.0](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.16.0)
- PR #57585 (merged 2025-04-03; labels c++, permission; **not** semver-minor or notable): "adds a suggestion flag (if exists) when ERR_ACCESS_DENIED is thrown". The new message format is `"Access to this API has been restricted. %s"`, where the suffix is `"Use <flag> to manage permissions."`. The test expects `message: 'Access to this API has been restricted. Use --allow-fs-read to manage permissions.'`, with `code: 'ERR_ACCESS_DENIED'`, `permission: 'FileSystemRead'`, `resource: <path>`. The `fs` and `inspector` scopes have an empty flag, so they get no suggestion — [PR #57585](https://github.com/nodejs/node/pull/57585)
- Source confirmation: v20.x `CreateAccessDeniedError` calls `ERR_ACCESS_DENIED(env->isolate())`, which uses the default message "Access to this API has been restricted". v22.x calls `GetErrorFlagSuggestion(perm)` and passes it as the formatted message — [v20.x permission.cc](https://github.com/nodejs/node/blob/v20.x/src/permission/permission.cc); [v22.x permission.cc](https://github.com/nodejs/node/blob/v22.x/src/permission/permission.cc)
- errors.md `ERR_ACCESS_DENIED` has the same text in both lines: "A special type of error that is triggered whenever Node.js tries to get access to a resource restricted by the Permission Model." No properties are listed — [Node v20 errors](https://nodejs.org/docs/latest-v20.x/api/errors.html#err_access_denied); [Node v22 errors](https://nodejs.org/docs/latest-v22.x/api/errors.html#err_access_denied)
- Example property values in the docs: `permission: 'FileSystemRead'` with `resource`, `permission: 'ChildProcess'`, `permission: 'WorkerThreads'`. Addons throw `ERR_DLOPEN_DISABLED` ("Cannot load native addon because loading addons is disabled."). These are the same in both lines — [Node v22 CLI](https://nodejs.org/docs/latest-v22.x/api/cli.html#--allow-child-process); [Node v20 CLI](https://nodejs.org/docs/latest-v20.x/api/cli.html#--allow-addons)
- The doc examples in **both** lines still show the old message text without the suggestion suffix — [Node v22 permissions](https://nodejs.org/docs/latest-v22.x/api/permissions.html)

### Inferences
- `err.code` and `err.permission` are stable across 20 and 22. `err.message` equality checks break at 22.16.0. Because the PR is a patch-level change in a minor release, nothing in the semver labels warns about it.

### Gaps
- I did not verify the exact message for every scope at runtime, such as the WASI and worker suggestion text. It is derived from the macro table, for example "Use --allow-worker to manage permissions."

## Q5. Policy (`--experimental-policy`) deprecation and removal

### Takeaway
**Confirmed.** It was doc-deprecated in 22.0.0 and 20.13.0 (#52602), removed in **22.2.0** (#52583, 2024-05-15), and its docs were removed in 22.7.0 (#54266). It was **never removed from 20.x**. 20.x cli.md still has `--experimental-policy` marked "Stability: 0 – Deprecated: Will be removed shortly", and the Policies section is still in permissions.md. It never had a DEP-numbered deprecation code in either line.

### Cited Findings
- "doc: deprecate --experimental-policy (RafaelGSS) #52602" appears in CHANGELOG_V22 under 22.0.0 (2024-04-24) and in CHANGELOG_V20 under 20.13.0 (2024-05-07) — [CHANGELOG_V22 22.0.0](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.0.0); [CHANGELOG_V20 20.13.0](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V20.md#20.13.0)
- "lib,src: remove --experimental-policy (Rafael Gonzaga) #52583" is under 22.2.0 (2024-05-15). PR #52583 was merged 2024-05-07 with labels notable-change, deprecations, policy; Summary: "We are dropping the `--experimental-policy` feature from Node.js." Refs issue #52575 — [CHANGELOG_V22 22.2.0](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.2.0); [PR #52583](https://github.com/nodejs/node/pull/52583)
- "doc: remove module-based permission doc #54266" is under 22.7.0 (2024-08-22) — [CHANGELOG_V22 22.7.0](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.7.0)
- v20 docs: cli.md `--experimental-policy` (added v11.8.0) has "Stability: 0 - Deprecated: Will be removed shortly." permissions.md still contains "Module-based permissions › Policies" ("Stability: 0 - Deprecated: Will be removed shortly"), with integrity checks, dependency redirection, and scopes — [Node v20 CLI](https://nodejs.org/docs/latest-v20.x/api/cli.html#--experimental-policy); [Node v20 permissions](https://nodejs.org/docs/latest-v20.x/api/permissions.html#policies)
- v22 docs: there is no `--experimental-policy` section in cli.md and no policy section in permissions.md. deprecations.md has no policy entry (the only "policy" match is the unrelated `--force-node-api-uncaught-exceptions-policy`). In v20 deprecations, DEP0111 (`process.binding`) says it "is unavailable when [policies] or the [permission model] are enabled" — [Node v22 deprecations](https://nodejs.org/docs/latest-v22.x/api/deprecations.html); [Node v20 deprecations DEP0111](https://nodejs.org/docs/latest-v20.x/api/deprecations.html#dep0111-processbinding)

### Inferences
- On 22.2.0+, passing `--experimental-policy` should fail at startup as an unknown/bad option, because the option was removed from source. On 20.x it is still accepted. I did not run either binary.
- Policy was in v22.0.0–22.1.x as doc-deprecated, so "22.x has no policy" is true only from 22.2.0 on.

### Gaps
- I did not confirm the exact startup error text on 22.2.0+ when `--experimental-policy` is passed.

## Q6. Documented limitations in v20 vs v22 docs

### Takeaway
The seat-belt statement, symlink caveat, fd bypass, `--env-file`/`--openssl-config`/`v8.setFlagsFromString` exemption, OpenSSL engine block, and `node:sqlite` fs caveat are **word-for-word identical** in both lines. The v22 docs make two real changes: they drop "child node process" from the inheritance constraint, and they add "Run-Time Loadable Extensions cannot be loaded … affecting the sqlite module". The v20 docs contain back-ported text that does not match 20.x behavior: a `node:sqlite` mention, an `npx --node-options="--permission"` example, and the stale comma-delimiter text.

### Cited Findings
- Both lines: "The permission model implements a "seat belt" approach, which prevents trusted code from unintentionally changing files or using resources that access has not explicitly been granted to. It does not provide security guarantees in the presence of malicious code." The note was added via #54268 in 22.7.0 and 20.18.0 — [Node v22 permissions](https://nodejs.org/docs/latest-v22.x/api/permissions.html); [Node v20 permissions](https://nodejs.org/docs/latest-v20.x/api/permissions.html); [CHANGELOG_V22 22.7.0](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.7.0); [CHANGELOG_V20 20.18.0](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V20.md#20.18.0)
- Both lines, under constraints: `--env-file`/`--openssl-config` "are not subject to the rules of the Permission Model. The same applies for V8 flags that can be set via runtime through `v8.setFlagsFromString`". "OpenSSL engines cannot be requested at runtime". "Using existing file descriptors via the `node:fs` module bypasses the Permission Model." — same sources
- Both lines, under Limitations: "Symbolic links will be followed even to locations outside of the set of paths that access has been granted to. Relative symbolic links may allow access to arbitrary files and directories…" — same sources
- **v22 only:** "Run-Time Loadable Extensions cannot be loaded when the Permission Model is enabled, affecting the sqlite module." — [Node v22 permissions](https://nodejs.org/docs/latest-v22.x/api/permissions.html#permission-model-constraints)
- **Both lines** say the model "does not guarantee that users will not be able to access the file system through other means, such as through the `node:sqlite` module." The sentence appears even in v20, where `node:sqlite` does not exist — [Node v20 permissions](https://nodejs.org/docs/latest-v20.x/api/permissions.html#file-system-permissions)
- **v20 doc anomalies:** v20 permissions.md has an `npx --node-options="--permission"` section, but v20 cli.md has no `--permission` flag (only `--experimental-permission`). It still lists "Paths delimited by comma (`,`)" as valid even though cli.md History says commas have not been allowed since v20.7.0. Its example still prints `ExperimentalWarning: Permission is an experimental feature` — [Node v20 permissions](https://nodejs.org/docs/latest-v20.x/api/permissions.html); [Node v20 CLI --allow-fs-read](https://nodejs.org/docs/latest-v20.x/api/cli.html#--allow-fs-read)
- Comma text removal in v22 docs: "doc: remove comma delimiter mention on permissions doc #58297" in 22.17.0 — [CHANGELOG_V22 22.17.0](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.17.0)
- 20.x continued to receive permission CVE fixes up to its final releases, for example 20.20.1 (CVE-2026-21716 "include permission check on lib/fs/promises", CVE-2026-21715 "add permission check to realpath.native") and 20.20.0 (CVE-2025-55132 "disable futimes when permission model is enabled", CVE-2025-55130 "require full read and write to symlink APIs") — [CHANGELOG_V20](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V20.md#20.20.1)

### Inferences
- The `node:sqlite` caveat and the `npx --permission` example in v20 docs look like doc back-ports that were not adapted to 20.x. On 20.x the `npx` example would need `--experimental-permission`. The earlier report's statement that the v20 sqlite mention is a back-port artifact is consistent with this. That `node:sqlite` is absent from 20.x is my background knowledge (it was added in v22.5.0); I did not re-verify it here.
- Since 20.20.0 (CVE-2025-55130), symlink APIs require full read and write. That narrows, but does not remove, the documented symlink caveat. The caveat text was not updated in either line.

### Gaps
- I did not compare the security-release blog posts for 2026 (June/July) in this pass. They are outside this runtime-API scope and are covered by the earlier report.

---

### Verdict on earlier report claims (summary for the writer)
- **Confirmed:** 22.17.0 entrypoint/`-r` implicit read (#58579); 22.18.0 spawn propagation (#58853) and worker non-inheritance; 22.18.0 `addon` scope (#58951) absent from process.html; 22.22.1 `has()` empty-param fix (#60674); 22.16.0 ERR_ACCESS_DENIED message change (#57585); Policy deprecated 22.0.0/20.13.0 (#52602), removed 22.2.0 (#52583), docs removed 22.7.0 (#54266); seat-belt note via #54268 in 22.7.0/20.18.0; comma doc fix #58297 in 22.17.0; limitations list; ERR_DLOPEN_DISABLED for addons.
- **Correction/nuance:** "20.x child process ran unrestricted" is true for `spawn`/`exec*`. For `fork()`, flags were already inherited via the default `execArgv`, per PR #58853's own description. Propagation also covers `spawnSync` according to the PR, though the docs name only `spawn()`.
- **Add:** the v22 permissions.html still shows a pre-22.17 entrypoint `ERR_ACCESS_DENIED` example; the v22 cli.html has a `process.has(...)` typo; the doc examples in both lines show the old error message; neither process.html documents `wasi`, `inspector`, `addon` scopes or Buffer references; v20 docs contain a `--permission`-based npx example that cannot work on 20.x; and the spawn propagation guard matches only the literal `--permission` (a possible alias interaction, unverified).
