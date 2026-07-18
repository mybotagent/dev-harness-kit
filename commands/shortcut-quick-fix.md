---
name: shortcut-quick-fix
category: shortcuts
description: verify+debug instant call. No code writing. Quick build verification / debug.
alpha: analysis
when_to_use: |
  - User types /dev-kit:quick-fix
alpha: enforcement
---

## Invocation

Arguments: `$ARGUMENTS` — optional scope or target path for the verify+debug pass.

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
