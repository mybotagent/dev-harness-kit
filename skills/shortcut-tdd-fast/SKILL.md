---
name: shortcut-tdd-fast
category: shortcuts
description: Bootstrap+Plan bypass → straight to Build. Marks hand-off stub. For urgent hotfix.
when_to_use: |
  - User types /dev-kit:tdd-fast
  - urgent hotfix
allowed-tools: Read Write Bash
disallowed-tools: WebFetch Agent
model: sonnet
---

# shortcut-tdd-fast — Bypass to Build

## Iron Law
**Only when user explicitly expresses bypass intent.** Urgent hotfix / prototype scenarios.

## Behavior

1. Plan/Design hand-off stub auto-marked (`.dev-kit/hand-off/plan→build.md` empty file)
2. `.dev-kit/state.json` `shortcut_used: "tdd-fast"` recorded
3. Build immediate (harness-runner engine)
4. Review/Security stages follow on subsequent calls

## Rules

- 6 gates of Plan stage auto-skip (only on explicit user OK)
- Subsequent `/dev-kit:plan` call returns to normal flow
- No automatic user-code changes (TDD cycle preserved)

## Hook integration

Same as Build stage.

## Subsequent hand-off

`build→review.md` (full chain normal) + separate `plan→build.md` stub for audit.