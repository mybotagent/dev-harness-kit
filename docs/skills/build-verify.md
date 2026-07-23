> [← Skills index](README.md) · [Project README](../../README.md)

# `build-verify`

**Category:** `build` · **Alpha:** `enforcement` · **Invocation:** Model-invoked sub-skill of `/dev-kit:build` — not exposed in slash autocomplete, never typed directly

`build-verify` enforces evidence-before-completion (MUST-L3): no "done" claim is accepted without a quoted exit code, test count, or build log. It exists as its own skill because "done" is exactly the kind of claim a model can make confidently without actually having checked — the `stop-verify` hook backs the rule at the Stop-event layer so the check does not depend on the model remembering to run it.

## When to use it

- The user uses a declaration phrase such as "done" / "finished" / "passing".

## How it works

Verification evidence is ranked strong to weak:

```
1. exit code (test runner / linter / build)
2. test count (passed/failed/skipped)
3. lint count
4. runtime log (last 30 lines)
5. file path + line number cited
```

Phrases like "should work" / "probably fine" / "done" without evidence are disallowed. When a "passing" claim is made, the `stop-verify` hook auto-warns on stderr:

```
[verify-gate] You said it works but cited no output/exit/test evidence.
[verify-gate] Run the verify command and quote the output.
```

Enforcement is 2-layer (MUST-9): (a) the hook's automatic check and (b) the skill's own advisory. Regression fixtures under `fixtures/real-bugs/` are recommended as supporting evidence.

`stop-verify.sh` is auto-active in the Build, Review, Security, and Ship stages. When the user says "done" / "finished", the hook receives the Stop event, runs the verify command, and writes the result to stderr. A passing example: the hook runs `pytest`, reports "passed 12, failed 0, error 0", and confirms "Iron Law L3 verified." A failing example: the hook emits the `[verify-gate]` warning shown above because no evidence was cited.

On a verify pass, the skill calls `state_codec.transition_stage(root, "review")` automatically. On failure, control loops back to the per-step harness runner (`lib/execute.py`).

## Invoked automatically

`build-verify` is a model-invoked sub-skill — it has no direct slash command and does not appear in slash autocomplete. It activates whenever a declaration phrase is used, and its backing hook (`stop-verify.sh`) is active across Build, Review, Security, and Ship stages.

## Output

- A quoted exit code, test count, or build-log excerpt substantiating any "done" claim.
- On pass: an automatic stage transition to `review` via `state_codec.transition_stage`.
- On fail: a loop back to the per-step harness runner (`lib/execute.py`).

## Related

- [build](build.md) — the parent skill whose steps this gate verifies before allowing a stage transition.
- [build-debug](build-debug.md) — where a failed verify commonly routes to for systematic reproduction.
- `hooks/stop-verify.sh` — the Stop-event hook backing this skill's enforcement.
- `fixtures/real-bugs/` — recommended regression fixtures cited as verification evidence.

---
*Source: [`skills/build-verify/SKILL.md`](../../skills/build-verify/SKILL.md)*
