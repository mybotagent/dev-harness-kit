# ADR-0022: Refactor `/dev-kit:eval` from asset freshness to agent behavior

**Status:** Accepted (2026-07-09)
**Supersedes:** the implicit "eval = asset freshness" model in
`lib/eval_runner.py` v1.0.0 (25 golden files at `eval/golden/00..24`).

## Context

The previous eval scored **static doc freshness** along four axes
(semantic_drift / completeness / correctness / consistency) over the
repo's CLAUDE.md, skills, hooks, iron laws, and methodology files. It
caught doc rot and skill prompt drift, but it did not measure the thing
we actually care about: **does the agent produce the right output for
the right input when running the dev-kit skills?**

Three forces pushed the change:

1. **Reviews were inconsistent.** Two runs of `/dev-kit:review` on the
   same diff sometimes surfaced different findings, and the verifier
   pass on a real SQL-injection fixture was an after-the-fact
   eyeball-check (the `expected.md` table at
   `skills/review/fixtures/expected.md` is a human-grader reference, not
   a CI gate). We needed a behavior-based signal.
2. **Security classification was unjudged.** `/dev-kit:security` fans
   out 10 OWASP A01-A10 subagents; whether the result actually placed a
   planted vuln in the right A-category was never measured.
3. **Plan decompositions varied.** `/dev-kit:plan` emits 3-7 step
   decompositions; ambiguity score, step atomicity, AC executability,
   dependency ordering were never graded.

Plus a fourth, surfaced by the user mid-design: **the reviewer should
also catch clean-code violations, over-engineering, and churn**. A code
change that does not produce user value should be visibly distinguished
from one that does.

## Decision

`/dev-kit:eval` is now an **agent-behavior eval** over three dimensions
plus a 20-checkbox code-sanity rubric. The unit of eval shifts from
"file on disk" to **"case fixture + recorded agent transcript ->
per-dim rubric judgment"**.

### Three dimensions, three rubrics

| Dim | Axes (0-10) | What it measures |
|---|---|---|
| `review` | `verdict_consistency` `severity_calibration` `precision` `recall` `code_sanity_score` | review verdict + findings quality + clean-code / over-eng / value |
| `security` | `owasp_classification_accuracy` `severity_accuracy` `precision` | A01-A10 mapping + severity + false-positive rate |
| `plan` | `spec_clarity` `step_atomicity` `ac_executability` `dependency_ordering` | ambiguity per step, single-deliverable steps, runnable AC, buildable order |

Per-case axis mean drives the verdict:
- `>= 8.0` -> OK
- `5.0-7.9` -> DRIFT_WARNING
- `< 5.0` -> ROT
- missing transcript -> SKIPPED (a setup gap, not a regression)

### Code-sanity rubric (20 items)

The review judge's `code_sanity_score` axis is a composite:

```
code_sanity_score = 0.4 * clean_code_found
                  + 0.4 * over_engineering_caught
                  + 0.2 * value_articulated
```

20 checkboxes split 8 / 8 / 4 (see `eval/prompts/judge-code-sanity.md`):

- **Clean code (CC-1..8):** vague names, function > 50 lines or > 4
  params, dead code, magic numbers, copy-paste duplication, bare
  except / swallowed errors, type unsafety, stale comments.
- **Over-engineering (OE-1..8):** interface with one implementer,
  speculative params, premature optimization, YAGNI features,
  excessive layering, factory/Strategy for one impl, deep inheritance,
  1-class-per-file without justification.
- **Value / meaning (VM-1..4):** stated purpose tied to user need, not
  noise/cosmetic/churn, scope matches the problem, diff earns its lines.

### Architecture

```
eval/cases/<dim>/<name>.json     ← input + expected behavior
eval/transcripts/<dim>/<name>.json  ← recorded agent output (replay)
eval/prompts/judge-<dim>.md     ← per-dim LLM-as-judge rubric
eval/prompts/judge-code-sanity.md  ← shared 20-checkbox rubric
lib/eval_runner.py              ← discover_cases → replay → judge → report
lib/llm_judge.py                ← keep JUDGE_AXES; add DIM_AXES
```

The runner is **replay-only** in v1: it loads a recorded agent
transcript from `eval/transcripts/<dim>/<case_id>.json` and judges it
against the case fixture. Live re-run is a v2 follow-up (env-flagged
in `run_eval(--live)`); until then a case without a transcript is
`SKIPPED`, not failed.

