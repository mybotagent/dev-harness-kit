---
name: audit
category: audit
description: 0-arg cross-cutting. Bulk slop + secret audit. READ-ONLY.
alpha: state
when_to_use:
  - User types /dev-kit:audit
  - Bulk audit before release
allowed-tools: Read Grep Glob Bash
disallowed-tools: Write Edit
model: haiku
disable-model-invocation: false
---
> [← Skills index](../../README.md)

Cross-cutting audit. Read-only. Delegates to `lib.analysis_core.run_analysis(dimensions=group("audit"), mode="read-only", paths=...)` for the slop+secret sweep. Outdated-skill drift uses `lib.ci_setup.py:per_skill_drift` directly.

**Iron Law (no exceptions).** Read-only invariant. `Write` / `Edit` disallowed. Bash only for read-only scanners (`grep`, `git diff`, `slop-detector.sh`, `secret-scan.sh`).

## Modes

- `/dev-kit:audit --secrets-only` -> secret scan only.
- `/dev-kit:audit --slop-only` -> slop scan only.
- `/dev-kit:audit --outdated` -> outdated-skill drift report.
- default -> all three combined.

## Mode 1 — secret scan

SSOT patterns: `hooks/secret-scan.sh` (AWS `AKIA...`, Anthropic `sk-*` / `sk-ant-*`, GitHub `ghp_*` / `gho_*`, Slack `xox[bpoa]-*`, PEM private keys, `postgres://user:pass@`, `mongodb+srv://user:pass@`).

Never print secret text. Report matches only (path + masked value `***`). Use `dim: "secret"` with `fix_hint: "rotate + remove"`. Severity: CRITICAL on discovery; WARN on env-file references (verify).

## Mode 2 — slop scan

Phrase bank `hooks/references/slop/phrases.md` (T1) + structure bank `hooks/references/slop/structures.md` (T2). For each file: T1 phrase scan, T2 structure scan, score on 5-dim rubric. Bucket per file: HIGH (any KO OR >=3 distinct T1 OR >=1 T1 + >=1 T2), MEDIUM (>=2 T1 OR any KO structure), LOW (1 T1 OR 1 T2), clean. Use `dim: "slop"`; HIGH/MED/LOW bucket report.

## Mode 3 — outdated-skill audit

Use `lib/ci_setup.py:per_skill_drift(plugin_root) -> dict[str, str]`. Compares installed snapshot (`~/.claude/plugins/cache/dev-kit/...` or `~/.claude/plugins/marketplaces/dev-kit/...`) against HEAD. Drift: `behind` / `current` / `no_install`. Sort: behind first, current, no_install. Stdout only — no file write.

Exit 0 if all skills current, exit 1 if any behind/no_install.

## Output (combined)

```
## /dev-kit:audit -- {path} -- {N} files / {M} matches

### CRITICAL
- path/to/file.py:42 AKIA*** (AWS key — REMOVE)

### HIGH (slop)
- README.md 8 (delve into x3, robust x2, ...)

=== /dev-kit:audit --outdated -- N behind of 30 skills ===
SKILL  STATUS
audit  behind
... N current ...
```

Next: `/dev-kit:inspect` (broader semantic sweep) or `/dev-kit:security` (OWASP A01–A10).
