---
name: audit
category: audit
description: 0-arg cross-cutting. Bulk slop + secret audit. READ-ONLY.
when_to_use: |
  - User types /dev-kit:audit
  - Bulk audit before release
allowed-tools: Read Grep Glob Bash
disallowed-tools: Write Edit
model: haiku
disable-model-invocation: false
---

# /dev-kit:audit — Cross-cutting audit

read-only. HIGH/MEDIUM/LOW buckets output. Never write ❌.

## Iron Law (no exceptions)

**Read-only invariant.** `Write` / `Edit` are disallowed-tools. Every mode below emits a report; no file mutations. `Bash` is permitted only for read-only scanners (`slop-detector.sh` advisory hook, `secret-scan.sh`, `grep -rnE`, `git diff`, etc.).

## Modes

- `/dev-kit:audit --secrets-only` → secret scan only (audit-secret mode, below)
- `/dev-kit:audit --slop-only` → slop scan only (audit-slop mode, below)
- `/dev-kit:audit --outdated` → outdated-skill audit (audit-outdated mode, below)
- combined mode (default) → all three above

---

## Mode 1 — secret scan (`audit-secret`)

**Iron Law:** never print secret text ❌. Report matches only (path + masked value `***`).

### SSOT patterns

`hooks/secret-scan.sh` patterns:
- `AKIA...` (AWS)
- `sk-...` / `sk-ant-...` (Anthropic)
- `ghp_...` / `gho_...` (GitHub)
- `xox[bpoa]-...` (Slack)
- `-----BEGIN ... PRIVATE KEY-----`
- `postgres://user:pass@`
- `mongodb+srv://user:pass@`

### Output format

```markdown
## /dev-kit:audit secret — {path} — {N} files / {M} matches

### CRITICAL
- src/auth.ts:42 `AKIA***` (AWS key — REMOVE)

### WARN
- scripts/setup.sh:8 — env file reference (verify)
```

### Rules

- Discovery → immediate CRITICAL. Fail-open mode also warns.
- Line number required. One masked value example only.
- Read-only — never write ❌.
- Hook: `secret-scan.sh` auto-active on PostToolUse (Build/Review/Security).
- Regression fixtures: empty → 0 finding; leaked (rotated) → masked-only report.

---

## Mode 2 — slop scan (`audit-slop`, v2)

Multi-dim slop audit. T1 phrase + T2 structure + 5-dim scoring rubric
(DIRECTNESS/RHYTHM/TRUST/AUTHENTICITY/DENSITY). HIGH/MEDIUM/LOW bucket report.

### SSOT

| Bank | Path | Tier |
|---|---|---|
| Phrase bank | `hooks/references/slop/phrases.md` | T1 |
| Structure bank | `hooks/references/slop/structures.md` | T2 |
| Scoring rubric | `hooks/references/slop/scoring.md` | scoring |
| Examples | `hooks/references/slop/examples.md` | reference |
| Loader contract | `hooks/references/slop/README.md` | meta |

The post-write hook (`hooks/slop-detector.sh`) consumes the same two bank files. There is exactly one regex per slop signal — no duplication between hook and skill.

### Pipeline

```text
1. Walk {path}; skip .git/, node_modules/, dist/, __pycache__/, .lock, *.min.{js,css}, *.lock.json, pnpm-lock.yaml, package-lock.json, yarn.lock.
2. For each surviving file:
   a. Run T1 phrase scan via `grep -oE -f <(grep -vE '^[[:space:]]*#|^$' hooks/references/slop/phrases.md) <file>`.
   b. Run T2 structure scan via the same pattern against `structures.md`.
   c. Score each finding on the 5-dim rubric (see scoring.md).
3. Bucket each file:
   - HIGH    -> any KO match OR >=3 distinct T1 OR (>=1 T1 AND >=1 T2)
   - MEDIUM  -> >=2 distinct T1 OR any KO structure
   - LOW     -> 1 distinct T1 OR 1 T2 (no KO)
   - clean   -> 0 findings
4. Emit report; max 20 files shown, capped at first evidence.
```

### Severity rules

| Match origin | Default bucket |
|---|---|
| Any KO phrase or structure match | HIGH |
| Any EN T1 match | at least MEDIUM |
| EN structure only | LOW (consider noise) |

