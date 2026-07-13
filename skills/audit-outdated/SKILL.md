---
name: audit-outdated
category: audit
description: outdated-skill audit. Diff-based per-skill drift report between installed dev-kit snapshot and dev-harness-kit HEAD. Zero bookkeeping.
when_to_use: |
  - User types /dev-kit:audit --outdated
  - User wants to know which installed skills are behind current HEAD before /dev-kit:ci-setup --force
allowed-tools: Read Grep Glob Bash
disallowed-tools: Write Edit
model: haiku
user-invocable: false
---

# audit-outdated — Outdated-skill audit

Read-only per-skill drift report. Compares the dev-kit plugin snapshot the
user has **installed** against the **HEAD** checkout of `dev-harness-kit`.
Surfaces skills whose installed file content differs from HEAD, so the
user can decide whether to `/dev-kit:ci-setup --force`.

## Iron Law
**Read-only ❌.** No file writes. No edits. Stdout only — no
`audit-report.md` (KISS; committing a generated report risks bit-rot;
future consumers can redirect stdout to a file if persistence is needed).

## Why file-content diff (not per-skill versions)

Earlier draft attempted to track each skill with its own `version:`
frontmatter field and bump per bump. We scrapped that — it was
bureaucratic tax with no real benefit at this scale. Drift detection at
the SKILL.md file-content level is:

- **Honest**: a version number can lie; file bytes cannot. If the
  installed SKILL.md bytes match HEAD, the skill is current.
- **Zero-bookkeeping**: nothing to forget. No `version:` line to bump in
  frontmatter on every PR. No `installed_skill_versions` map in the
  marker. No audit-of-the-audit to catch missing bumps.
- **Cheap to run**: diff is two stat calls + content compare per skill.

There is no PR-build version floor either — dev-kit does not gate consumer
builds on a plugin-version comparison, plugin- or skill-level. Per-skill
bookkeeping for both author and consumer is gone.

## Walk

Use `lib/ci_setup.py:per_skill_drift(plugin_root) -> dict[str, str]`. The
helper:

1. Walks `skills/<name>/SKILL.md` (HEAD) in this checkout.
2. Picks the **newest** installed snapshot dir at
   `~/.claude/plugins/cache/dev-kit/dev-kit/*/skills/<name>/SKILL.md`
   (semver-max when the version field is present; latest mtime
   otherwise). Falls back to
   `~/.claude/plugins/marketplaces/dev-kit/skills/<name>/SKILL.md` when
   the cache is empty. Override with `DEV_KIT_INSTALLED_ROOT` for
   offline/test.
3. Compares file bytes. Returns `behind` / `current` / `no_install`
   per skill.

## Drift classification (output rows)

| Diff result                | Drift tag      |
|----------------------------|----------------|
| Installed file bytes == HEAD | `current`     |
| Installed file bytes ≠ HEAD  | `behind`      |
| Installed snapshot missing   | `no_install`  |

(`regress` / `removed` / `invalid` are no longer applicable — diff is
binary. A "removed" skill simply doesn't appear in the output.)

## Output

```
=== /dev-kit:audit --outdated -- N behind of 30 skills ===

SKILL                  STATUS
build                  behind
audit-secret           behind
... N current ...
... (no_install) ...

To refresh: /dev-kit:ci-setup --force
```

- Sort: `behind` first, `current` middle, `no_install` last.
- 4-space fixed column for the eye to scan; do not align to the
  longest name (the table is human-readable, not machine-parseable).
- If **zero** drift: print
  `=== /dev-kit:audit --outdated -- all 30 skills current ===` and exit 0.
- No file written.

## Exit codes

- `0` if every installed skill's SKILL.md bytes match HEAD (no action).
- `1` if at least one skill is `behind` or `no_install`.

The non-zero exit lets a user wire this into a pre-commit hook or a
nightly cron with `|| true` if they only want a heads-up, or `|| exit 1`
if they want it to block.

## Edge cases

- **No installed snapshot at all** (no `~/.claude/plugins/.../dev-kit/`
  cache, no marketplace clone): every skill reports `no_install`. Exit 1
  with the message: "No installed dev-kit snapshot found — run
  `claude plugin install dev-kit` first."
- **Cache has multiple installed versions**: pick the newest mtime
  (deterministic for repeated runs). Note the pick in the output header
  so the user knows which snapshot was inspected.
- **Snapshot is non-git** (no commit metadata available): the helper
  uses raw file bytes; no `git log` is consulted. Means we can't show
  "behind by N commits", only "behind yes/no." That's the trade-off for
  zero-bookkeeping.
