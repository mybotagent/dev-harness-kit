> [← Skills index](README.md) · [Project README](../../README.md)

# `eval`

**Category:** `eval` · **Alpha:** `analysis` · **Invocation:** `/dev-kit:eval` (human-invoked)

`eval` measures whether the **agent behaves correctly** when running dev-kit skills, across three dimensions — review, security, plan — each with its own rubric. The unit of eval is a case fixture plus a recorded agent transcript judged against a per-dimension rubric, not a file on disk, so the skill validates agent *behavior* rather than code.

## When to use it

- The user types `/dev-kit:eval`.
- A nightly cron auto-call rotates through dimensions.
- The user is about to merge a change to a target skill's (review/security/plan) prompt.
- A behavior regression report comes back from `/dev-kit:repair`.

## How it works

Three dimensions, each judged on its own 0–10 axes:

| Dim | Axes (0-10) | What it measures |
|---|---|---|
| `review` | `verdict_consistency` `severity_calibration` `precision` `recall` `code_sanity_score` | Review verdict + findings quality + clean-code/over-eng/value rubric |
| `security` | `owasp_classification_accuracy` `severity_accuracy` `precision` | A01–A10 mapping + severity + false-positive rate |
| `plan` | `spec_clarity` `step_atomicity` `ac_executability` `dependency_ordering` | Ambiguity ≤ 3 per step, single-deliverable steps, runnable acceptance criteria, buildable order |

Verdict is computed per case as the axis mean: **OK** at ≥ 8.0, **DRIFT_WARNING** at 5.0–7.9, **ROT** below 5.0.

### Code-sanity rubric (composite of `code_sanity_score`)

The `review` judge embeds a 20-checkbox rubric. The LLM scores three sub-rubrics 0–10, and the final `code_sanity_score` is the weighted composite `code_sanity_score = 0.4 * clean_code_found + 0.4 * over_engineering_caught + 0.2 * value_articulated`.

- **Clean code (8 items):** vague/short names; function > 50 lines or > 4 params; dead code / commented-out blocks / unused imports; magic numbers/strings without named constants; copy-paste duplication; bare `except` / swallowed errors / missing cleanup; type unsafety (`any`, missing types, wrong return types); stale or misleading comments.
- **Over-engineering (8 items):** interface with one implementer; speculative params/configs for hypothetical use; premature optimization without measurement; YAGNI features/flags for hypothetical futures; excessive layering (3+ layers for trivial logic); Factory/Strategy pattern for a single implementation; deep inheritance without polymorphism; 1-class-per-file without justification.
- **Value / meaning (4 items):** change has a stated purpose tied to a real user need; not noise/cosmetic/churn; scope matches the problem (no creep); the diff earns its lines.

Per sub-score is `(items_flagged / items_present_in_input) * 10` — a reviewer that misses even the obvious items in a planted fixture scores 0 on that sub-rubric.

### Inputs / outputs

- **Input:** a `--dim` filter (default: all 3) and an optional `--case <id>` filter.
- **Case discovery:** scans `eval/cases/{review,security,plan}/*.json` (12 seed cases).
- **Transcript replay:** reads `eval/transcripts/<dim>/<case_id>.json` for the recorded agent output; a missing transcript means the case is skipped (logged, not failed).
- **Per-dim judge prompt:** `eval/prompts/judge-<dim>.md` returns a JSON object with the dimension's axes.
- **Code-sanity rubric prompt:** `eval/prompts/judge-code-sanity.md` is the shared 20-checkbox rubric the `review` judge invokes for the `code_sanity_score` axis.
- **Output:** `.dev-kit/eval-report.md`, with a per-dim table of axis means + verdict counts.

### Opt-in flags (default OFF)

The session-log judge and golden-diff paths cost extra LLM calls and are never auto-invoked — they fire only when the user explicitly passes the flag (or `tools/session_monitor.py` emits a handshake pointer that another script wires up; the monitor itself never calls the judge).

| Flag | What it does | Output |
|---|---|---|
| `--session-log <path>` | Judge one session log on the 8-axis session rubric (`eval/prompts/judge-session.md`); 1 LLM call, cached by `session_id` | JSON summary to stdout; `--write-session-report` also writes `.dev-kit/session-eval-report.md` |
| `--golden-diff` | Diff the current `run_eval` result against `eval/golden/*.json` (schema 2.0.0 baselines) and emit regression markers per axis | JSON summary to stdout; `--write-regression-report` also writes `.dev-kit/regression-report.md` |

`--session-log` short-circuits the case-based path (the session, not a case, is the unit of judgment); `--golden-diff` only runs after a case-based `run_eval` completes.

### Failure modes

- Missing transcript for a case → the case is **skipped** (logged in the report), not failed — a setup gap, not a regression.
- Judge API error → the case is marked **ROT** with an `error` field; the loop continues.
- Malformed JSON from the LLM → `parse_scores_json` falls back to a regex extract; if still empty, score is 0 → ROT.
- Empty/unreadable session log under `--session-log` → report marked **ROT** with `error="empty or unreadable session log"`; no LLM call made.
- Missing `eval/golden/` under `--golden-diff` → an empty regression report (`summary.markers=0`); never errors.

## Usage

```bash
python lib/eval_runner.py --project-root . [--dry-run] [--dim review|security|plan] [--case <id>]
python lib/eval_runner.py --project-root . --session-log logs/cc/<sid>.jsonl [--write-session-report]
python lib/eval_runner.py --project-root . --golden-diff [--write-regression-report]
```

| Flag | Purpose |
|---|---|
| `--dry-run` | Skip LLM calls; mock each case at 7.0/DRIFT_WARNING (no API key required) |
| `--dim` | Restrict to one dimension (default: all 3) |
| `--case` | Restrict to a single `case_id` |
| `--session-log` | Opt-in: judge one session log on the 8-axis rubric (default: OFF) |
| `--golden-diff` | Opt-in: diff the run_eval result against `eval/golden/*.json` (default: OFF) |
| `--write-session-report` | Emit `.dev-kit/session-eval-report.md` from a `--session-log` run |
| `--write-regression-report` | Emit `.dev-kit/regression-report.md` from a `--golden-diff` run |

## Output

`.dev-kit/eval-report.md` — per-dimension table of axis means and verdict counts (OK / DRIFT_WARNING / ROT), plus, for opt-in runs, `.dev-kit/session-eval-report.md` and/or `.dev-kit/regression-report.md`.

## Rules

- DRIFT_WARNING → log and continue; do not auto-repair.
- ROT → log and continue; `/dev-kit:repair` may pick up the case if wired to the repair loop.
- Adding a case requires no code change: drop a JSON into `eval/cases/<dim>/<name>.json` plus a recorded transcript into `eval/transcripts/<dim>/<name>.json`.
- `--session-log` and `--golden-diff` are opt-in only: no CI wiring, no cron, no auto-trigger from `tools/session_monitor.py`.

## Hook integration (Stage Eval)

`slop-detector=ON`, `stop-verify=ON`, `tdd-guard=OFF` (no production code in this stage). Eval is read-only on disk — transcripts are pre-recorded, and the judge only writes the report.

## Related

- `/dev-kit:repair` — may invoke this skill to confirm a regression is still present after a fix attempt.
- [report](report.md) — reads `.dev-kit/eval-report.md` (this skill's output) and renders it as a self-contained HTML page.

---
*Source: [`skills/eval/SKILL.md`](../../skills/eval/SKILL.md)*