### Output template

```markdown
## /dev-kit:audit slop -- {path} -- {N} files / {M} total matches

### HIGH (>=5 matches)
- README.md 8 (delve into x3, robust x2, cutting-edge x3, ...)

### MEDIUM (2-4)
- docs/STAGES.md 3

### LOW (1)
- skill/t.skill

### Top fix hints (per reference/examples.md)
- {file} -> {one-line replacement}
```

### Filter rules

- Skip globs: `.git/`, `node_modules/`, `dist/`, `__pycache__/`, lockfiles
- Max 20 files in report
- Per-phrase count + path (token efficiency)
- For UI / Notion / Slack prose: enable full 5-dim scoring; for code commits (mostly): count-only

### Regression fixtures

| File | Expectation |
|---|---|
| `tests/fixtures/slop/sample-with-slop.md` | HIGH bucket, >=1 fix hint |
| `tests/fixtures/slop/sample-clean.md` | 0 findings |

---

## Mode 3 — outdated-skill audit (`audit-outdated`)

Read-only per-skill drift report. Compares the dev-kit plugin snapshot the
user has **installed** against the **HEAD** checkout of `dev-harness-kit`.
Surfaces skills whose installed file content differs from HEAD, so the
user can decide whether to `/dev-kit:ci-setup --force`.

### Iron Law
**Read-only ❌.** No file writes. No edits. Stdout only — no
`audit-report.md` (KISS; committing a generated report risks bit-rot;
future consumers can redirect stdout to a file if persistence is needed).

### Why file-content diff (not per-skill versions)

Drift detection at the SKILL.md file-content level is:
- **Honest**: a version number can lie; file bytes cannot. If the
  installed SKILL.md bytes match HEAD, the skill is current.
- **Zero-bookkeeping**: nothing to forget. No `version:` line to bump in
  frontmatter on every PR. No `installed_skill_versions` map in the
  marker. No audit-of-the-audit to catch missing bumps.
- **Cheap to run**: diff is two stat calls + content compare per skill.

There is no PR-build version floor either — dev-kit does not gate consumer
builds on a plugin-version comparison, plugin- or skill-level.

### Walk

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

### Drift classification

| Diff result                | Drift tag      |
|----------------------------|----------------|
| Installed file bytes == HEAD | `current`     |
| Installed file bytes ≠ HEAD  | `behind`      |
| Installed snapshot missing   | `no_install`  |

### Output

```
=== /dev-kit:audit --outdated -- N behind of 30 skills ===

SKILL                  STATUS
build                  behind
audit                  behind
... N current ...
... (no_install) ...

To refresh: /dev-kit:ci-setup --force
```

- Sort: `behind` first, `current` middle, `no_install` last.
- 4-space fixed column for the eye to scan; do not align to the
  longest name.
- If **zero** drift: print
  `=== /dev-kit:audit --outdated -- all 30 skills current ===` and exit 0.
- No file written.

### Exit codes

- `0` if every installed skill's SKILL.md bytes match HEAD (no action).
- `1` if at least one skill is `behind` or `no_install`.

The non-zero exit lets a user wire this into a pre-commit hook or a
nightly cron with `|| true` if they only want a heads-up, or `|| exit 1`
if they want it to block.

### Edge cases

- **No installed snapshot at all**: every skill reports `no_install`. Exit 1
  with the message: "No installed dev-kit snapshot found — run
  `claude plugin install dev-kit` first."
- **Cache has multiple installed versions**: pick the newest mtime
  (deterministic for repeated runs). Note the pick in the output header.
- **Snapshot is non-git** (no commit metadata available): the helper
  uses raw file bytes; no `git log` is consulted. That's the trade-off for
  zero-bookkeeping.

---

## Related

- `/dev-kit:inspect` is the **broader, project-wide, semantic** sibling:
  6-dim fan-out (dead/dup/smell/overeng/cleancode/slop) → markdown
  report at `.dev-kit/inspect-report.md`. Use `inspect` when you want
  a deep, semantic health sweep across the whole codebase; use `audit`
  when you want the fast, shallow, deterministic phrase+secret scan.