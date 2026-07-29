# STAGES — dev-harness-kit per-stage harness spec

> Reference: ADR-0011, ADR-0020. 7 stages (B / B.5 / 1 / 2 / 3 / 5a / 5b / 6 / 7) × must/must-not/AC unified.

## Stage B — Bootstrap (`/dev-kit:bootstrap`)

- **Goal**: First entry into a new project, 0 → 30 min productive. Minimal setup: exactly 3 files written to a fresh repo.
- **Must**: (a) sanity read-only audit (printed to stdout; `--persist-audit` writes `.dev-kit/sanity-report.md`) (b) codebase-map lazy-loading index in CLAUDE.md §3 (c) active-hooks.json SSOT init (d) CLAUDE.md §1~§5 unified record (e) AGENTS.md shared-instruction index for Codex and other CLIs (f) `--full-claude-md` opt-in writes `docs/CODEBASE-MAP.md`
- **Must-Not**: modify files (sanity read-only). Modify lockfiles. Speculation. Persist hand-off file (CLAUDE.md §5 pointer is enough).
- **AC**: On fresh repo: CLAUDE.md + AGENTS.md + `.dev-kit/.active-hooks.json` exist. CLAUDE.md §3 = lazy-loading index referencing canonical source files. `.dev-kit/` directory auto-created.
- **Active Skills**: `bootstrap` (sanity + codebase-map + hook-matrix are inlined sub-stages), `write_project_md`
- **Active Hooks**: `secret-scan`=read-only. Others OFF.
- **Hand-off out**: §5 hand-off pointer in CLAUDE.md (no separate `.dev-kit/hand-off/` file from bootstrap)

## Stage B.5 — CI Setup (`/dev-kit:ci-setup`)

- **Goal**: Replicate dev-kit's CI shape (workflows + pre-push hook + local runner) into the target repo. One-command CI parity.
- **Must**: (a) Idempotent install via `.dev-kit/ci-config.json` marker. (b) Mirror of `.githooks/pre-push` + 3 GitHub Actions workflows. (c) `validate.py` extracted from dev-kit's own `ci.yml` 5-step validate job. (d) `--force` flag for refresh; otherwise refuse overwrite.
- **Must-Not**: Modify dev-kit's own repo. Drop the marker. Delete user-created files in target.
- **AC**: All 15 expected files exist post-install (3 workflows + 4 scripts + 5 worktree-rule files + pre-push + .claude/rules/git-workflow.md + tests). `python3 scripts/validate.py` exits 0. `.dev-kit/ci-config.json` has correct schema.
- **Active Skills**: `ci-setup` (0-arg orchestrator; hidden `--force`, `--target DIR`)
- **Active Hooks**: same as Bootstrap (`secret-scan`=read-only)
- **Hand-off out**: gates `build` via marker file

## Stage 1 — Plan+Design (`/dev-kit:plan`)

