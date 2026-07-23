---
name: eval
category: eval
description: Agent-behavior eval across 3 dimensions (review / security / plan) with a 20-checkbox code-sanity rubric. Replays recorded transcripts and judges against per-dim rubrics. /dev-kit:eval [--dim review|security|plan] [--case <id>] [--dry-run].
alpha: analysis
when_to_use: |
  - User types /dev-kit:eval
  - nightly cron auto-call (per-dim rotated)
  - Before merging a change to a target skill (review/security/plan) prompt
  - After a behavior regression report from /dev-kit:repair
allowed-tools: Read Grep Glob Bash Agent
disallowed-tools: Write Edit
model: opus
disable-model-invocation: false
user-invocable: true
safety:
  safety_valve: 1
  convergence: per-case axis mean >= 8.0
  dedup_metric: identical-case-score=2
  user_interrupt: true
---
> [← Skills index](../../README.md)

# /dev-kit:eval — Agent-Behavior Eval (3 dims, 20-checkbox code-sanity)

Measures whether the **agent behaves correctly** when running the dev-kit
skills. The unit of eval is a **case fixture + a recorded agent transcript
-> per-dim rubric judgment**, not a file on disk.

Three dimensions, each with its own rubric:

| Dim | Axes (0-10) | What it measures |
|---|---|---|
| `review` | `verdict_consistency` `severity_calibration` `precision` `recall` `code_sanity_score` | review verdict + findings quality + clean-code/over-eng/value rubric |
| `security` | `owasp_classification_accuracy` `severity_accuracy` `precision` | A01-A10 mapping + severity + false-positive rate |
| `plan` | `spec_clarity` `step_atomicity` `ac_executability` `dependency_ordering` | ambiguity <= 3 per step, single-deliverable steps, runnable AC, buildable order |

Verdict (per-case axis mean): **OK** at >= 8.0, **DRIFT_WARNING** 5.0-7.9, **ROT** < 5.0.

## Code-sanity rubric (composite of `code_sanity_score`)

The review judge embeds a 20-checkbox rubric. The LLM scores three sub-rubrics 0-10; the final `code_sanity_score` is the weighted composite:

```
code_sanity_score = 0.4 * clean_code_found
                  + 0.4 * over_engineering_caught
                  + 0.2 * value_articulated
```

### Clean code (8 items)

1. Vague / short names (`x`, `tmp`, `data`, `val`, `obj`)
2. Function > 50 lines or > 4 params
3. Dead code / commented-out blocks / unused imports
4. Magic numbers / strings without named constants
5. Copy-paste duplication
6. Bare `except` / swallowed errors / missing cleanup
7. Type unsafety (`any`, missing types, wrong return types)
8. Stale or misleading comments

### Over-engineering (8 items)

1. Interface with one implementer
2. Speculative params / configs for hypothetical use
3. Premature optimization without measurement
4. YAGNI: features / flags for hypothetical futures
5. Excessive layering (3+ layers for trivial logic)
6. Factory / Strategy pattern for single implementation
7. Deep inheritance without polymorphism
8. 1-class-per-file without justification

### Value / meaning (4 items)

1. Change has a stated purpose tied to a real user need
2. Not noise / cosmetic / churn
3. Scope matches the problem (no creep)
4. The diff earns its lines

Per sub-score = `(items_flagged / items_present_in_input) * 10`. A reviewer that does not surface even the obvious items in a planted fixture scores 0 on the relevant sub-rubric.

## Inputs / outputs

- **Input**: a `--dim` filter (default: all 3) and an optional `--case <id>` filter.
- **Case discovery**: scans `eval/cases/{review,security,plan}/*.json` (12 seed cases).
- **Transcript replay**: reads `eval/transcripts/<dim>/<case_id>.json` for the recorded agent output. Missing transcript -> case skipped (logged, not failed).
- **Per-dim judge prompt**: `eval/prompts/judge-<dim>.md` returns a JSON object with the dim's axes.
- **Code-sanity rubric prompt**: `eval/prompts/judge-code-sanity.md` is the shared 20-checkbox rubric the `review` judge invokes for the `code_sanity_score` axis.
- **Output**: `.dev-kit/eval-report.md` with a per-dim table (axis means + verdict counts).

