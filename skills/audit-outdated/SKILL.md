---
name: audit-outdated
category: audit
description: outdated-skill audit. Compares installed dev-kit snapshot vs current dev-harness-kit HEAD. Reports per-skill semver drift.
version: 0.1.0
when_to_use: |
  - User types /dev-kit:audit --outdated
  - User wants to know which installed skills are below current HEAD before /dev-kit:ci-setup --force
allowed-tools: Read Grep Glob Bash
disallowed-tools: Write Edit
model: haiku
user-invocable: false
---

# audit-outdated — Outdated-skill audit

Read-only per-skill version drift report. Compares the dev-kit plugin
snapshot the user has **installed** against the **HEAD** checkout of
`dev-harness-kit`. Surfaces skills where the installed version is
behind HEAD, so the user can decide whether to
`/dev-kit:ci-setup --force`.

## Iron Law
**Read-only ❌.** No file writes. No edits. The output is stdout only —
intentionally no `audit-report.md` (KISS; committing a generated report
risks bit-rot; a future consumer can redirect stdout to a file if they
want a persistent artifact).

## Walk

Two directories to compare for each `skills/<name>/SKILL.md`:

1. **HEAD** (the candidate): `<cwd>/skills/<name>/SKILL.md` in the
   dev-harness-kit checkout the user is currently in.
2. **Installed** (the baseline): glob
   `~/.claude/plugins/cache/dev-kit/dev-kit/*/skills/<name>/SKILL.md`
   where `*` is the semver dir (or commit-SHA dir per PR #31). Pick
   the **semver-max** entry if multiple. If the cache is empty (fresh
   install pre-this-feature, or cache was never refreshed), fall back
   to `~/.claude/plugins/marketplaces/dev-kit/skills/<name>/SKILL.md`
   (the marketplace clone `bin/devkit-refresh.sh` keeps up to date).

For each skill, extract the `version:` field from the frontmatter of
both files. Use `lib/ci_setup.py:extract_skill_versions()` on the HEAD
side; the same logic inlined (or the cached `installed_skill_versions`
mirror in `.dev-kit/ci-config.json` if present) for the installed side.

## Drift classification

| Relationship                       | Drift tag |
|------------------------------------|-----------|
| Installed == HEAD                  | `same`    |
| Installed < HEAD (numeric)         | `patch` / `minor` / `major` per the magnitude |
| Installed > HEAD (HEAD regressed)  | `regress` — flag loudly (likely a hand-edit or partial checkout) |
| Installed missing, HEAD present    | `new`     |
| Installed present, HEAD missing    | `removed` — flag loudly (skill was deleted from the plugin) |
| Either side fails SEMVER_RE        | `invalid` — flag loudly with both raw values |

Use the semver compare from `lib/ci_setup.py` (PEP 440 via
`packaging.version.Version` when available; the self-contained
`_semver_lt` in `templates/ci/scripts/validate.py` otherwise). Both
files in dev-harness-kit have access to one of the two.

## Output

```
=== /dev-kit:audit --outdated -- N outdated of 29 skills ===

SKILL          INSTALLED  HEAD      DRIFT
build          0.1.0      0.2.0     minor
audit-secret   0.1.0      0.1.1     patch
... 27 unchanged ...

To refresh: /dev-kit:ci-setup --force
```

- Sort: outdated first (most-outdated by semver magnitude within ties),
  then `same`, then `new` / `removed` / `regress` / `invalid` at the
  bottom (these are surprises and deserve attention).
- 4-space fixed column for the eye to scan; do not align to the
  longest name (the table is human-readable, not machine-parseable).
- If **zero** drift: print `=== /dev-kit:audit --outdated -- all 29 skills current ===` and exit 0.
- No file written.

## Exit codes

- `0` if every installed skill is at-or-above HEAD (no actionable drift).
- `1` if at least one skill is below HEAD, OR any surprise
  (`regress` / `removed` / `invalid`).

The non-zero exit lets a user wire this into a pre-commit hook or a
nightly cron with `|| true` if they only want a heads-up, or `|| exit 1`
if they want it to block.

## Edge cases

- **No installed snapshot at all** (no `~/.claude/plugins/.../dev-kit/`
  cache, no marketplace clone): all skills report `new`. Exit 1 with
  the message: "No installed dev-kit snapshot found — run
  `claude plugin install dev-kit` first."
- **Cache has multiple installed versions** (shouldn't happen, but):
  pick the semver-max. Note the pick in the output header so the user
  knows which snapshot was inspected.
- **`.dev-kit/ci-config.json` exists with `installed_skill_versions`**:
  prefer that mirror over walking the cache (faster + matches the
  PR-gate's source of truth).
