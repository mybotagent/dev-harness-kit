---
name: shortcut-quick-fix
category: shortcuts
description: verify+debug instant call. No code writing. Quick build verification / debug.
version: 0.1.0
when_to_use: |
  - User types /dev-kit:quick-fix
allowed-tools: Read Bash
disallowed-tools: Write Edit WebFetch
model: sonnet
---

# shortcut-quick-fix — Verify + Debug Fast-Path

## Iron Law
**build/fix ✕ / verify + debug ◯.** No code changes ❌.

## Behavior

```
1. Call build-verify SKILL (verification-before-completion)
2. On fail → auto-call build-debug SKILL (4-phase)
3. STOP — wait for user interrupt
4. /dev-kit:build call resumes normal flow
```

## Rules

- read-only + run-tests only
- Edit/Write tools ❌
- Fast verify + debug loop → report to user

## Hook integration

Same as Build stage (tdd-guard OFF, verify ON).