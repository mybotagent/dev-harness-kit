> [← Skills index](README.md) · [Project README](../../README.md)

# `repair`

**Category:** `repair` · **Alpha:** `state` · **Invocation:** `/dev-kit:repair approve|reject|defer <asset>` (human-invoked)

`repair` is the 8-step Eval-Repair loop: it reads a golden set, scores an asset against it, root-causes the failures, invokes a specialized fixer, re-evaluates the candidate fix, validates against the golden invariant, and writes a draft diff — but never applies that diff itself. The final step is always a single human decision (`approve`, `reject`, or `defer`), and the skill never auto-commits (MUST-NOT-31). It exists to close the loop between eval failures (from `/dev-kit:eval`) and a reviewable, human-gated fix.

## When to use it

- The user types `/dev-kit:repair approve|reject|defer <asset>`.

## How it works

The 8 automated steps, in order:

1. **Read golden_set** — load the reference examples the asset must satisfy.
2. **LLM as Judge** — score the asset on a 4-axis rubric.
3. **Score failures + root cause** — identify why the failing cases fail.
4. **Invoke Specialized Fixer** — dispatch to one of 9 fixer categories matched to the root cause.
5. **Fix candidate → re-evaluate** — apply the candidate fix and re-run the judge, looping up to 3 times.
6. **A/B Validation Regression** — check the fix against the golden invariant to confirm no regression.
7. **Auto-write draft diff** — write the proposed change to `.dev-kit/repair/<asset>.diff` without applying it.
8. **Human Review** — the terminal step; the user must explicitly run `approve`, `reject`, or `defer` on the asset. No step past this point runs automatically.

The skill's `allowed-tools` are `Read Grep Glob Bash Agent`; `Edit` and `Write` are explicitly disallowed, which is what makes step 7's diff a draft rather than a live edit — the diff can only be materialized into the working tree via the human-invoked `approve` command.

## Usage

```bash
/dev-kit:repair list
/dev-kit:repair approve <asset>
/dev-kit:repair reject <asset>
/dev-kit:repair defer <asset>
```

| Command | Effect |
|---|---|
| `list` | Shows the pending diff list. |
| `approve <asset>` | Applies the draft diff (`git apply`). |
| `reject <asset>` | Discards the diff and adds a golden regression pattern so the same failure is caught in future eval runs. |
| `defer <asset>` | Preserves the diff for a later decision, without applying or discarding it. |

## Output

`.dev-kit/repair/<asset>.diff` — the draft diff written at step 7, which persists until the user resolves it via `approve`, `reject`, or `defer`.

## Related

- `/dev-kit:eval` — the source of the failures this skill root-causes and repairs.
- `/dev-kit:babysit-pr` — recommended on abnormal exit if the failure looks like a golden-asset regression.

---
*Source: [`skills/repair/SKILL.md`](../../skills/repair/SKILL.md)*
