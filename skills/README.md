# Skills index

This index lists every skill shipped by the `dev-kit` plugin. Click into any skill to read its full `SKILL.md`; every `SKILL.md` has a back-link at the top to return here.

**33 skills** across 13 categories. The full path of each entry is `skills/<dir>/SKILL.md`.

## By category

### `audit` (8)

| Skill | α | Description |
|---|---|---|
| [`audit`](audit/SKILL.md) | `state` | 0-arg cross-cutting. Bulk slop + secret audit. READ-ONLY. |
| [`ci-doctor`](ci-doctor/SKILL.md) | `enforcement` | Read-only CI readiness audit. Prints one PASS/FAIL summary across files, marker, provider file, secrets, and gh auth. Hand-off answer to "would CI succeed on my next PR?" |
| [`cost-gate`](cost-gate/SKILL.md) | `enforcement` | 0-arg cost-gate status. Prints current session spend, threshold distance, and a two-line git-trailer block to include in commits so the PR-level cost flag can aggregate. |
| [`docs-maintenance`](docs-maintenance/SKILL.md) | `analysis` | Audit repository documentation, remove superseded guidance, and refresh the README without recording volatile inventory facts. |
| [`inspect`](inspect/SKILL.md) | `analysis` | 0-arg read-only code health audit. 8-dim fan-out (dead, dup, smell, overeng, overarch, cleancode, tokenbudget, slop) -> markdown report. |
| [`prune-propose`](prune-propose/SKILL.md) | `state` | 0-arg skill — usage telemetry dump + per-skill delete proposal. User approves each deletion explicitly. |
| [`report`](report/SKILL.md) | `analysis` | 0-arg HTML renderer for the latest eval + inspect markdown reports. One self-contained .dev-kit/report.html. No options, no JS, no external assets. |
| [`token-analyzer`](token-analyzer/SKILL.md) | `analysis` | 0-arg token-efficiency dashboard. Runs tools/token_efficiency_analyzer.py over logs/{claude-code,codex}/*.jsonl to produce an HTML report (+ lazy per-worktree transcript sidecars) -- 4-dim session scoring, 6 anti-pattern warnings, USD savings estimate. |

### `ship` (3)

| Skill | α | Description |
|---|---|---|
| [`babysit-pr`](babysit-pr/SKILL.md) | `state` | 0-arg PR babysitter. Polls `gh pr checks`, fetches failing run logs, applies minimal fixes, commits + pushes, and re-iterates until review verdict = Approve and all required checks pass. Hard cap on iterations to prevent infinite loops. |
| [`bump`](bump/SKILL.md) | `state` | Explicit version bump of `.claude-plugin/plugin.json` + push of `chore/bump-vX.Y.Z`. Mirrors the auto-bump in `.github/workflows/version-bump.yml` but user-triggered for race recovery and pre-PR explicit bumps. |
| [`ship`](ship/SKILL.md) | `state` | 0-arg. Release tag emit. Gate check only (hooks auto). Requires Review verdict=Approve + main-block pass. |

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
| [`build-debug`](build-debug/SKILL.md) | `enforcement` | 4-phase systematic debugging. No fix proposal before Phase 1 (reproduce) completes (MUST-L2). Root-cause-first Iron Law. |
| [`build-refactor`](build-refactor/SKILL.md) | `enforcement` | 4-pass cleanup (dead → dup → naming → coverage). No cleanup without regression test (MUST-L1 + L4). |
| [`build-tdd`](build-tdd/SKILL.md) | `enforcement` | Red-Green-Refactor cycle. Active when methodology=tdd (default). No production code without a failing test. tdd-guard hook enforces. |
| [`build-verify`](build-verify/SKILL.md) | `enforcement` | verification-before-completion. No "done" without quoted exit code + test count + build log (MUST-L3, hook stop-verify). |
| [`feat-remove`](feat-remove/SKILL.md) | `state` | Safely remove a feature. Sweeps the call graph, flags dependents, produces a deletion report, and verifies the full suite stays green after deletion. |
| [`prune`](prune/SKILL.md) | `analysis` | 0-arg slop-removal chain. One slash wraps inspect → 3-pass delete sweep → review. Gated phases for deleting AI slop and dead features (not refactoring). |
| [`refactor`](refactor/SKILL.md) | `analysis` | 0-arg cleanup chain. One slash wraps inspect -> build-refactor -> review. 3 gated phases with quoted exit codes between each. |

### `shortcuts` (3)

| Skill | α | Description |
|---|---|---|
| [`codex-cache-update`](codex-cache-update/SKILL.md) | `analysis` | Refresh the dev-kit Codex marketplace checkout and synchronize the versioned plugin cache. Use when Codex reports the marketplace is current but the installed cache may be stale, or after a dev-kit merge. |
| [`llm-refresh`](llm-refresh/SKILL.md) | `analysis` | Refresh docs/llm-info/<provider>.json from each vendor's official pricing page. Diff-then-commit; manual like set-provider.sh. |
| [`log`](log/SKILL.md) | `state` | Toggle /log setup|on|off|status — install/remove loghooks from ~/dev/loghooks into the current project's Claude/Codex settings. |

### `config` (1)

| Skill | α | Description |
|---|---|---|
| [`config`](config/SKILL.md) | `state` | skill + MCP + hook + methodology picker (multiSelect). |

### `eval` (1)

| Skill | α | Description |
|---|---|---|
| [`eval`](eval/SKILL.md) | `analysis` | Agent-behavior eval across 3 dimensions (review / security / plan) with a 20-checkbox code-sanity rubric. Replays recorded transcripts and judges against per-dim rubrics. /dev-kit:eval [--dim review|security|plan] [--case <id>] [--dry-run]. |

### `plan` (1)

| Skill | α | Description |
|---|---|---|
| [`plan`](plan/SKILL.md) | `state` | 0-arg plan stage. Take 1-line idea → PRD.md + phases/<name>/{index.json, step<N>.md} in 5 gates. Quantified value (cost/LTV) + ambiguity loop (0-10) replace the old 5-question grill-me. |

### `design` (1)

| Skill | α | Description |
|---|---|---|
| [`proposal`](proposal/SKILL.md) | `state` | 0-arg HTML renderer for design proposals / plans. Renders any docs/proposals/<main>/<sub>.yaml to docs/proposals/<main>/<sub>.html for pre-implementation review. |

### `repair` (1)

| Skill | α | Description |
|---|---|---|
| [`repair`](repair/SKILL.md) | `state` | 8-step Eval-Repair loop (golden → judge → root cause → fix → judge → A/B → diff → Human Review). Final step = single user approve. |

### `review` (1)

| Skill | α | Description |
|---|---|---|
| [`review`](review/SKILL.md) | `analysis` | "Parallel multi-dimension code review with a false-positive filter. Fans out to per-dim experts (correctness, security, architecture) that run in parallel and return evidence-backed findings; a verifier pass confirms/rejects each candidate before rendering per-line inline comments plus a PR-style summary with a verdict." |

### `security` (1)

| Skill | α | Description |
|---|---|---|
| [`security`](security/SKILL.md) | `enforcement` | Full OWASP Top 10 2025 fan-out (A01–A10) with a verifier pass. Ten parallel subagents, one per category, return evidence-backed findings; a verification pass confirms or rejects each before a per-category breakdown table + verdict. |

### `status` (1)

| Skill | α | Description |
|---|---|---|
| [`status`](status/SKILL.md) | `state` | HOTL visualization. Current loop progress + cumulative cycles + hand-off chain + eval score on one screen. |

## Alphabetical

| # | Skill | Category | α |
|---|---|---|---|
| 1 | [`audit`](audit/SKILL.md) | `audit` | `state` |
| 2 | [`babysit-pr`](babysit-pr/SKILL.md) | `ship` | `state` |
| 3 | [`bootstrap`](bootstrap/SKILL.md) | `bootstrap` | `state` |
| 4 | [`bootstrap-full`](bootstrap-full/SKILL.md) | `bootstrap` | `state` |
| 5 | [`build`](build/SKILL.md) | `build` | `state` |
| 6 | [`build-debug`](build-debug/SKILL.md) | `build` | `enforcement` |
| 7 | [`build-refactor`](build-refactor/SKILL.md) | `build` | `enforcement` |
| 8 | [`build-tdd`](build-tdd/SKILL.md) | `build` | `enforcement` |
| 9 | [`build-verify`](build-verify/SKILL.md) | `build` | `enforcement` |
| 10 | [`bump`](bump/SKILL.md) | `ship` | `state` |
| 11 | [`ci-doctor`](ci-doctor/SKILL.md) | `audit` | `enforcement` |
| 12 | [`ci-setup`](ci-setup/SKILL.md) | `bootstrap` | `enforcement` |
| 13 | [`codex-cache-update`](codex-cache-update/SKILL.md) | `shortcuts` | `analysis` |
| 14 | [`config`](config/SKILL.md) | `config` | `state` |
| 15 | [`cost-gate`](cost-gate/SKILL.md) | `audit` | `enforcement` |
| 16 | [`docs-maintenance`](docs-maintenance/SKILL.md) | `audit` | `analysis` |
| 17 | [`eval`](eval/SKILL.md) | `eval` | `analysis` |
| 18 | [`feat-remove`](feat-remove/SKILL.md) | `build` | `state` |
| 19 | [`inspect`](inspect/SKILL.md) | `audit` | `analysis` |
| 20 | [`llm-refresh`](llm-refresh/SKILL.md) | `shortcuts` | `analysis` |
| 21 | [`log`](log/SKILL.md) | `shortcuts` | `state` |
| 22 | [`plan`](plan/SKILL.md) | `plan` | `state` |
| 23 | [`proposal`](proposal/SKILL.md) | `design` | `state` |
| 24 | [`prune`](prune/SKILL.md) | `build` | `analysis` |
| 25 | [`prune-propose`](prune-propose/SKILL.md) | `audit` | `state` |
| 26 | [`refactor`](refactor/SKILL.md) | `build` | `analysis` |
| 27 | [`repair`](repair/SKILL.md) | `repair` | `state` |
| 28 | [`report`](report/SKILL.md) | `audit` | `analysis` |
| 29 | [`review`](review/SKILL.md) | `review` | `analysis` |
| 30 | [`security`](security/SKILL.md) | `security` | `enforcement` |
| 31 | [`ship`](ship/SKILL.md) | `ship` | `state` |
| 32 | [`status`](status/SKILL.md) | `status` | `state` |
| 33 | [`token-analyzer`](token-analyzer/SKILL.md) | `audit` | `analysis` |

