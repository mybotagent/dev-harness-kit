> [← Skills index](README.md) · [Project README](../../README.md)

# `build-debug`

**Category:** `build` · **Alpha:** `enforcement` · **Invocation:** Model-invoked sub-skill of `/dev-kit:build` — not exposed in slash autocomplete, never typed directly

`build-debug` exists to stop the model from jumping straight to a fix the moment something looks broken. Its Iron Law — no fix proposal before Phase 1 (reproduce) completes — forces a strict reproduce → isolate → root-cause → fix sequence so debugging sessions produce an actual root cause instead of a guess that happens to make the symptom go away.

## When to use it

- The model or user surfaces language like "bug" / "doesn't work" / "why failing" / "error" during a build step.

## How it works

The skill runs four phases as separate cycles, never bundled into one:

```
[1/4] REPRODUCE  → 1+ failing cases
       (don't proceed if reproduction fails)
       ↓
[2/4] ISOLATE    → minimal reproduction
       (reduce input / block external deps)
       ↓
[3/4] ROOT CAUSE → specific line + call stack quoted
       (tools: git blame, git bisect, log, debugger)
       ↓
[4/4] FIX        → with regression test
       (Iron Law L1: no test = no fix)
```

Rules enforced throughout: the 4 phases must not be bundled into one cycle (MUST-NO-LOOP); the user confirms after each phase, or the 4 phases run as separate calls; asserting "probably X" without a quoted root cause is disallowed; only one change is made at a time.

The `tdd-guard` hook is ON during the build stage, so writing a fix during debug forces a regression test to accompany it — the skill cannot silently skip Phase 4's test requirement even if it wanted to.

After all 4 phases complete, the skill quotes the root cause in one line, confirms the regression test is GREEN, calls `state_codec.append_hand_off(root, "build", "build", "..")`, and loops back to the per-step harness runner (`lib/execute.py`).

## Invoked automatically

`build-debug` is a model-invoked sub-skill — it has no direct slash command and does not appear in slash autocomplete. It is triggered automatically when the model or user's language matches a debugging scenario during a build step.

## Output

- A quoted one-line root cause plus a GREEN regression test run, required before the skill considers Phase 4 complete.
- A hand-off record via `state_codec.append_hand_off(root, "build", "build", "..")`, looping control back to `lib/execute.py`.

## Red flags

| Thought | Reality |
|---|---|
| "Probably X" | Unknown if not reproduced |
| "Just patch it" | Ignoring root cause → same bug repeats |
| "Multiple changes at once" | Can't tell which change was the fix |
| "Skip reproduce" | L2 violation |

## Related

- [build](build.md) — the parent skill whose per-step harness runner (`lib/execute.py`) `build-debug` loops back into.
- [build-tdd](build-tdd.md) — supplies the regression-test discipline that Phase 4's fix relies on.
- [build-verify](build-verify.md) — the evidence-before-done gate that governs completion claims elsewhere in the build stage.

---
*Source: [`skills/build-debug/SKILL.md`](../../skills/build-debug/SKILL.md)*
