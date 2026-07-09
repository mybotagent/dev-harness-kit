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

## Rules

- `/dev-kit:audit --secrets-only` → secrets only
- `/dev-kit:audit --slop-only` → slop only
- `/dev-kit:audit --outdated` → outdated-skill audit (delegates to `audit-outdated` subskill — installed vs HEAD per-skill semver drift)
- combined mode (default) → all three above

## Related

- `/dev-kit:inspect` is the **broader, project-wide, semantic** sibling:
  6-dim fan-out (dead/dup/smell/overeng/cleancode/slop) → markdown
  report at `.dev-kit/inspect-report.md`. Use `inspect` when you want
  a deep, semantic health sweep across the whole codebase; use `audit`
  when you want the fast, shallow, deterministic phrase+secret scan.