---
name: feat-fix
category: build
description: Reproduce-first fix for a single named feature. MUST-L2 enforces a quoted failing case before any fix proposal lands.
when_to_use: |
  - User types /dev-kit:feat-fix <feature>
  - User knows which feature is broken (vs /dev-kit:build-debug for unknown bugs)
  - The feature boundary is identifiable in code or in the plan
allowed-tools: Read Bash Glob Grep
disallowed-tools: Edit Write WebFetch
model: opus
disable-model-invocation: false
user-invocable: true
---

## What it does

Fixes a known-broken feature in 4 separate phases — Reproduce, Isolate, Root-Cause, Fix — with the same Iron Laws as `build-debug` but bounded to one named feature boundary. Produces a regression test, a one-line root cause, and a hand-off back to `build`. The skill itself never writes the fix — it produces the diagnosis and waits for the user to apply the patch, mirroring the `build-debug` write-prevention pattern.

## Iron Law

**MUST-L2 — no fix proposal before a quoted failing case exists.** Phase 1 is reproduce; it must succeed before any of the next three phases start.

## 4 phases (separate cycles)

```
[1/4] REPRODUCE  → quoted failing case (run command, paste output)
       (don't proceed if reproduction fails)
       ↓
[2/4] ISOLATE    → minimal reproduction within the <feature> boundary
       (strip unrelated inputs, mock external deps)
       ↓
[3/4] ROOT CAUSE → specific line + call stack quoted
       (tools: git blame, git bisect, log, debugger)
       ↓
[4/4] FIX        → with regression test
       (Iron Law L1: no regression test = no fix; the user applies the patch)
```

## Rules (no exceptions)

- MUST-NO-LOOP: do not bundle 4 phases into one cycle. User confirmation after each phase, or 4 phases in separate tool calls.
- MUST-L2: "probably X" without a quoted reproduction is rejected outright.
- One change at a time. Multiple changes at once breaks attribution.
- Fix is scoped to `<feature>`. If the root cause lives outside the boundary, stop and call `/dev-kit:build-debug` (generic) instead.

## Hook integration

| Hook | Mode |
|---|---|
| tdd-guard | ON — the regression test in Phase 4 must exist before the user applies the fix |
| bash-guard | ON |
| stop-verify | ON — completion requires a quoted root cause + a green regression test |

## Output

- `.dev-kit/hand-off/feat-fix→build.md` containing:
  - One-line root cause quoted from the codebase (path + line).
  - Regression test path + quoted green run output (test count + duration).
  - Diff summary of the fix (files touched, lines added/removed).

## Red flags

| Thought | Reality |
|---|---|
| "Probably X" | Unknown if not reproduced. L2 violation. |
| "Just patch it" | Ignoring root cause → same bug recurs. |
| "Fix two features at once" | Out of scope. Run `feat-fix` again. |
| "I'll write the regression test after" | L1 violation. Test exists before the fix. |

## Next step

Hand off to `/dev-kit:build` to resume the phase, or `/dev-kit:feat-revise` if the root cause reveals the AC itself was wrong.
