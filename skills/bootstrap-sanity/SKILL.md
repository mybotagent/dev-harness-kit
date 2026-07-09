---
name: bootstrap-sanity
category: bootstrap
description: read-only audit of project preconditions. Deterministic (regex + glob, no LLM call). Outputs PASS/WARN/FAIL to .dev-kit/sanity-report.md.
version: 0.1.0
when_to_use: |
  - When `/dev-kit:bootstrap` first run
  - When user runs `/dev-kit:audit` with --sanity-only
allowed-tools: Read Glob Bash
disallowed-tools: Write Edit WebFetch Agent
model: haiku
disable-model-invocation: false
user-invocable: false
---

# bootstrap-sanity — Read-Only Precondition Audit

## Iron Law (no exceptions)
**Never modify files.** Read input directory only; emit result to `.dev-kit/sanity-report.md`.

## Gate output

| Result | Condition |
|---|---|
| **PASS** | All required preconditions pass |
| **WARN** | 1~3 WARN (pass-through allowed) |
| **FAIL** | 4+ WARN or 1+ critical — Plan entry ❌ |

## 7-Check Audit (deterministic)

| # | Check | Tool | Severity |
|---|---|---|---|
| 1 | `package.json` or `pyproject.toml` exists (manifest) | `Glob` | WARN |
| 2 | `.git/` directory healthy (HEAD exists) | `Bash: git rev-parse --git-dir` | WARN |
| 3 | `docs/` directory has 4 template placeholders (`ARCHITECTURE.md`, `PRD.md`, `ADR.md`, `DESIGN.md`) | `Glob` | WARN |
| 4 | banned-phrase scan (slop-detector SSOT regex) | `Bash: slop-detector.sh` (read-only) | WARN |
| 5 | secret-scan (credential pattern) | `Bash: secret-scan.sh` (read-only) | **CRITICAL FAIL** |
| 6 | hook bypass detection (`DEV_KIT_HOOK_OFF=*` env) | `Bash: env \| grep` | WARN |
| 7 | methodology lockfile (`lib/methodology.json` consistency) | `Read` | WARN |

## Output format

```markdown
# Sanity Report — dev-harness-kit
- scanned_at: ISO-8601 KST
- target: <absolute path>
- result: PASS / WARN / FAIL
- checks:
  - [PASS] check_1: package.json found
  - [PASS] check_2: .git/ OK
  - [WARN] check_3: docs/DESIGN.md template missing (Bootstrap will create)
  ...
- critical_issues: []
- recommendations:
  - "ok to proceed to /dev-kit:plan"
```

## Rules (no exceptions)

- **Read-only invariant**: no file modifications ❌. Validation uses Read + Glob + Bash (stat/grep/cat) only.
- **Zero LLM calls**: deterministic. Result reproducible.
- **Fail fast**: 1 critical → immediate FAIL + Plan entry blocked.

## Hook integration

In Bootstrap stage via active-hooks.json:
- `slop-detector=OFF` (sanity itself is the slop check)
- `secret-scan=read-only` (sanity result can detect secrets)
- `bash-guard=OFF` (sanity only calls safe Bash)