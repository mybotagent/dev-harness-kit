---
name: audit-slop
category: audit
description: Multi-dim slop audit. T1 phrase + T2 structure + 5-dim scoring rubric (DIRECTNESS/RHYTHM/TRUST/AUTHENTICITY/DENSITY). HIGH/MEDIUM/LOW bucket report.
when_to_use: |
  - User types /dev-kit:audit (cross-cutting)
  - Bulk audit before release
  - Bulk scan after a content/PR rewrites prose across many files
allowed-tools: Read Grep Bash
disallowed-tools: Write Edit
model: haiku
user-invocable: false
---

# audit-slop — Multi-Dim Slop Audit (v2)

## What it does

Reads the SSOT bank at `hooks/references/slop/{phrases,structures,scoring}.md`, walks the target path, applies T1 (phrase) + T2 (structure) scans per file, scores each file on the 5-dim 1-10 rubric (Directness / Rhythm / Trust / Authenticity / Density), and emits a per-file HIGH / MEDIUM / LOW bucket with a one-line fix hint. Read-only invariant — never writes to disk.

## Iron Law

**Read-only.** `Write` / `Edit` are disallowed-tools. The audit emits a report; no file mutations. `Bash` is permitted only for read-only scanners (the `slop-detector.sh` advisory hook, or `grep -rnE`).

## SSOT (single source of truth)

| Bank | Path | Tier |
|---|---|---|
| Phrase bank | `hooks/references/slop/phrases.md` | T1 |
| Structure bank | `hooks/references/slop/structures.md` | T2 |
| Scoring rubric | `hooks/references/slop/scoring.md` | scoring |
| Examples | `hooks/references/slop/examples.md` | reference |
| Loader contract | `hooks/references/slop/README.md` | meta |

The post-write hook (`hooks/slop-detector.sh`) consumes the same two bank files. There is exactly one regex per slop signal — no duplication between hook and skill.

## Pipeline

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

### Severity rules (verbatim from scoring.md)

| Match origin | Default bucket |
|---|---|
| Any KO phrase or structure match | HIGH |
| Any EN T1 match | at least MEDIUM |
| EN structure only | LOW (consider noise) |

## Output template

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

## Filter rules

- Skip globs: `.git/`, `node_modules/`, `dist/`, `__pycache__/`, lockfiles
- Max 20 files in report
- Per-phrase count + path (token efficiency)
- Read-only -- never write
- For UI / Notion / Slack prose: enable full 5-dim scoring; for code commits (mostly): count-only

## Hook

`hooks/slop-detector.sh` (v2, multi-tier) auto-active on PostToolUse(Write|Edit|MultiEdit) when `slop-detector=ON` stage. Exit 0 advisory by default; opt-in `SLOP_STRICT=1` for exit 2 on HIGH.

## Regression fixtures

| File | Expectation |
|---|---|
| `tests/fixtures/slop/sample-with-slop.md` | HIGH bucket, >=1 fix hint |
| `tests/fixtures/slop/sample-clean.md` | 0 findings |

## Done definition

After this skill runs, the report must:
- list at most 20 files,
- bucket each by HIGH / MEDIUM / LOW / clean,
- render one-line fix hints per file pulled from `references/slop/examples.md`,
- print, on the final line, `exit 0` and the count of files inspected (token budget audit trail).

## Next step

Hand off to `/dev-kit:audit --secrets-only` for the credential scan, or `/dev-kit:inspect` for the broader code-health report.
