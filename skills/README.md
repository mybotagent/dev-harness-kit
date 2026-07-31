# Skills index

This index lists every skill shipped by the `dev-kit` plugin. Click into any skill to read its full `SKILL.md`; every `SKILL.md` has a back-link at the top to return here.

**38 skills** across 13 categories (33 human-invocable, 5 model-invoked). The full path of each entry is `skills/<dir>/SKILL.md`. Use `find skills -mindepth 2 -maxdepth 2 -name SKILL.md | wc -l` to confirm.

## By category

### `audit` (10)

| Skill | α | Description |
|---|---|---|
| [`audit`](audit/SKILL.md) | `state` | 0-arg cross-cutting. Bulk slop + secret audit. READ-ONLY. |
| [`ci-doctor`](ci-doctor/SKILL.md) | `enforcement` | Read-only CI readiness audit. Prints one PASS/FAIL summary across files, marker, provider file, secrets, and gh auth. Hand-off answer to "would CI succeed on my next PR?" |
| [`ci-triage`](ci-triage/SKILL.md) | `enforcement` | Triage failing GitHub Actions runs across recent commits, dedupe against a persisted case store, judge new failures against a model/context/harness taxonomy with a required repro + regression test, and record them without re-analyzing repeats. |
| [`cost-gate`](cost-gate/SKILL.md) | `enforcement` | 0-arg cost-gate status. Prints current session spend, threshold distance, and a two-line git-trailer block to include in commits so the PR-level cost flag can aggregate. |
| [`docs-maintenance`](docs-maintenance/SKILL.md) | `analysis` | Audit repository documentation, remove superseded guidance, and refresh the README without recording volatile inventory facts. |
| [`hook-doctor`](hook-doctor/SKILL.md) 🔒 | `enforcement` | Diagnose failed Claude Code or Codex hooks, repair safe cache and registration drift, and report the exact restart step. |
| [`inspect`](inspect/SKILL.md) | `analysis` | 0-arg read-only code health audit. 8-dim fan-out (dead, dup, smell, overeng, overarch, cleancode, tokenbudget, slop) -> markdown report. |
| [`prune-propose`](prune-propose/SKILL.md) | `state` | 0-arg skill — usage telemetry dump + per-skill delete proposal. User approves each deletion explicitly. |
| [`report`](report/SKILL.md) | `analysis` | 0-arg HTML renderer for the latest eval + inspect markdown reports. One self-contained .dev-kit/report.html. No options, no JS, no external assets. |
| [`token-analyzer`](token-analyzer/SKILL.md) | `analysis` | 0-arg token-efficiency dashboard. Runs tools/token_efficiency_analyzer.py over logs/{claude-code,codex}/*.jsonl to produce an HTML report (+ lazy per-worktree transcript sidecars) -- 4-dim session scoring, 6 anti-patter… |

### `bootstrap` (3)

| Skill | α | Description |
|---|---|---|
| [`bootstrap`](bootstrap/SKILL.md) | `state` | 0-arg orchestrator. Writes minimal CLAUDE.md + AGENTS.md + active-hooks.json on a fresh repo. No noise files by default. |
| [`bootstrap-full`](bootstrap-full/SKILL.md) | `state` | One-shot setup for new projects. Runs /dev-kit:bootstrap + /dev-kit:ci-setup in a single call — writes CLAUDE.md + AGENTS.md + active-hooks.json, then installs the 15 CI templates + pre-push hook + marker. |
| [`ci-setup`](ci-setup/SKILL.md) | `enforcement` | Install dev-kit's reusable CI workflow templates into a target project. Idempotent via `.dev-kit/ci-config.json` presence, no version gate. Hand-off to /dev-kit:build. |

### `build` (8)

| Skill | α | Description |
|---|---|---|
| [`build`](build/SKILL.md) | `state` | 0-arg. Per-step sub-agent delegation + self-fix loop (MUST-36~38). Uses harness-runner engine. TDD + verify + debug integrated. |
| [`build-debug`](build-debug/SKILL.md) 🔒 | `enforcement` | 4-phase systematic debugging. No fix proposal before Phase 1 (reproduce) completes (MUST-L2). Root-cause-first Iron Law. |
| [`build-refactor`](build-refactor/SKILL.md) 🔒 | `enforcement` | 4-pass cleanup (dead → dup → naming → coverage). No cleanup without regression test (MUST-L1 + L4). |
| [`build-tdd`](build-tdd/SKILL.md) 🔒 | `enforcement` | Red-Green-Refactor cycle. Active when methodology=tdd (default). No production code without a failing test. tdd-guard hook enforces. |
| [`build-verify`](build-verify/SKILL.md) 🔒 | `enforcement` | verification-before-completion. No "done" without quoted exit code + test count + build log (MUST-L3, hook stop-verify). |
| [`feat-remove`](feat-remove/SKILL.md) | `state` | DEPRECATED. Use /dev-kit:prune --target <feature> instead. |
| [`prune`](prune/SKILL.md) | `analysis` | 0-arg slop-removal chain. One slash wraps inspect → 3-pass delete sweep → review. Gated phases for deleting AI slop and dead features (not refactoring). |
| [`refactor`](refactor/SKILL.md) | `analysis` | 0-arg cleanup chain. One slash wraps inspect -> build-refactor -> review. 3 gated phases with quoted exit codes between each. |

### `config` (1)

| Skill | α | Description |
|---|---|---|
| [`config`](config/SKILL.md) | `state` | skill + MCP + hook + methodology picker (multiSelect). |

### `design` (4)

| Skill | α | Description |
|---|---|---|
| [`interview`](interview/SKILL.md) | `enforcement` | 5-field safety-contract interview that gates plan emission. Drives `lib.interview_engine` through one Ralph loop, enforces `safety_valve=8`, `narrowed_delta`, `dedup_metric` (identical-ambiguity-cycle=2), and `user_inte… |
| [`proposal`](proposal/SKILL.md) | `state` | 0-arg HTML renderer for design proposals / plans. Renders any docs/proposals/<main>/<sub>.yaml to docs/proposals/<main>/<sub>.html for pre-implementation review. |
| [`research`](research/SKILL.md) | `enforcement` | 0-arg research gate. Run Phase 0-3 escalation (cache / direct / multi / human) + verify() + enforce_citations(). /dev-kit:research <claim> [--max-phase N]. |
| [`valuate`](valuate/SKILL.md) | `enforcement` | Plan-value gate. Scores a plan on 6 axes via LLM judge and returns proceed / revise / hold / kill. Verdict envelope persists to .dev-kit/valuations/<plan-id>.json. |

### `eval` (1)

| Skill | α | Description |
|---|---|---|
| [`evaluate`](evaluate/SKILL.md) | `enforcement` | 0-arg eval extension. Replays transcripts and judges against registered rubrics (harness-quality, os-quality, plus legacy review/security/plan). /dev-kit:evaluate [--harness-quality] [--os-quality] [--case <id>] [--dry-… |

### `plan` (1)

| Skill | α | Description |
|---|---|---|
| [`plan`](plan/SKILL.md) | `state` | 0-arg plan stage. Take 1-line idea → PRD.md + phases/<name>/{index.json, step<N>.md} in 5 gates. Quantified value (cost/LTV) + ambiguity loop (0-10) replace the old 5-question grill-me. |

### `repair` (1)

| Skill | α | Description |
|---|---|---|
| [`repair`](repair/SKILL.md) | `state` | 8-step Eval-Repair loop (golden → judge → root cause → fix → judge → A/B → diff → Human Review). Final step = single user approve. |

### `review` (1)

| Skill | α | Description |
|---|---|---|
| [`review`](review/SKILL.md) | `analysis` | Parallel multi-dimension code review with a false-positive filter. Fans out to per-dim experts (correctness, security, architecture) that run in parallel and return evidence-backed findings; a verifier pass confirms/rej… |

### `security` (1)

| Skill | α | Description |
|---|---|---|
| [`security`](security/SKILL.md) | `enforcement` | Full OWASP Top 10 2025 fan-out (A01–A10) with a verifier pass. Ten parallel subagents, one per category, return evidence-backed findings; a verification pass confirms or rejects each before a per-category breakdown tabl… |

### `ship` (3)

| Skill | α | Description |
|---|---|---|
| [`babysit-pr`](babysit-pr/SKILL.md) | `state` | 0-arg PR babysitter. Polls `gh pr checks`, fetches failing run logs, applies minimal fixes, commits + pushes, and re-iterates until review verdict = Approve and all required checks pass. Hard cap on iterations to preven… |
| [`bump`](bump/SKILL.md) | `state` | Explicit version bump of `.claude-plugin/plugin.json` + push of `chore/bump-vX.Y.Z`. Mirrors the auto-bump in `.github/workflows/version-bump.yml` but user-triggered for race recovery and pre-PR explicit bumps. |
| [`ship`](ship/SKILL.md) | `state` | 0-arg. Release tag emit. Gate check only (hooks auto). Requires Review verdict=Approve + main-block pass. |

### `shortcuts` (3)

| Skill | α | Description |
|---|---|---|
| [`codex-cache-update`](codex-cache-update/SKILL.md) | `analysis` | Refresh the dev-kit Codex marketplace checkout and synchronize the versioned plugin cache. Use when Codex reports the marketplace is current but the installed cache may be stale, or after a dev-kit merge. |
| [`llm-refresh`](llm-refresh/SKILL.md) | `analysis` | Refresh docs/llm-info/<provider>.json from each vendor's official pricing page via WebFetch extraction. Diff-then-commit; manual like set-provider.sh. |
| [`log`](log/SKILL.md) | `state` | Toggle /log setup|on|off|status — install/remove loghooks from ~/dev/loghooks into the current project's Claude/Codex settings. |

### `status` (1)

| Skill | α | Description |
|---|---|---|
| [`status`](status/SKILL.md) | `state` | HOTL visualization. Current loop progress + cumulative cycles + hand-off chain + eval score on one screen. |

## Alphabetical

| # | Skill | Category | α | Invocable |
|---|---|---|---|---|
| 1 | [`audit`](audit/SKILL.md) | `audit` | `state` | human |
| 2 | [`babysit-pr`](babysit-pr/SKILL.md) | `ship` | `state` | human |
| 3 | [`bootstrap`](bootstrap/SKILL.md) | `bootstrap` | `state` | human |
| 4 | [`bootstrap-full`](bootstrap-full/SKILL.md) | `bootstrap` | `state` | human |
| 5 | [`build`](build/SKILL.md) | `build` | `state` | human |
| 6 | [`build-debug`](build-debug/SKILL.md) | `build` | `enforcement` | model |
| 7 | [`build-refactor`](build-refactor/SKILL.md) | `build` | `enforcement` | model |
| 8 | [`build-tdd`](build-tdd/SKILL.md) | `build` | `enforcement` | model |
| 9 | [`build-verify`](build-verify/SKILL.md) | `build` | `enforcement` | model |
| 10 | [`bump`](bump/SKILL.md) | `ship` | `state` | human |
| 11 | [`ci-doctor`](ci-doctor/SKILL.md) | `audit` | `enforcement` | human |
| 12 | [`ci-setup`](ci-setup/SKILL.md) | `bootstrap` | `enforcement` | human |
| 13 | [`ci-triage`](ci-triage/SKILL.md) | `audit` | `enforcement` | human |
| 14 | [`codex-cache-update`](codex-cache-update/SKILL.md) | `shortcuts` | `analysis` | human |
| 15 | [`config`](config/SKILL.md) | `config` | `state` | human |
| 16 | [`cost-gate`](cost-gate/SKILL.md) | `audit` | `enforcement` | human |
| 17 | [`docs-maintenance`](docs-maintenance/SKILL.md) | `audit` | `analysis` | human |
| 18 | [`evaluate`](evaluate/SKILL.md) | `eval` | `enforcement` | human |
| 19 | [`feat-remove`](feat-remove/SKILL.md) | `build` | `state` | human |
| 20 | [`hook-doctor`](hook-doctor/SKILL.md) | `audit` | `enforcement` | model |
| 21 | [`inspect`](inspect/SKILL.md) | `audit` | `analysis` | human |
| 22 | [`interview`](interview/SKILL.md) | `design` | `enforcement` | human |
| 23 | [`llm-refresh`](llm-refresh/SKILL.md) | `shortcuts` | `analysis` | human |
| 24 | [`log`](log/SKILL.md) | `shortcuts` | `state` | human |
| 25 | [`plan`](plan/SKILL.md) | `plan` | `state` | human |
| 26 | [`proposal`](proposal/SKILL.md) | `design` | `state` | human |
| 27 | [`prune`](prune/SKILL.md) | `build` | `analysis` | human |
| 28 | [`prune-propose`](prune-propose/SKILL.md) | `audit` | `state` | human |
| 29 | [`refactor`](refactor/SKILL.md) | `build` | `analysis` | human |
| 30 | [`repair`](repair/SKILL.md) | `repair` | `state` | human |
| 31 | [`report`](report/SKILL.md) | `audit` | `analysis` | human |
| 32 | [`research`](research/SKILL.md) | `design` | `enforcement` | human |
| 33 | [`review`](review/SKILL.md) | `review` | `analysis` | human |
| 34 | [`security`](security/SKILL.md) | `security` | `enforcement` | human |
| 35 | [`ship`](ship/SKILL.md) | `ship` | `state` | human |
| 36 | [`status`](status/SKILL.md) | `status` | `state` | human |
| 37 | [`token-analyzer`](token-analyzer/SKILL.md) | `audit` | `analysis` | human |
| 38 | [`valuate`](valuate/SKILL.md) | `design` | `enforcement` | human |

