---
name: build-tdd
category: build
description: Red-Green-Refactor cycle. Active when methodology=tdd (default). No production code without a failing test. tdd-guard hook enforces.
alpha: enforcement
when_to_use: |
  - User types "build X" / "add X" / "implement X"
  - methodology=tdd (default) sub-skill of /dev-kit:build
allowed-tools: Read Write Edit Bash
disallowed-tools: WebFetch Agent
model: opus
user-invocable: false
---
> [← Skills index](../../README.md)

# build-tdd — Red-Green-Refactor

## Iron Law
```
No production code without a failing test.
You cannot know the test fails without running it.
```

## Cycle

```
RED      → Write a failing test
           ↓ Run it and confirm RED directly
GREEN    → Write minimum implementation to pass
           ↓ Confirm all tests GREEN
REFACTOR → Clean up without changing behavior
           ↓ Confirm tests still GREEN
           ↓ Next cycle
```

## Hook integration

`tdd-guard.sh` (PreToolUse Write|Edit|MultiEdit) blocks writes under `lib/`, `src/lib`, `src/utils`, `app/api/services/domain/` unless a test exists (co-located or in `tests/`).

## Rules (no exceptions)

- Code written before the test → **delete and restart.**
- "Just for reference" / "It's simple" → rationalization. **Reject all.**
- RED confirmation is required (run the test, see it fail as intended).
- One cycle at a time. Cycle N+1 only after cycle N is GREEN.

## Red Flags — stop immediately

| Thought | Reality |
|---|---|
| "Skip just this once" | Rationalization. Stop. |
| "Add tests later" | Tests-after are not TDD |
| "Too simple to test" | Simple code breaks too |
| "Refactor without tests" | Refactor also needs TDD |

## Exceptions (only with explicit user approval)

- Throwaway prototype / one-off script
- Auto-generated code (migrations, generated clients)
- Config files / type definitions / static assets

## Workflow

1. Requirement in one sentence
2. Write test file first — at least one failing case
3. Confirm RED (run)
4. Write GREEN — minimum code to pass
5. REFACTOR — remove duplication, improve naming
6. Next cycle