### Files

- `lib/eval_runner.py` — `discover_assets` replaced with
  `discover_cases`; new `judge_case`, `load_transcript`,
  `save_transcript`; per-dim dispatch.
- `lib/llm_judge.py` — kept `JUDGE_AXES` and `parse_scores_json` for
  backward-compat; added `DIM_AXES` dict + dim-aware `parse_scores_json(raw, axes=...)`.
- `eval/prompts/judge-{review,security,plan}.md` — 3 new per-dim
  prompts, each with the prompt-engineering pattern from v1.0.0
  (fenced JSON output, "ONLY a JSON object" instruction, axis bullet
  per line).
- `eval/prompts/judge-code-sanity.md` — shared 20-checkbox rubric the
  review judge embeds.
- `eval/cases/{review,security,plan}/*.json` — 12 seed cases.
- `eval/transcripts/<dim>/*.json` — 12 recorded transcripts.
- `eval/golden/<dim>-<name>-<hash>.json` — 12 new schema-2.0.0
  baselines (replacing 25 old asset-freshness baselines).

### Skill count unchanged

`tests/test_smoke.py:21` pins `SKILL_COUNT = 29` and CI pins the same
in `.github/workflows/ci.yml:89`. The new eval replaces the body of
`skills/eval/SKILL.md` (same name, same `category: eval`, same
`user-invocable: true`); no new skill added. `test_naming.py` and the
CI `Validate skill count + flat layout` step pass unchanged.

## Alternatives considered

- **(a) New `skills/eval-behavior/SKILL.md` + new runner.** Clean
  separation but requires bumping `SKILL_COUNT` from 29 to 30 in 3
  places (`tests/test_smoke.py`, `.claude/rules/skill-authoring.md`,
  `.github/workflows/ci.yml`). Rejected to keep the change surface
  small.
- **(b) Live re-run only (no transcripts).** Highest signal but
  non-deterministic; CI becomes flaky; no way to grade an offline
  review. Replay-with-transcripts gives a stable CI signal; live
  re-run is a v2 flag.
- **(c) Keep asset-freshness eval as a separate sub-skill.** Rejected:
  the user asked to "reconfigure", not extend. Two evals would split
  attention and bury the new behavior signal.

## Consequences

- The eval is now **replay-only**; a new case requires recording a
  transcript before the case is gradeable. Mitigated by treating
  missing transcripts as `SKIPPED` (not failure).
- The judge prompt for the review dim **embeds the 20-checkbox
  rubric** on every call, which is more tokens per case. Mitigated by
  factoring the rubric into a shared prompt file
  (`judge-code-sanity.md`) and embedding via `${RUBRIC}` substitution.
- The four legacy asset-freshness axes (semantic_drift etc.) are
  retained in `JUDGE_AXES` for backward-compat with
  `tests/test_llm_judge.py` and any external callers, but no longer
  used by the eval runner.
- The Eval-Repair loop in `skills/repair/SKILL.md` step 2 still names
  the 4-axis judge; that is now misleading. A follow-up PR will update
  the repair skill to point at the per-dim rubric.

## References

- `lib/eval_runner.py:1-300` — new case-based runner
- `lib/llm_judge.py:1-200` — added `DIM_AXES`; kept `JUDGE_AXES`
- `eval/prompts/judge-{review,security,plan,code-sanity}.md` — new
  rubric prompts
- `eval/cases/{review,security,plan}/*.json` — 12 seed cases
- `eval/transcripts/{review,security,plan}/*.json` — 12 recorded
  transcripts
- `tests/test_eval_runner.py` — rewritten for schema 2.0.0
- `tests/test_eval_hygiene.py` — rewritten for 12-case / 4-prompt
  / 20-checkbox checks
- `tests/test_llm_judge.py` — added 8 tests in `TestDimAxes`
- `skills/review/SKILL.md:81-94` — review output contract the new
  eval judges
- `skills/security/SKILL.md:25-63` — security output contract
- `skills/plan/SKILL.md:184-280` — plan output contract (phase JSON +
  step template)
- `docs/adr/ADR-0021-eval-repair-loop.md` — the repair loop the new
  eval plugs into