## Opt-in flags (default OFF)

The session-log judge and golden-diff paths are **never auto-invoked**.
They cost extra LLM calls and only fire when the user explicitly passes
the flag (or the `tools/session_monitor.py` handshake emits a request).
Wire them from a script, not from CI.

| Flag | What it does | Output |
|---|---|---|
| `--session-log <path>` | Judge one session log on the 8-axis session rubric (`eval/prompts/judge-session.md`). 1 LLM call, cached by `session_id`. | JSON summary to stdout; `--write-session-report` also writes `.dev-kit/session-eval-report.md`. |
| `--golden-diff` | Diff the current `run_eval` result against `eval/golden/*.json` (schema 2.0.0 baselines) and emit regression markers per axis. | JSON summary to stdout; `--write-regression-report` also writes `.dev-kit/regression-report.md`. |

These flags are independent: `--session-log` short-circuits the
case-based path (the session is the unit of judgment, not a case),
and `--golden-diff` only runs after a case-based `run_eval` completes.

## CLI

```
python lib/eval_runner.py --project-root . [--dry-run] [--dim review|security|plan] [--case <id>]
python lib/eval_runner.py --project-root . --session-log logs/cc/<sid>.jsonl [--write-session-report]
python lib/eval_runner.py --project-root . --golden-diff [--write-regression-report]
```

- `--dry-run` — skip LLM calls; mock each case at 7.0/DRIFT_WARNING (no API key required).
- `--dim` — restrict to one dimension. Default: all 3.
- `--case` — restrict to a single `case_id`.
- `--session-log` — opt-in: judge one session log on the 8-axis rubric. Default: OFF.
- `--golden-diff` — opt-in: diff the run_eval result against `eval/golden/*.json`. Default: OFF.
- `--write-session-report` — emit `.dev-kit/session-eval-report.md` from a `--session-log` run.
- `--write-regression-report` — emit `.dev-kit/regression-report.md` from a `--golden-diff` run.

## Failure modes

- Missing transcript for a case -> that case is **skipped** (logged in report), not failed. A new case without a transcript is a setup gap, not a regression.
- Judge API error -> case marked **ROT** with `error` field, loop continues. One bad case does not abort the eval.
- LLM returns malformed JSON -> `parse_scores_json` falls back to regex extract; if still empty -> score 0 -> ROT.
- Empty / unreadable session log under `--session-log` -> report marked **ROT** with `error="empty or unreadable session log"`; no LLM call.
- Missing `eval/golden/` under `--golden-diff` -> empty regression report (`summary.markers=0`); never errors.

## Rules

- DRIFT_WARNING -> log + continue. Do not auto-repair.
- ROT -> log + continue. `/dev-kit:repair` may pick up the case if the eval is wired to the repair loop.
- Adding a case: drop a JSON into `eval/cases/<dim>/<name>.json` + a recorded transcript into `eval/transcripts/<dim>/<name>.json`. No code change required.
- `--session-log` and `--golden-diff` are **opt-in only**: no CI wiring, no cron, no auto-trigger from `tools/session_monitor.py` (the monitor only emits a handshake pointer — it does not call the judge itself).

## Hook integration (Stage Eval)

- `slop-detector=ON`, `stop-verify=ON`. `tdd-guard=OFF` (no production code here).
- Eval is read-only on disk (transcripts are pre-recorded; the judge only writes the report).

## Next step

On DRIFT_WARNING or ROT, `/dev-kit:repair` may invoke this skill to confirm the regression is still present after a fix attempt. Manual review recommended before any prompt change to a target skill.

## Related

- `/dev-kit:report` reads `.dev-kit/eval-report.md` (this skill's
  output) and renders it as a self-contained HTML page. Run report
  after eval to share results with non-technical reviewers.
