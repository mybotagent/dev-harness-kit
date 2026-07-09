---
name: audit-slop
category: audit
description: slop-detector SSOT bulk audit. KO+EN banned phrase scan. HIGH/MEDIUM/LOW buckets report.
when_to_use: |
  - User types /dev-kit:audit (cross-cutting)
  - Bulk audit before release
allowed-tools: Read Grep Bash
disallowed-tools: Write Edit
model: haiku
user-invocable: false
---

# audit-slop — Read-Only Slop Audit

## Iron Law
**Read-only invariant.** No file modifications ❌. Grep output only — report.

## SSOT

`hooks/slop-detector.sh` `SLOP=` regex (single source of truth). 17 EN + KO equivalent phrases.

## Output

```markdown
## /dev-kit:audit slop — {path} — {N} files / {M} total matches

### HIGH (≥5 matches)
- README.md 8 (delve into×3, robust×2, cutting-edge×3, ...)

### MEDIUM (2-4)
- docs/STAGES.md 3

### LOW (1)
- skill/t.skill
```

## Rules

- Skip globs: `.git/`, `node_modules/`, `dist/`, `__pycache__/`, lockfiles
- Max 20 files in report
- Per-phrase count + path (token efficiency)
- Read-only — never write ❌

## Hook

slop-detector.sh auto-active on PostToolUse (slop-detector=ON stage).

## Regression fixture

- `examples/sample-with-slop.md` → HIGH ≥ 1 report
- `examples/sample-clean.md` → 0 finding