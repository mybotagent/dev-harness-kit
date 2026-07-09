---
name: audit-secret
category: audit
description: secret scan read-only audit. credential pattern detection. NEVER print secret text.
when_to_use: |
  - User types /dev-kit:audit (cross-cutting, or --secrets-only flag)
allowed-tools: Read Grep Bash
disallowed-tools: Write Edit
model: haiku
user-invocable: false
---

# audit-secret — Read-Only Credential Audit

## Iron Law
**Never print secret text ❌.** Report matches only (path + masked value `***`).

## SSOT

`hooks/secret-scan.sh` patterns:
- `AKIA...` (AWS)
- `sk-...` / `sk-ant-...` (Anthropic)
- `ghp_...` / `gho_...` (GitHub)
- `xox[bpoa]-...` (Slack)
- `-----BEGIN ... PRIVATE KEY-----`
- `postgres://user:pass@`
- `mongodb+srv://user:pass@`

## Output

```markdown
## /dev-kit:audit secret — {path} — {N} files / {M} matches

### CRITICAL
- src/auth.ts:42 `AKIA***` (AWS key — REMOVE)

### WARN
- scripts/setup.sh:8 — env file reference (verify)
```

## Rules

- Discovery → immediate CRITICAL. Fail-open mode also warns.
- Line number required. One masked value example only.
- Read-only — never write ❌.

## Hook

`secret-scan.sh` auto-active on PostToolUse (Build/Review/Security).

## Regression

- empty fixture → 0 finding
- leaked fixture (rotated) → masked-only report