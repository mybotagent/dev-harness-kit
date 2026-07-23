> [← Skills index](README.md) · [Project README](../../README.md)

# `build-tdd`

**Category:** `build` · **Alpha:** `enforcement` · **Invocation:** Model-invoked sub-skill of `/dev-kit:build` — not exposed in slash autocomplete, never typed directly

`build-tdd` is the Red-Green-Refactor sub-skill active during the build stage whenever `methodology=tdd` (the default). Its Iron Law — no production code without a failing test, because you cannot know the test fails without running it — exists as its own skill because TDD discipline is easy to rationalize away in the moment ("just this once", "it's simple"); the `tdd-guard` hook backs the rule with a deterministic write-time block rather than relying on the model to police itself.

## When to use it

- The user's language is "build X" / "add X" / "implement X".
- It is the active sub-skill of `/dev-kit:build` whenever `methodology=tdd` (the default).

## How it works

The cycle runs as:

```
RED      → Write a failing test
           ↓ Run it and confirm RED directly
GREEN    → Write minimum implementation to pass
           ↓ Confirm all tests GREEN
REFACTOR → Clean up without changing behavior
           ↓ Confirm tests still GREEN
           ↓ Next cycle
```

`tdd-guard.sh` is a PreToolUse hook on `Write|Edit|MultiEdit` that blocks writes under `lib/`, `src/lib`, `src/utils`, and `app/api/services/domain/` unless a test already exists for the change (co-located or under `tests/`).

Rules enforced: code written before its test is deleted and the cycle restarted; "just for reference" / "it's simple" are treated as rationalizations and rejected outright; RED must be confirmed by actually running the test and seeing it fail as intended; only one cycle runs at a time, and cycle N+1 starts only after cycle N is GREEN.

The full workflow per cycle: state the requirement in one sentence; write the test file first with at least one failing case; confirm RED by running it; write the minimum GREEN implementation to pass; REFACTOR to remove duplication and improve naming; move to the next cycle.

Exceptions to the Iron Law require explicit user approval, and are limited to: a throwaway prototype or one-off script; auto-generated code (migrations, generated clients); or config files, type definitions, and static assets.

## Invoked automatically

`build-tdd` is a model-invoked sub-skill — it has no direct slash command and does not appear in slash autocomplete. It activates automatically inside `/dev-kit:build` whenever the active methodology is `tdd`.

## Output

No standalone report file — the skill's deliverable is the RED→GREEN→REFACTOR cycle itself, each step confirmed by an actual test run rather than an assertion.

## Red flags

| Thought | Reality |
|---|---|
| "Skip just this once" | Rationalization. Stop. |
| "Add tests later" | Tests-after are not TDD |
| "Too simple to test" | Simple code breaks too |
| "Refactor without tests" | Refactor also needs TDD |

## Related

- [build](build.md) — the parent skill; `build-tdd` is the active methodology sub-skill when `methodology=tdd`.
- [build-debug](build-debug.md) — invoked when a build step surfaces a bug rather than a straightforward implementation task.
- [build-verify](build-verify.md) — the evidence-before-done gate that governs completion claims once a cycle's tests pass.
- `hooks/tdd-guard.sh` — the PreToolUse hook enforcing the write-time test-first block.

---
*Source: [`skills/build-tdd/SKILL.md`](../../skills/build-tdd/SKILL.md)*