- **Goal**: idea → PRD.md + `phases/<name>/{index.json, step<N>.md}`
- **Must**: 5 gates (frame → validate → non-goals → decompose → emit) in **one Ralph loop, safety_valve=8** (MUST-15). The `validate` gate fuses the old evidence / diff-profit / socratic gates into one composite convergence test: `evidence_count >= 3` AND `value_score = LTV × reachable_users / cost >= 3.0` AND `ambiguity_score <= 3`. Phase index.json written via `lib/execute.py:register_step()` so every step carries an explicit `status` (`unimplemented` → `pending` → `in_progress` → `completed`, plus `error` / `blocked` for runtime).
- **Must-Not**: Write code, build, or deploy. Write artifacts other than PRD.md + phases/ + .dev-kit/hand-off/. Set runtime-only statuses (`in_progress`, `completed`, `error`, `blocked`) — those belong to harness-runner. Run the old 5-question grill-me (replaced by the ambiguity loop).
- **AC**: PRD.md 6-section DoD pass. `phases/<name>/step<N>.md` 4 fields (must-read / instruction / AC / Don't). `phases/<name>/index.json` schema valid. `value_score >= 3.0` AND `ambiguity_score <= 3` OR `loop-log.json` shows `status: held` + user acknowledgement. `loop-log.json` narrowing appended per cycle.
- **Active Skills**: `plan` (self-contained)
- **Active Hooks**: `stop-verify`=ON. `slop-detector`=OFF (planning doc allowed). Others OFF.
- **Hand-off out**: `plan→build.md`

## Stage 2 — Valuate (`/dev-kit:valuate`)

- **Goal**: Decide whether the plan from Stage 1 is worth building. Returns one of `proceed` / `revise` / `hold` / `kill`. Persists the verdict to `lcs://valuations/<plan-id>` (file: `.dev-kit/valuations/<plan-id>.json`).
- **Must**: (a) Score 6 rubric axes (problem_fit / roi_estimate / existing_solution_edge / team_capability / risk_vs_reward / measurability) via `lib/llm_judge.py:call_judge(axes=DIM_AXES["plan_value"])`. (b) Run `lib/valuation_engine.py:decide(plan, rubric_scores)` to produce the verdict. (c) Honor the absolute risk-floor rule: any axis < 2.0 → `kill`, regardless of all other axes. (d) Persist the verdict envelope (`decision` / `rationale` / `blocking_findings`) to `lcs://valuations/<plan-id>`.
- **Must-Not**: Allow the LLM to emit the verdict directly. The engine is the only authority — the judge returns scores, not decisions. Emit `kill` / `hold` / `revise` when the gate would; the build stage depends on this.
- **AC**: `.dev-kit/valuations/<plan-id>.json` exists with the canonical envelope. `lcs://valuations/<plan-id>` returns `{decision, rationale, blocking_findings}`. `python3 -m lib.valuation_engine --plan PRD.md --dry-run` exits 0 with a valid envelope.
- **Active Skills**: `valuate` (`alpha: enforcement` — the no-go gate is deterministic)
- **Active Hooks**: `stop-verify`=ON. Others OFF.
- **Hand-off out**: `lcs://valuations/<plan-id>` (the build stage reads this URI as its pre-flight valuation gate).

## Stage 3 — Build (`/dev-kit:build`)

- **Goal**: Per-step code completion per `phases/<name>/step<N>.md` + regression GREEN.
- **Must**: (a) Read `lcs://valuations/<plan-id>` before launching the first step; refuse with exit 2 if the verdict is not `proceed` (unless `--skip-valuation` is passed). (b) Follow `phases/<name>/step<N>.md` exactly. (c) Run AC commands and quote output. (d) Bug → reproduce → root-cause → regression test → minimal fix (4-phase debug via `build-debug`). (e) 2-commit protocol (feat + chore).
- **Must-Not**: Speculate on AC ("should work", "probably fine"). Delete `output.json`. Batch multiple changes.
- **AC**: All steps `status=completed`. `pytest` exit code 0 + count quoted. 2-commit protocol followed.
- **Active Skills**: `build-tdd`, `build-debug`, `build-verify`, `build-refactor` (the per-step harness runner + methodology selector live in `lib/execute.py` + `lib/methodology/`; prune's 3-pass sweep is inlined into `prune`), `valuate` (pre-flight no-go gate reads `lcs://valuations/<plan-id>` and refuses non-PROCEED; `--skip-valuation` flag is the permanent backward-compat escape hatch)
- **Active Hooks**: `tdd-guard`, `bash-guard`, `secret-scan`, `slop-detector`, `stop-verify` — all ON
- **Sub-agent**: Phase 3 (planned). Currently sequential-only.
- **Hand-off out**: `build→review.md`

## Stage 5a — Review (`/dev-kit:review`)

- **Goal**: Find correctness + security + architecture defects in the diff + PR-style verdict.
- **Must**: Every finding has `failure_scenario` + `confidence`. **Single-message 3-dim fan-out**. Separate verifier pass.
- **Must-Not**: Skip verifier pass. Report unverified critical.
- **AC**: PR summary `**Verdict:**` + sorted inline findings. Per-severity count.
- **Active Skills**: `review`
- **Active Hooks**: `slop-detector`, `secret-scan`, `stop-verify` = ON. Review/security verdict gates run via `.github/workflows/review.yml` (CI).
- **Hand-off out**: `review→ship.md`

## Stage 5b — Security (`/dev-kit:security`)

- **Goal**: OWASP Top 10 2025 (A01~A10) audit.
- **Must**: Per-category breakdown table. Single-message 10-dim fan-out. Verifier CONFIRMED ≥ 5.
- **Must-Not**: Skip A0X IDs. Unverified critical.
- **AC**: Per-category table. Per-severity verdict.
- **Active Skills**: `security`
- **Active Hooks**: Same as Review.
- **Hand-off out**: `security→ship.md` (independent of Review)

## Stage 6 — Ship (`/dev-kit:ship`)

- **Goal**: Issue release-ready tag.
- **Must**: Review verdict=Approve + Verify AC passed + Pre-push main-block passed.
- **Must-Not**: Direct push to main. `--no-verify` abuse.
- **AC**: git tag + CHANGELOG entry + pre-release smoke.
- **Active Skills**: (none, manual gate only)
- **Active Hooks**: `stop-verify`=ON.

## Stage 7 — Maintenance Gate (`.github/workflows/maintenance.yml`)

- **Goal**: PR-only enforcement of clean-code + over-engineering + value.
  Companion to the pre-push intent check in `.githooks/pre-push`.
  Runs on every PR (excluding bump-PRs).
- **Must**: (a) `maintenance_judge` job invokes `/dev-kit:maintenance
  --diff <PR>` via `claude-code-action`; the judge prompt at
  `eval/prompts/judge-maintenance.md` applies the canonical
  20-checkbox rubric (CC-1..8 + OE-1..8 + VM-1..4) and emits three
  composite 0-10 axes (`code_sanity_score`, `docs_coverage_score`,
  `scope_discipline_score`). (b) `gate` job extracts the verdict via
  `lib/maintenance_gate.py:extract_verdict` (mirrors review.yml's
  pattern). (c) `gate` runs the docs-updated sub-gate
  (`lib/maintenance_gate.py:docs_updated_ok`) as its final step. (d)
  Combined verdict derivation: `code_sanity_score < 5` → Blocked;
  `5..7.99` → Changes Requested; `≥ 8` → Approve; an Approve with
  docs-updated failure downgrades to Changes Requested. (e) Bump-PR
  skip mirrors review.yml's filter (`startsWith(title, 'chore(release): bump dev-kit to v')`).
- **Must-Not**: Auto-approve the PR. Bypass `--no-verify` equivalent
  (none exists; the gate never auto-approves). Use the dedicated
  maintenance workflow for non-PR surface.
- **AC**: Workflow exists at `.github/workflows/maintenance.yml`.
  `python3 -m lib.maintenance_gate --extract-verdict-from-stdin`
  exits 0 and prints `Approve|Changes Requested|Blocked|""`.
  `tests/test_maintenance_gate.py` is GREEN (≥ 19 tests covering
  verdict extraction, docs-updated check, combine_verdict, CLI
  subprocess). Eval golden cases
  `eval/golden/maintenance-{01,02,03}*.json` exist and resolve to
  their expected verdict bands. `lib/llm_judge.py:DIM_AXES["maintenance"]`
  is registered with the 3 axes. `docs/quality/maintenance-gate.md` documents
  thresholds + bypass policy.
- **Active Skills**: `maintenance` (agent-skill companion to the
  workflow, opt-in invocation pattern)
- **Active Hooks**: (no in-process hooks — pure CI gate)
- **Hand-off out**: (terminal — the gate is the final pre-merge
  signal alongside review/security)

## Cross-cutting — Audit (`/dev-kit:audit`)

- **Goal**: Batch audit of slop + secrets.
- **Must**: Output HIGH/MEDIUM/LOW buckets. Banned-phrase regex SSOT.
- **Must-Not**: Modify files (read-only).
- **AC**: HIGH ≥ 5 = warning. 0 findings = clean.
- **Active Skills**: `audit` (slop + secret + outdated are inlined modes)

## Cross-cutting — Inspect (`/dev-kit:inspect`)

- **Goal**: Whole-codebase (not per-PR, not per-diff) health audit
  across 6 dimensions in parallel: `dead`, `dup`, `smell`, `overeng`,
  `cleancode`, `slop`. Produces one markdown report at
  `.dev-kit/inspect-report.md`.
- **Must**: Single-message 6-dim fan-out. Verifier pass on survivors.
  HIGH/MED/LOW bucketing in the report. `failure_scenario` required per
  finding.
- **Must-Not**: Modify source files (read-only invariant). Post PR
  comments. Edit the report from outside the skill.
- **AC**: Report exists at `.dev-kit/inspect-report.md`. Verdict is one
  of `Critical | Major drift | Minor drift | Healthy`. Per-dimension
  summary table present.
- **Active Skills**: `inspect`

## Cross-cutting — Report (`/dev-kit:report`)

- **Goal**: Render the latest `eval-report.md` + `inspect-report.md` as
  one self-contained HTML file at `.dev-kit/report.html`. Distinct
  human action ("view the report in a browser") with a distinct
  artifact; not an option on `/dev-kit:eval` or `/dev-kit:inspect`.
- **Must**: Self-contained HTML (no `<script>`, no external CSS/IMG,
  inline styles only). Dark-mode aware. Defensive HTML escaping on
  every interpolated value.
- **Must-Not**: Read source files (only the two report artifacts). Make
  network calls.
- **AC**: `.dev-kit/report.html` exists. Either contains both report
  sections (when both source artifacts are present) or a "not found"
  banner (when one or both are missing). Open in a browser with no
  console errors.
- **Active Skills**: `report`

## Cross-cutting — Eval (`/dev-kit:eval`)

- **Goal**: Asset freshness eval (CLAUDE.md / skill / hook / Iron Law).
- **Must**: 4-axis score (semantic_drift / completeness / correctness / consistency). 2-judge cross-check.
- **AC**: ≥ 8 OK. < 5 ROT → CI fail.
- **Active Skills**: `eval` (3 dims: review, security, plan; cross-cutting agent-behavior rubrics)

## Cross-cutting — Repair (`/dev-kit:repair`)

- **Goal**: Eval-Repair 8-step loop. Last step = user 1× approve.
- **Must**: 7 steps auto. Step 8 Human Review is the only sync STOP.
- **Must-Not**: Auto commit diff. Change review / design / build state itself.
- **AC**: Human `approve|reject|defer` is the only commit.
- **Active Skills**: 9 Specialized Fixers (one per category).
