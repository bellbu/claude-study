# Node.js 20.x vs 22.x: permission-model security fixes and support status (verified as of 2026-10-17)

Scope: re-check of the security and lifecycle claims in `reports/Nodejs 20 22 권한 모델 변화.md` against official Node.js sources (Release schedule.json, nodejs.org previous-releases, nodejs.org security blog posts, CHANGELOG_V20/V22, SECURITY.md, versioned API docs). Each section ends with what was confirmed or corrected in the earlier report.

## Q1. Official EOL date of 20.x and current support phase of 22.x

### Takeaway
20.x ("Iron") reached EOL on **2026-04-30**. Its last release was **20.20.2 (2026-03-24)**, a security release. 22.x ("Jod") has been in **Maintenance LTS since 2025-10-21** and reaches EOL on **2027-04-30**. The latest 22.x release is **22.23.3 (2026-09-23)**. The earlier report's EOL claim is confirmed.

### Cited Findings
- Release schedule: v20 start 2023-04-18, LTS 2023-10-24, maintenance 2024-10-22, end **2026-04-30**. v22 start 2024-04-24, LTS 2024-10-29, maintenance **2025-10-21**, end **2027-04-30** — [nodejs/Release schedule.json](https://raw.githubusercontent.com/nodejs/Release/main/schedule.json)
- Other lines for context: v24 enters maintenance on 2026-10-20 and ends 2028-04-30. v25 ended 2026-06-01 in schedule.json (previous-releases shows its last update as Mar 31, 2026, status EOL). v26 becomes LTS on 2026-10-28 — [schedule.json](https://raw.githubusercontent.com/nodejs/Release/main/schedule.json); [Previous releases](https://nodejs.org/en/about/previous-releases)
- The previous-releases table lists v20 Iron as **EOL** (last updated Mar 24, 2026) and v22 Jod as **LTS** (last updated Sep 23, 2026) — [Previous releases](https://nodejs.org/en/about/previous-releases)
- CHANGELOG_V20 tops out at "2026-03-24, Version 20.20.2 'Iron' (LTS)" — [CHANGELOG_V20](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V20.md)
- CHANGELOG_V22 tops out at "2026-09-23, Version 22.23.3 'Jod' (LTS)". The latest-v22 docs are titled "Node.js v22.23.3 Documentation" — [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md); [v22 cli docs](https://nodejs.org/docs/latest-v22.x/api/cli.html)
- The previous-releases page says commercial support past the Maintenance LTS phase is available through OpenJS Ecosystem Sustainability Program partners. The March 2026 security post repeats this — [Previous releases](https://nodejs.org/en/about/previous-releases); [March 2026 security releases](https://nodejs.org/en/blog/vulnerability/march-2026-security-releases)

### Inferences
- 20.20.2 (2026-03-24) is in practice the final 20.x release. No 20.x release appears after it, and no later security post lists 20.x. The March 2026 post does not explicitly call itself the last 20.x release.
- 22.x has about 6.5 months of support left as of 2026-10-17. As a Maintenance LTS line, it gets critical bug and security fixes only.

### Gaps
- No official statement calls 20.20.2 "the final release". This is inferred from the changelog and the release table.

## Q2. Permission-model CVEs fixed in both lines vs only in 22.x (with verification of the seven named CVEs)

### Takeaway
All seven named CVEs are real, and their fixed versions match the earlier report. **CVE-2025-23083** (High) and **CVE-2025-55130** (High) were fixed in both lines. Five CVEs from June and July 2026 were fixed only in 22.x (and 24/26), after 20.x EOL. The earlier report labelled only CVE-2026-58043 by severity. The other four are all **Low**, and the report should say so explicitly.

### Cited Findings

**Fixed in both 20.x and 22.x (selected; all permission model)**

| CVE | Title (official) | Severity | 20.x fix | 22.x fix | Source |
|---|---|---|---|---|---|
| CVE-2025-23083 | Worker permission bypass via InternalWorker leak in diagnostics (`diagnostics_channel`) | High | 20.18.2 (2025-01-21) | 22.13.1 (2025-01-21) | [Jan 2025 security releases](https://nodejs.org/en/blog/vulnerability/january-2025-security-releases); CHANGELOG_V20/V22 entries "throw on InternalWorker use when permission model is enabled (High)" |
| CVE-2025-55130 | Bypass File System Permissions using crafted symlinks | High | 20.20.0 (2026-01-13) | 22.22.0 (2026-01-13) | [Jan 13, 2026 security releases (URL slug "december-2025")](https://nodejs.org/en/blog/vulnerability/december-2025-security-releases); changelog commit "lib,permission: require full read and write to symlink APIs" |
| CVE-2025-55132 | `fs.futimes()` bypasses read-only permission model | Low | 20.20.0 | 22.22.0 | [Jan 13, 2026 post](https://nodejs.org/en/blog/vulnerability/december-2025-security-releases) |
| CVE-2026-21715 | Permission Model bypass in `realpathSync.native` (file existence disclosure) | Low | 20.20.2 (2026-03-24) | 22.22.2 (2026-03-24) | [March 2026 security releases](https://nodejs.org/en/blog/vulnerability/march-2026-security-releases) |
| CVE-2026-21716 | CVE-2024-36137 patch bypass: `FileHandle.chmod/chown` | Low | 20.20.2 | 22.22.2 | [March 2026 security releases](https://nodejs.org/en/blog/vulnerability/march-2026-security-releases) |

- The security posts do not map CVEs to versions one by one. They list fixed releases per line. The CVE-to-version mapping above comes from the release headers in CHANGELOG_V20/V22 where each CVE commit appears: 20.18.2/22.13.1 dated 2025-01-21, 20.20.0/22.22.0 dated 2026-01-13, 20.20.2/22.22.2 dated 2026-03-24 — [CHANGELOG_V20](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V20.md); [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md)
- The page at the "december-2025-security-releases" URL is titled and dated **Tuesday, January 13, 2026**. Its summary still carries leftover text saying "Monday, December 15, 2025", from the postponed pre-announcement — [Jan 13, 2026 post](https://nodejs.org/en/blog/vulnerability/december-2025-security-releases)

**Fixed only in 22.x (and 24.x/26.x), after 20.x EOL**

| CVE | Title (official) | Severity | 22.x fix | Other lines | Source |
|---|---|---|---|---|---|
| CVE-2026-48617 | Permission Model bypass via `process.report.writeReport()` path misvalidation (commit: "permission: handle process.chdir on writereport") | **Low** | 22.23.0 (2026-06-18) | 24.17.0, 26.3.1 | [June 2026 security releases](https://nodejs.org/en/blog/vulnerability/june-2026-security-releases) |
| CVE-2026-48935 | Permission Model bypass via `FileHandle.utimes()` (promises API) on read-only paths (commit: "permission: disable FileHandle utimes with permission model") | **Low** | 22.23.0 | 24.17.0, 26.3.1 | [June 2026 security releases](https://nodejs.org/en/blog/vulnerability/june-2026-security-releases) |
| CVE-2026-56847 | Permission Model allows trace events (`trace_events.createTracing().enable()`) to write outside the allowlist | **Low** | 22.23.2 (2026-07-29) | 24.18.1, 26.5.1 | [July 2026 security releases](https://nodejs.org/en/blog/vulnerability/july-2026-security-releases) |
| CVE-2026-58039 | Permission Model allows process reports to write outside the allowlist (commit: "permission: check final report output path") | **Low** | 22.23.2 | 24.18.1, 26.5.1 | [July 2026 security releases](https://nodejs.org/en/blog/vulnerability/july-2026-security-releases) |
| CVE-2026-58043 | Permission Model path matching can over-grant filesystem access (radix-tree prefix boundary; commit "permission: avoid granting radix split nodes") | **High** | 22.23.2 | 24.18.1, 26.5.1 | [July 2026 security releases](https://nodejs.org/en/blog/vulnerability/july-2026-security-releases) |

- The June 2026 and July 2026 posts list only 22.x/24.x/26.x as affected and do not mention 20.x. Both say "End-of-Life versions are always affected when a security release occurs" — [June 2026](https://nodejs.org/en/blog/vulnerability/june-2026-security-releases); [July 2026](https://nodejs.org/en/blog/vulnerability/july-2026-security-releases)
- CHANGELOG_V22 lists CVE-2026-48617 and CVE-2026-48935 under 22.23.0, and CVE-2026-56847, CVE-2026-58039 and CVE-2026-58043 under 22.23.2. The PR references are nodejs-private/node-private #870, #873, #927, #926, #911 — [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md)
- The June 2026 post is dated Thursday, June 18, 2026, although its summary says "on or shortly after Wednesday, June 17". The July post was postponed twice (from July 27 to July 28, then to July 29) and is dated July 29, 2026 — [June 2026](https://nodejs.org/en/blog/vulnerability/june-2026-security-releases); [July 2026](https://nodejs.org/en/blog/vulnerability/july-2026-security-releases)
- 22.23.0 was itself the security release. 22.23.1 (2026-06-23) followed and fixed a regression from 22.23.0 — [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md)

**Permission CVEs in these releases that never affected 22.x (all tied to `--allow-net`, 25.x/26.x only)**
- CVE-2026-21636: Unix domain socket connections bypass the permission model. Medium, 25.x only, fixed in 25.3.0 — [Jan 13, 2026 post](https://nodejs.org/en/blog/vulnerability/december-2025-security-releases)
- CVE-2026-21711: a UDS server can bind and listen without `--allow-net`. Medium, 25.x only, fixed in 25.8.2 — [March 2026](https://nodejs.org/en/blog/vulnerability/march-2026-security-releases)
- CVE-2026-48936: a UDS server bypasses `--permission` network restrictions (incomplete fix for CVE-2026-21636). Low, 26.x only, fixed in 26.3.1 — [June 2026](https://nodejs.org/en/blog/vulnerability/june-2026-security-releases)

### Inferences
- **Correction to the earlier report:** its conclusion says two High-severity bypasses appeared after stable promotion. Counting from 22.13.0 (2025-01-07), there were **three** High permission CVEs affecting 22.x: CVE-2025-23083 (fixed 22.13.1, two weeks after promotion), CVE-2025-55130 and CVE-2026-58043. If one counts only bugs both discovered and fixed after promotion, the claim of two (55130 and 58043) is defensible. Either way, the wording should be made precise.
- 20.x is permanently exposed to CVE-2026-58043 (High; allowlist over-grant) plus four Low issues. All of them affect users who enable `--experimental-permission`.
- The earlier report described CVE-2026-48617 as a "path validation problem". The fix commit title ("handle process.chdir on writereport") shows the bypass worked through `process.chdir` changing the base for relative report paths. This is an inference from the commit title only.

### Gaps
- The official posts do not publish CVSS scores. Only High/Medium/Low labels are given, so no numeric severity can be cited.
- I did not independently check NVD/MITRE entries for these 2026 CVE IDs. Verification relies on nodejs.org posts and the changelogs.

## Q3. Permission-related 22.x releases or security releases after 2026-09; latest 22.x as of 2026-10-17

### Takeaway
The latest 22.x release is **22.23.3 (2026-09-23)**, a regular release with **no permission, CVE or security entries**. A **security release is pre-announced for "on or shortly after Wednesday, October 21, 2026"** covering 26.x, 24.x and **22.x**, with HIGH as the highest severity in each line. As of 2026-10-17 it has not shipped, and the pre-announcement does not say whether any issue involves the permission model.

### Cited Findings
- CHANGELOG_V22 22.23.3 (2026-09-23, prepared by @juanarbol) contains no commits mentioning permission, CVE or security. No version after 22.23.3 exists in the changelog — [CHANGELOG_V22](https://github.com/nodejs/node/blob/main/doc/changelogs/CHANGELOG_V22.md#22.23.3)
- Previous-releases shows v22 "last updated Sep 23, 2026" — [Previous releases](https://nodejs.org/en/about/previous-releases)
- The October 2026 pre-announcement ("Wednesday, October 21, 2026 Security Releases", page last updated Oct 14, 2026) lists 26.x, 24.x and 22.x, each with highest severity HIGH. It gives no CVE IDs, titles or per-issue counts, and does not mention 20.x — [October 2026 security releases](https://nodejs.org/en/blog/vulnerability/october-2026-security-releases)
- The 2026 security posts in order are: Mar 24, Jun 18, Jul 29, and the Oct 21 pre-announcement. A Jan 28, 2026 OpenSSL assessment post also exists — [Vulnerability blog index](https://nodejs.org/en/blog/vulnerability)

### Inferences
- The earlier report's statement that 22.23.3 has no permission-related items is **confirmed**. The report should add that an October 21, 2026 security release for 22.x is pending, and that its content (including any permission fixes) is unknown as of 2026-10-17. The next 22.x is likely 22.23.4 or 22.24.0, but that is not confirmed.

### Gaps
- Whether the Oct 21, 2026 release includes permission-model CVEs cannot be known until disclosure.

## Q4. How SECURITY.md / the threat model treats permission-model bypasses

### Takeaway
The current SECURITY.md (main branch, last changed 2026-10-07) has a dedicated "Permission Model Boundaries (`--permission`)" section. It states that the model is **not** a security boundary against intentional misuse or a compromised process. It sorts reports into three lanes: **Vulnerability**, **Security-interest bug** (hardening, not automatically a CVE) and **Excluded**. Symlink resolution and TOCTOU within the allowlist, `node:sqlite` SQL-level file access, worker `execArgv`/`env` propagation and operator-selected output paths are all explicitly not vulnerabilities. Much of this wording was added in **Aug–Sep 2026**, after most of the CVEs above were issued.

### Cited Findings
- "It is designed to reduce the blast radius of mistakes in trusted application code, **not** to act as a security boundary against intentional misuse or a compromised process." — [SECURITY.md](https://github.com/nodejs/node/blob/main/SECURITY.md)
- The triage lanes are quoted from the same section — [SECURITY.md](https://github.com/nodejs/node/blob/main/SECURITY.md):
  - Vulnerability: "An element Node.js does not trust crosses a Node.js-owned permission check without trusted code already executing in the protected process."
  - Security-interest bug: "Trusted application code uses documented, stable APIs as intended, but Node.js fails to enforce a documented permission invariant consistently — for example, one API enforces a check that an equivalent API omits. These are fixed as hardening and are not automatically CVE-class, because the Permission Model is not a sandbox against malicious same-process code."
  - Excluded: "Intentional misuse by code already running in the process, operator-selected flags, a modified `execArgv`/`env`, or any expectation that the Permission Model sandboxes malicious same-process code."
- Items listed as not vulnerabilities — [SECURITY.md](https://github.com/nodejs/node/blob/main/SECURITY.md):
  - Operator-controlled flags, e.g. files written at paths from `--trace-event-file-pattern` without a matching `--allow-fs-write`. These are treated as regular bugs on the public tracker.
  - `node:sqlite` pragmas or `ATTACH DATABASE`.
  - "Accessing a file through a symlink that resolves to an allowed path is the intended behavior, not a bypass", and TOCTOU races on symlinks resolving within the allowed list.
  - Workers started with modified `execArgv`/`env`: "Applications that rely on the Permission Model must not grant `--allow-worker` to code they do not trust."
- In the general triage section, security-interest bugs "should still be reported privately first when they affect a common security control such as protocol interpretation, **permission enforcement**, or certificate/TLS decisions" — [SECURITY.md](https://github.com/nodejs/node/blob/main/SECURITY.md)
- Experimental features: vulnerabilities affecting only 1.0 or 1.1 experimental features "will **not** be accepted as valid security issues unless" they can be exploited against a stable feature when the `--experimental-*` flag is not enabled. Stage 1.2 issues are accepted — [SECURITY.md](https://github.com/nodejs/node/blob/main/SECURITY.md)
- The disclosure policy says "Fixes are prepared for all supported releases", which implies EOL lines get no fixes — [SECURITY.md](https://github.com/nodejs/node/blob/main/SECURITY.md)
- Recent SECURITY.md history from the GitHub commits API — [commits for SECURITY.md](https://github.com/nodejs/node/commits/main/SECURITY.md):
  - 2026-08-26 "doc: clarify security triage dispositions and permission boundaries"
  - 2026-08-27 "meta: refine the security vuln posture for experimental features"
  - 2026-09-14 "doc: clarify permission model scope for output paths"
  - 2026-10-07 "doc: clarify node binary misuse after compromise"

### Inferences
- **Partial correction to the earlier report:** it says SECURITY.md designates "permission enforcement" bypasses as private-report targets. That phrase appears in the generic security-interest-bug lane: report privately first, but such bugs do not automatically get a CVE. The permission-specific section narrows what counts as a vulnerability. The report should present both parts so the policy is not read as "every bypass is a CVE".
- The policy has tightened over time. Several CVE classes issued earlier would likely be classed as "security-interest bug" or "excluded" under the Aug/Sep 2026 wording: missing checks on equivalent APIs (`FileHandle.utimes`, `FileHandle.chmod/chown`, `realpath.native`), report/trace output paths, and symlink chains. The 2026-09-14 commit on "output paths" came after CVE-2026-56847 and CVE-2026-58039 (trace/report outputs, July 2026). Future fixes of this kind may therefore ship as hardening without CVEs. This is an inference; the commit messages do not say so.
- Applying the experimental-feature rule (1.0/1.1 not accepted) to 20.x, where the permission model stayed at Stability 1.1, would exclude 20.x-only issues. In practice, CVEs were still assigned to 20.x because the same bugs affected the stable 22.x+/24.x implementation. The experimental-features rule was refined only on 2026-08-27, so earlier practice may have differed. This is an inference.

### Gaps
- I did not retrieve the SECURITY.md text as it stood at the time of each CVE (e.g. January 2025). The quotes reflect the main branch as of 2026-10-17.

## Q5. Features only in newer lines (--allow-net, --permission-audit, permission.drop): absent from 22.x?

### Takeaway
All three are **absent from 22.x** (the v22.23.3 docs contain no reference to them). **Correction:** the earlier report says these exist only on main and 25.x+. In fact **`--permission-audit` and `process.permission.drop()` were backported to 24.x (v24.20.0)**. Only `--allow-net` remains 25.x+ (added v25.0.0, Stability 1.1).

### Cited Findings
- latest-v22 docs (v22.23.3): cli.html, permissions.html and process.html have zero occurrences of `allow-net`, `permission-audit` or `permission.drop` — [v22 cli](https://nodejs.org/docs/latest-v22.x/api/cli.html); [v22 permissions](https://nodejs.org/docs/latest-v22.x/api/permissions.html); [v22 process](https://nodejs.org/docs/latest-v22.x/api/process.html)
- main cli.md: `--allow-net` "added: v25.0.0", "Stability: 1.1 - Active development" — [cli.md main](https://github.com/nodejs/node/blob/main/doc/api/cli.md)
- main cli.md: `--permission-audit` "added: v25.8.0, v24.20.0". v24 docs (v24.22.0) show "Added in: v24.20.0". The feature runs permission checks without denying access (no `ERR_ACCESS_DENIED`) and publishes violations through `node:diagnostics_channel` — [cli.md main](https://github.com/nodejs/node/blob/main/doc/api/cli.md); [v24 cli](https://nodejs.org/docs/latest-v24.x/api/cli.html)
- main process.md: `process.permission.drop(scope[, reference])` "added: v26.3.0, v24.20.0", with a change in v26.12.0 (PR #65492). It is irreversible and only affects future access checks. The v24 docs list `process.permission.drop(scope[, reference])` — [process.md main](https://github.com/nodejs/node/blob/main/doc/api/process.md); [v24 process](https://nodejs.org/docs/latest-v24.x/api/process.html)
- The v24 docs (v24.22.0) have no `--allow-net` entry — [v24 cli](https://nodejs.org/docs/latest-v24.x/api/cli.html)
- The March 2026 post notes "`--allow-net` is currently experimental" in the context of CVE-2026-21711 (25.x) — [March 2026](https://nodejs.org/en/blog/vulnerability/march-2026-security-releases)

### Inferences
- Users who need audit mode or runtime permission dropping can stay on an LTS line by moving to 24.x (≥ 24.20.0, EOL 2028-04-30). Network permissions need 25.x+ (25 is EOL), which in practice means 26.x (LTS from 2026-10-28).
- No backport of these features to 22.x is likely. 22.x is in Maintenance LTS, which takes only critical and security fixes. This is an inference from LTS policy; no official statement was found.

### Gaps
- I did not identify the exact 24.20.0 release date or the PR numbers for the 24.x backports.

## Summary of verification against the earlier report
- Confirmed: 20.x EOL 2026-04-30. Fixed versions and severities for CVE-2025-23083 (High; 20.18.2/22.13.1) and CVE-2025-55130 (High; 20.20.0/22.22.0). CVE-2026-48617 and CVE-2026-48935 fixed in 22.23.0. CVE-2026-56847, CVE-2026-58039 and CVE-2026-58043 fixed in 22.23.2 (2026-07-29). CVE-2026-58043 is High. 22.23.3 (2026-09-23) has no permission items.
- Add: the four other post-EOL CVEs (48617, 48935, 56847, 58039) are all **Low**. 22.x is in Maintenance LTS until 2027-04-30. An Oct 21, 2026 security release covering 22.x is pre-announced with undisclosed contents.
- Correct: `--permission-audit` and `permission.drop()` exist in 24.x (≥ 24.20.0), not only 25.x+. Only `--allow-net` is 25.x+. The count of "two High bypasses after stable promotion" is three if CVE-2025-23083 (fixed in 22.13.1) is included.
- Clarify: SECURITY.md's "permission enforcement" private-report wording belongs to the security-interest-bug lane (no automatic CVE). The permission section states that the model is not a security boundary against misuse or a compromised process. Much of this wording dates from Aug–Sep 2026.
- Citation nit: the earlier report labels the december-2025 URL as the "January 2026 security release". That is correct: the page is dated Jan 13, 2026 despite its slug.
