# Node.js permission model: enabling flags, stability levels, and per-flag introduction versions (20.x vs 22.x)

Scope note: verified on 2026-10-17 against the rendered docs (latest-v20.x = **v20.20.2**, latest-v22.x = **v22.23.3**), the raw `doc/api/*.md` and `src/node_options.cc` / `lib/internal/process/pre_execution.js` on the `v20.x` / `v22.x` branches and on release tags, CHANGELOG_V20/V21/V22/V23 on `main`, and PR diffs. (Branch heads: `v20.x` has `node_version.h` 20.20.3-pre and `v22.x` has 22.23.4-pre, so branch docs match the latest released docs except for any unreleased commits.)

## Q1. Which enabling flag does each line support, and from which version? Is the 22.13.0 stabilization (PR #56201) confirmed?

### Takeaway
20.x registers only `--experimental-permission`, from 20.0.0 through the final 20.20.x. 22.0.0–22.12.x also register only `--experimental-permission`. In **22.13.0 (2025-01-07)** PR #56201 renamed the option to `--permission` and kept `--experimental-permission` as an alias. The v22 docs History, the CHANGELOG_V22 "Notable Changes" section, and the source code all confirm this. **The earlier report's claims on this point are confirmed.**

### Cited Findings
- The v20.x `src/node_options.cc` registers only `AddOption("--experimental-permission", "enable the permission system", ...)`. There is no `--permission` option and no alias — [node_options.cc v20.x](https://github.com/nodejs/node/blob/v20.x/src/node_options.cc)
- v20 cli.html (v20.20.2) has a `--experimental-permission` entry ("Added in: v20.0.0", Stability 1.1) and **no `--permission` entry**. Its NODE_OPTIONS allow-list includes only `--experimental-permission` — [Node v20 cli.html](https://nodejs.org/docs/latest-v20.x/api/cli.html)
- v20 permissions.html (v20.20.2) says "The API exists behind a flag `--experimental-permission`" and uses `node --experimental-permission index.js` in its examples — [Node v20 permissions.html](https://nodejs.org/docs/latest-v20.x/api/permissions.html)
- **New finding (doc inconsistency in v20):** the v20.x `permissions.md` npx section uses `npx --node-options="--permission" package-name` and `--node-options="--permission --allow-fs-read=$(npm prefix -g)"`, even though 20.x does not register `--permission`. This section came from the backport of "doc: add section about using npx with permission model" (#56539) in a late 20.19.x release — [permissions.md v20.x](https://raw.githubusercontent.com/nodejs/node/v20.x/doc/api/permissions.md); [CHANGELOG_V20](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V20.md)
- The v22.12.0 tag registers `AddOption("--experimental-permission", ...)` only. The v22.13.0 tag registers `AddOption("--permission", ...)` followed by `AddAlias("--experimental-permission", "--permission")` — [node_options.cc v22.12.0](https://github.com/nodejs/node/blob/v22.12.0/src/node_options.cc); [node_options.cc v22.13.0](https://github.com/nodejs/node/blob/v22.13.0/src/node_options.cc)
- The v22.x branch head still contains `AddOption("--permission", ...)` + `AddAlias("--experimental-permission", "--permission")` — [node_options.cc v22.x](https://github.com/nodejs/node/blob/v22.x/src/node_options.cc)
- The PR #56201 diff adds `AddAlias("--experimental-permission", "--permission")`, renames the cli.md section `### --experimental-permission` to `### --permission` with the history line "Permission Model is now stable.", replaces `--experimental-permission` with `--permission` in examples and the NODE_OPTIONS list, and removes `emitExperimentalWarning('Permission')` and the doc's `ExperimentalWarning: Permission is an experimental feature` example — [PR #56201](https://github.com/nodejs/node/pull/56201)
- CHANGELOG_V22, "2025-01-07, Version 22.13.0 'Jod' (LTS)", Notable Changes: "#### Stabilize Permission Model — Upgrades the Permission Model status from Active Development to Stable. Contributed by Rafael Gonzaga #56201". The commit list has "(SEMVER-MINOR) src,lib: stabilize permission model #56201" — [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.13.0)
- PR #56201 first landed in **23.5.0 (2024-12-19)** — [CHANGELOG_V23](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V23.md)
- The v22 permissions.html (v22.23.3) History table lists "v22.13.0 — This feature is no longer experimental." and "v20.0.0 — Added in: v20.0.0". The examples use `node --permission`, and the page never mentions `--experimental-permission` — [Node v22 permissions.html](https://nodejs.org/docs/latest-v22.x/api/permissions.html)
- The v22 cli.html `--permission` entry reads: "Added in: v20.0.0"; History "v22.13.0: Permission Model is now stable." The v22 NODE_OPTIONS allow-list contains both `--experimental-permission` and `--permission` — [Node v22 cli.html](https://nodejs.org/docs/latest-v22.x/api/cli.html); [cli.md v22.x](https://github.com/nodejs/node/blob/v22.x/doc/api/cli.md)
- With permission off, using any `--allow-*` flag throws `ERR_MISSING_OPTION('--experimental-permission')` in 20.x and `ERR_MISSING_OPTION('--permission')` in 22.x — [pre_execution.js v20.x](https://github.com/nodejs/node/blob/v20.x/lib/internal/process/pre_execution.js); [pre_execution.js v22.x](https://github.com/nodejs/node/blob/v22.x/lib/internal/process/pre_execution.js)

### Inferences
- The flag that works on every 20.x and every 22.x release is `--experimental-permission`. `--permission` works only on 22.13.0 and later.
- Because 20.x does not register `--permission`, following the v20 npx doc snippet (`--node-options="--permission"`) on 20.x would most likely fail as an unknown/bad option rather than enable the model. This is a doc bug in the v20 docs. I did not run it to confirm the exact runtime error.
- The v22 cli docs show "Added in: v20.0.0" for `--permission`. That date refers to the feature, not to the `--permission` spelling, which only exists on 22.13.0+. Readers can be misled by it.

### Gaps
- I did not run 20.x with `--permission` to confirm the exact error message.

## Q2. What stability level do the latest v20 and v22 docs show for the core model and each `--allow-*` flag?

### Takeaway
v20 (v20.20.2) shows **1.1 – Active development** for the core model, `--experimental-permission`, and all six `--allow-*` flags. v22 (v22.23.3) shows **2 – Stable** for the core model. `--permission`, `--allow-fs-read`, and `--allow-fs-write` are stable per their History entries, but they no longer carry an explicit banner. `--allow-child-process`, `--allow-worker`, `--allow-addons`, and `--allow-wasi` still show **1.1 – Active development**. **The earlier report's claim is confirmed, with one nuance:** the explicit "Stability: 2 - Stable." banner on the cli flags was present from 22.13.0 to 22.15.0 and is absent from 22.16.0 onward.

### Cited Findings
- v20 permissions.html (v20.20.2): Permission Model "Stability: 1.1 - Active development", "Added in: v20.0.0", no History table — [Node v20 permissions.html](https://nodejs.org/docs/latest-v20.x/api/permissions.html)
- In v20 cli.md (v20.x branch), `--experimental-permission`, `--allow-fs-read`, `--allow-fs-write`, `--allow-child-process`, `--allow-worker`, `--allow-addons`, and `--allow-wasi` each carry `> Stability: 1.1 - Active development` — [cli.md v20.x](https://github.com/nodejs/node/blob/v20.x/doc/api/cli.md); [Node v20 cli.html](https://nodejs.org/docs/latest-v20.x/api/cli.html)
- The 1.1 level came from "doc: move permission model to Active Development" #50068, which landed in **21.0.0 (2023-10-17)** and **20.10.0 (2023-11-22)** — [CHANGELOG_V21](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V21.md); [CHANGELOG_V20](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V20.md)
- v22 permissions.md (v22.x branch) / permissions.html (v22.23.3): `> Stability: 2 - Stable` — [Node v22 permissions.html](https://nodejs.org/docs/latest-v22.x/api/permissions.html)
- In v22 cli.md (v22.x branch), `--allow-child-process`, `--allow-worker`, `--allow-addons`, and `--allow-wasi` carry `> Stability: 1.1 - Active development`. `--permission`, `--allow-fs-read`, and `--allow-fs-write` have no Stability line. Their YAML history includes "v22.13.0 … Permission Model and --allow-fs flags are stable" (fs flags) and "Permission Model is now stable" (`--permission`) — [cli.md v22.x](https://github.com/nodejs/node/blob/v22.x/doc/api/cli.md); [Node v22 cli.html](https://nodejs.org/docs/latest-v22.x/api/cli.html)
- PR #56201 added `> Stability: 2 - Stable.` banners to `--permission`, `--allow-fs-read`, and `--allow-fs-write` in cli.md, replacing 1.1 — [PR #56201](https://github.com/nodejs/node/pull/56201)
- The v22.13.0, v22.14.0, and v22.15.0 tags' cli.md show `> Stability: 2 - Stable.` under `--permission` / `--allow-fs-read`. The v22.16.0, v22.18.0, and v22.20.0 tags show no Stability line under `--permission` — [cli.md v22.13.0](https://github.com/nodejs/node/blob/v22.13.0/doc/api/cli.md); [cli.md v22.15.0](https://github.com/nodejs/node/blob/v22.15.0/doc/api/cli.md); [cli.md v22.16.0](https://github.com/nodejs/node/blob/v22.16.0/doc/api/cli.md)
- 22.16.0 includes "doc: make stability labels more consistent" #57516. That PR's diff removes several `> Stability: 2 - Stable.` lines from `doc/api/cli.md` — [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.16.0); [PR #57516](https://github.com/nodejs/node/pull/57516)
- The v22.12.0 tag still shows `--experimental-permission` and `--allow-fs-read` at `Stability: 1.1 - Active development` — [cli.md v22.12.0](https://github.com/nodejs/node/blob/v22.12.0/doc/api/cli.md)

### Inferences
- Summary matrix (latest docs):

  | Item | v20.20.2 | v22.23.3 |
  |---|---|---|
  | Core model (permissions.html) | 1.1 | **2 Stable** (History: v22.13.0) |
  | Enabling flag | `--experimental-permission` 1.1 | `--permission`: stable via History, no banner since 22.16 |
  | `--allow-fs-read` / `--allow-fs-write` | 1.1 | stable via History (v22.13.0), no banner since 22.16 |
  | `--allow-child-process` | 1.1 | 1.1 |
  | `--allow-worker` | 1.1 | 1.1 |
  | `--allow-addons` | 1.1 | 1.1 |
  | `--allow-wasi` | 1.1 | 1.1 |
- The banner removal by #57516 is very likely a cosmetic "no banner = stable" normalization, not a demotion. The History entries and permissions.md still say Stable. I did not inspect every hunk of #57516 to confirm that the three removed cli.md lines are exactly `--allow-fs-read`, `--allow-fs-write`, and `--permission`. The tag comparison (present in 22.15.0, absent in 22.16.0) strongly suggests they are.

### Gaps
- No official statement explains why child-process/worker/addons/wasi were left at 1.1. The SecurityWarning text ("could invalidate the permission model") suggests the reason, but that is my inference.

## Q3. When was each `--allow-*` flag and path-syntax change introduced in each line?

### Takeaway
The earlier report's table is **largely confirmed**. One wording is imprecise: "(21.6.0에서 백포트)" ("backported from 21.6.0") means the change first landed in 21.6.0 and was then backported to 20.12.0. I also found two additions: the v20 docs never gained the "Relative paths" bullet and still describe commas as a valid delimiter in permissions.md, and the v22 cli docs list `--allow-wasi` as "Added in: v22.3.0" only, without its 20.16.0 backport.

### Cited Findings
- `--allow-fs-read`, `--allow-fs-write`, `--allow-child-process`, `--allow-worker`: "Added in: v20.0.0" in both v20 and v22 cli docs. The permission model itself arrived in 20.0.0 (2023-04-18) via "(SEMVER-MINOR) src,process: add permission model #44004" — [Node v20 cli.html](https://nodejs.org/docs/latest-v20.x/api/cli.html); [Node v22 cli.html](https://nodejs.org/docs/latest-v22.x/api/cli.html); [CHANGELOG_V20](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V20.md)
- `--allow-addons`: "(SEMVER-MINOR) src,permission: add --allow-addon flag #51183" landed in **21.6.0 (2024-01-15)** and **20.12.0 (2024-03-26)**. The v22 cli docs say "Added in: v21.6.0, v20.12.0" and the v20 cli docs say "Added in: v20.12.0" — [CHANGELOG_V21](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V21.md); [CHANGELOG_V20](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V20.md); [cli.md v22.x](https://github.com/nodejs/node/blob/v22.x/doc/api/cli.md)
- `--allow-wasi`: "(SEMVER-MINOR) src,permission: --allow-wasi & prevent WASI exec #53124" landed in **22.3.0 (2024-06-11)** and **20.16.0 (2024-07-24)**. The v20 cli docs say "Added in: v20.16.0", while the v22 cli docs say only "Added in: v22.3.0" — [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.3.0); [CHANGELOG_V20](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V20.md); [PR #53124](https://github.com/nodejs/node/pull/53124)
- Comma separator removal: "src,permission: add multiple allow-fs-\* flags #49047" landed in **20.7.0 (2023-09-18)**. The cli docs History for both fs flags, in both lines, says "v20.7.0 — Paths delimited by comma (`,`) are no longer allowed." It is not listed in CHANGELOG_V22 because 22.0.0 already included it — [CHANGELOG_V20](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V20.md); [PR #49047](https://github.com/nodejs/node/pull/49047)
- Since then, both 20.x and 22.x source emit a `Warning` ("The --allow-fs-read CLI flag has changed. Passing a comma-separated list of paths is no longer valid…") when a single fs flag value contains a comma — [pre_execution.js v20.x](https://github.com/nodejs/node/blob/v20.x/lib/internal/process/pre_execution.js); [pre_execution.js v22.x](https://github.com/nodejs/node/blob/v22.x/lib/internal/process/pre_execution.js)
- Stale v20 doc: v20 permissions.html (v20.20.2) still lists "Paths delimited by comma (`,`) to allow only matching `FileSystemRead` or `FileSystemWrite` operations". In v22 this was removed by "doc: remove comma delimiter mention on permissions doc" #58297 in **22.17.0**. That PR does not appear in CHANGELOG_V20 — [Node v20 permissions.html](https://nodejs.org/docs/latest-v20.x/api/permissions.html); [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.17.0)
- Relative paths: CHANGELOG_V20 20.12.0 Notable Changes: "relative paths are now supported through the `--allow-fs-*` flags… `node --experimental-permission --allow-fs-read=./index.js`", via #50758 ("(SEMVER-MINOR) lib,src,permission: port path.resolve to C++"). #50758 first landed in **21.6.0** — [CHANGELOG_V20](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V20.md); [CHANGELOG_V21](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V21.md); [PR #50758](https://github.com/nodejs/node/pull/50758)
- Doc lag on relative paths: until "doc: fix relative path mention in --allow-fs" #55791, cli.md said "Relative paths are NOT yet supported by the CLI flag". #55791 removed that sentence (and the comma note in `--allow-fs-read`). It shipped in 23.4.0, **22.13.0**, and **20.19.5 (2025-09-03)** — [PR #55791 diff](https://github.com/nodejs/node/pull/55791); [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.13.0); [CHANGELOG_V20](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V20.md)
- v22 permissions.html lists the valid fs arguments as "`*`", "Relative paths to the current working directory.", and "Absolute paths." The v20 permissions.html has **no** relative-path bullet and still has the comma bullet — [Node v22 permissions.html](https://nodejs.org/docs/latest-v22.x/api/permissions.html); [Node v20 permissions.html](https://nodejs.org/docs/latest-v20.x/api/permissions.html)
- Wildcards: both v20 and v22 permissions.html have identical text. `--allow-fs-read=/home/test*` matches `/home/test/file1` or `/home/test2`. "After passing a wildcard character (`*`) all subsequent characters will be ignored… `/home/*.js` will work similar to `/home/*`". An existing directory gets an implicit `/*`, and a non-existent one does not unless `/*` is given explicitly — [Node v20 permissions.html](https://nodejs.org/docs/latest-v20.x/api/permissions.html); [Node v22 permissions.html](https://nodejs.org/docs/latest-v22.x/api/permissions.html)
- Wildcard-related changes in the changelogs: a wildcard fix ("permission: fix wildcard when children > 1" #51209) and CVE-2024-21890 ("Improper handling of wildcards in --allow-fs-read and --allow-fs-write") in **20.11.1 (2024-02-14)**. The doc addition "add additional explanation to the wildcard section in permissions" #53664 landed in **22.5.0** and **20.17.0** — [CHANGELOG_V20](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V20.md); [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.5.0)
- 22-only fs behavior: "src,permission: implicit allow-fs-read to app entrypoint" #58579 in **22.17.0** (cli History: "Entrypoints of your application are allowed to be read implicitly"). `--allow-child-process` gained spawn propagation (#58853) in **22.18.0**. "permission.has(addon)" #58951 also arrived in 22.18.0. None of these appear in CHANGELOG_V20 — [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.18.0); [cli.md v22.x](https://github.com/nodejs/node/blob/v22.x/doc/api/cli.md)

### Inferences
- Consolidated timeline:

  | Change | 20.x | 22.x |
  |---|---|---|
  | fs-read/fs-write/child-process/worker flags | 20.0.0 | present from 22.0.0 |
  | Comma separator removed (#49047) | 20.7.0 | present from 22.0.0 |
  | Relative paths (#50758, first in 21.6.0) | 20.12.0 (docs corrected only in 20.19.5, and v20 permissions.md still lacks the bullet) | present from 22.0.0; docs corrected in 22.13.0 |
  | `--allow-addons` (#51183, first in 21.6.0) | 20.12.0 | present from 22.0.0 |
  | `--allow-wasi` (#53124) | 20.16.0 | 22.3.0 |
  | Wildcard semantics | unchanged since 20.0.0, bug fixes in 20.11.1 | same |
  | Implicit entrypoint read (#58579) | not present | 22.17.0 |
  | Spawn flag propagation (#58853) | not present | 22.18.0 |
- Doc correction to the earlier report: it says "v20.x 브랜치의 permissions.md는 여전히 'comma-delimited list'라고 적고" ("the v20.x branch permissions.md still says 'comma-delimited list'"). The actual v20 wording is "Paths delimited by comma (`,`)". The substance (the stale comma mention) is correct.

### Gaps
- I did not check whether #50758 also enabled relative paths for other constructs. Only the CLI fs flags are documented.

## Q4. Does the `--experimental-permission` alias emit a deprecation warning in 22.x?

### Takeaway
**No.** In 22.13.0+ the alias is a plain `AddAlias`. No deprecation code is registered, and no DEP entry, doc note, or warning exists for it. The `ExperimentalWarning: Permission is an experimental feature` that 20.x and 22.0–22.12 print on every run was removed in 22.13.0. **Correction to the earlier report:** the `SecurityWarning` for `--allow-child-process`/`--allow-worker`/`--allow-addons`/`--allow-wasi` did **not** start in 22.13.0. It has existed since 20.0.0, and the list of flags it covers grew as new flags were added.

### Cited Findings
- v22.x `node_options.cc`: `AddAlias("--experimental-permission", "--permission");`. The alias has no attached deprecation or warning — [node_options.cc v22.x](https://github.com/nodejs/node/blob/v22.x/src/node_options.cc)
- v22.x `initializePermission()` reads `getOptionValue('--permission')` and contains **no** `emitExperimentalWarning` call. The only warnings it emits are the SecurityWarning for risky flags and the comma-list Warning — [pre_execution.js v22.x](https://github.com/nodejs/node/blob/v22.x/lib/internal/process/pre_execution.js)
- v20.x `initializePermission()` reads `getOptionValue('--experimental-permission')` and calls `emitExperimentalWarning('Permission')` — [pre_execution.js v20.x](https://github.com/nodejs/node/blob/v20.x/lib/internal/process/pre_execution.js)
- The v20 permissions.html example output shows "(node:19836) ExperimentalWarning: Permission is an experimental feature" — [Node v20 permissions.html](https://nodejs.org/docs/latest-v20.x/api/permissions.html)
- PR #56201 removes `emitExperimentalWarning('Permission')` and the doc's ExperimentalWarning example line — [PR #56201](https://github.com/nodejs/node/pull/56201)
- The SecurityWarning ("The flag ${flag} must be used with extreme caution. It could invalidate the permission model.") appears at these tags:
  - v20.0.0 (covers `--allow-child-process`, `--allow-worker`)
  - v22.0.0 (adds `--allow-addons`)
  - v22.12.0 (adds `--allow-wasi`)
  - the v20.x branch head (covers all four)

  [pre_execution.js v20.0.0](https://github.com/nodejs/node/blob/v20.0.0/lib/internal/process/pre_execution.js); [pre_execution.js v22.0.0](https://github.com/nodejs/node/blob/v22.0.0/lib/internal/process/pre_execution.js); [pre_execution.js v22.12.0](https://github.com/nodejs/node/blob/v22.12.0/lib/internal/process/pre_execution.js); [pre_execution.js v20.x](https://github.com/nodejs/node/blob/v20.x/lib/internal/process/pre_execution.js)
- The v22 permissions.html and cli.html do not mention `--experimental-permission` anywhere except the NODE_OPTIONS allow-list in cli. Neither page has an alias or deprecation note — [Node v22 permissions.html](https://nodejs.org/docs/latest-v22.x/api/permissions.html); [cli.md v22.x](https://github.com/nodejs/node/blob/v22.x/doc/api/cli.md)
- `process.binding` replacement (throws `ERR_ACCESS_DENIED`) and `ObjectFreeze(require('path'))` are present in **both** v20.x and v22.x `initializePermission()`. The earlier report attributed them to "pre_execution.js v22.13.0". They are not 22-specific — [pre_execution.js v20.x](https://github.com/nodejs/node/blob/v20.x/lib/internal/process/pre_execution.js); [pre_execution.js v22.x](https://github.com/nodejs/node/blob/v22.x/lib/internal/process/pre_execution.js)

### Inferences
- On 22.13.0+, `--experimental-permission` behaves identically to `--permission` and prints nothing extra. On 20.x it prints an ExperimentalWarning. Tests that assert empty stderr will therefore differ between the lines.
- The earlier report's sentence "22.13.0부터는 이 네 플래그를 쓰면 … SecurityWarning이 출력됩니다" ("from 22.13.0, using these four flags prints a SecurityWarning") is **wrong as worded**. The warning exists in 20.x as well. Only the covered flag list grew: addons was added by 22.0.0, and wasi when `--allow-wasi` was introduced (22.3.0 / 20.16.0).

### Gaps
- I found no official statement, deprecation entry (DEP0xxx), or issue planning removal of the `--experimental-permission` alias in 22.x. The absence was confirmed by the docs and source, but I did not exhaustively search issues or deprecations.md.
- I did not pin the exact 22.x/20.x patch release that first added `--allow-wasi` to the SecurityWarning list. It is presumably 22.3.0 / 20.16.0 together with #53124, but I did not verify against those tags.
