# Refactor — Phase 1: dead-code removal (2026-08-04)

Closes Phase 1 of `docs/proposals/harness-refactor/01-priorities.html`
(proposal lives on branch `inspect/2026-08-04-refactor-proposal`).

## What changed

- `lib/analysis_core/dimensions.py` — 19× tuple-literal duplication
  hoisted to 4 module constants (`_STANDARD_CONTRACT_FIELDS`,
  `_REVIEW_CONTRACT_FIELDS`, `_ALL_SEVERITIES`,
  `_MAJOR_PLUS_SEVERITIES`). All 22 `Dimension` constructors reference
  them by name. (cleancode-20)
- `lib/eval_runner.py` — deleted the ~110-line dup of `RubricRegistry`
  + `CaseResult` + 4 mock/exception helpers. Now imports the SSOT from
  `lib.eval._rubric` (extracted in PR-E). (dup-1, -2, -3)
- `lib/valuation_engine.py` — deleted the dead `pass`-only branch
  (cleancode-7) that advertised envelope persistence the CLI never
  implemented. Kept the `plan=` parameter (docs/stages/STAGES.md
  contract) with `del plan` + docstring note. (cleancode-6 partial)
- `.env.example` — `DEEPSEEK_API_KEY` moved to a "CI-only secret"
  comment block with a pointer to `review.yml:176` where
  `secrets.DEEPSEEK_API_KEY` is mapped onto `ANTHROPIC_API_KEY`. The
  original listing was misleading — read by GitHub Actions secrets,
  not by any local Python code.

## Deviations from the proposal

1. **`lib/interview_engine.py` was NOT deleted** — false positive in
   the inspect finding. `tests/test_interview_engine.py:22` does
   `import interview_engine as ie` (module import, not name imports)
   so the AST dead-export scanner missed it.
   `tools/harness_audit.py:205` actively flags
   `missing lib/interview_engine.py`. The `interview` skill is the
   documented consumer.
2. **`valuation_engine.py:decide()` kept the `plan=` parameter** —
   `docs/stages/STAGES.md:40` specifies `decide(plan, rubric_scores)`
   as the production API. Used `del plan` + docstring note.
3. **`.env.example` kept `DEEPSEEK_API_KEY` as a CI-only comment** —
   `.github/workflows/review.yml:176` reads `secrets.DEEPSEEK_API_KEY`.

## Verified

- 140/140 affected tests pass (test_eval_runner, test_evaluation_rubrics,
  test_valuation_engine, test_analysis_core_runner).
- Full suite: 667/668. The 1 failure is pre-existing and unrelated
  (a branch-naming convention check tripped on a leftover
  `agent/...` branch from a prior session).
- Ruff clean on all 4 files.

## Closed

- `dup-critical`: dup-1, dup-2, dup-3 (all eval_runner.py)
- `cleancode`: 6 (partial — kept `plan=` for API compat),
  7 (pass branch removed), 20 (tuple hoist)

## Next

- **Phase 2a**: `DashboardContext` + 4 sibling dataclasses
  (closes the 2 double-smell sites in `tools/te_analyzer/view_model.py:662`
  and `tools/token_efficiency_analyzer.py:2058`).
- **Phase 2b**: replace the 223-line hand-rolled YAML parser in
  `lib/ci_doctor.py:244 _parse_workflow_yaml` with `yaml.safe_load`.
- **Phase 3**: fail-closed verification hooks + per-iteration hand-off
  record.
