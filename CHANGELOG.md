# Changelog

All notable changes to dev-harness-kit are documented here.

## [0.1.5] - 2026-07-07

### Fixed
- **Wrapper pattern for the claude-code-action validation gate**:
  `templates/ci/.github/workflows/claude-review.yml` and
  `claude-security.yml` are new workflow_call-only wrapper files that
  contain the `anthropics/claude-code-action@v1` invocation. `review.yml`
  is now a thin orchestrator that calls them via
  `uses: ./.github/workflows/claude-{review,security}.yml`.

  Why this matters: the action validates "the workflow file must be
  identical to the version on the repository's default branch" against
  the file the action is invoked FROM. With the wrapper pattern, the
  action is invoked from `claude-{review,security}.yml`, which is
  never modified by PRs that change `review.yml` — so the validation
  gate passes on EVERY PR, including the very first PR that adds or
  modifies `review.yml` itself. This eliminates the chicken-and-egg
  bootstrap trade-off from 0.1.4's `pull_request_target` fix.

- **`review.yml` shrunk 420 → 146 lines**: orchestrator only. Triggers
  (`pull_request_target` + `workflow_dispatch`), fork-safety guards,
  concurrency group, and the verdict gate remain. The two `uses:` calls
  to the wrapper files replace the inline claude action steps.

- **`lib/ci_setup.py` EXPECTED_PATHS** now 17 paths (was 15). The two
  new wrapper files are in BOOTSTRAP_PATHS so they ship in the same
  PR as `review.yml` (the orchestrator's `uses:` references must
  resolve on first run).

- **POST_INSTALL_CHECKLIST step 4** rewritten: the two-phase install
  protocol (formerly required to dodge the validation gate) is no
  longer needed. Single-shot `--force` install produces a working
  review pipeline from the very first PR.

### Notes
- No schema or marker version bump (`MARKER_SCHEMA_VERSION` is content-
  only per the 0.1.3 note). `ci-setup --force` on a consumer repo picks
  up the new files automatically.
- Bootstrap order is now: one PR (with all 5 workflow files + scripts)
  → merge → every subsequent PR gets a real review. No two-phase dance.

## [0.1.4] - 2026-07-07


### Fixed
- **`templates/ci/.github/workflows/review.yml`**: trigger switched from
  `pull_request` to `pull_request_target`. The previous trigger caused
  `anthropics/claude-code-action@v1` to silently skip the agent whenever
  the PR head modified `.github/workflows/review.yml` (e.g. on every
  `ci-setup --force` template refresh) — the action's workflow-validation
  gate refuses to run when the calling workflow file differs from main.
  Result: zero AI comments posted on exactly the PRs that need them most.
  Under `pull_request_target`, the running workflow file is from the base
  branch (main), so the validation passes; the agent reads the PR diff
  via `gh pr diff` + the explicit `actions/checkout @ head.sha` step.
- **Fork safety on both review.yml + auto-fix-pr.yml**: each agent job +
  the severity gate now skip silently when
  `github.event.pull_request.head.repo.full_name != github.repository`,
  preventing the base-branch context from being exposed to fork PRs.
- **`review.yml` concurrency group**: cancel-in-progress on
  `pull_request_target` so a force-push mid-review doesn't double-charge
  the agent quota. `workflow_dispatch` runs are unaffected.

### Notes
- Bootstrap trade-off: a PR that ADDS `review.yml` for the first time
  cannot be triggered under `pull_request_target` (file isn't yet on
  main). The fix assumes `review.yml` is already on the consumer
  repo's main. After one manual merge of a bootstrap PR, subsequent
  PRs flow through normally.
- No schema or marker version bump — `MARKER_SCHEMA_VERSION` is
  unchanged. Consumers who re-run `ci-setup --force` get the trigger
  swap without any version gate.

## [0.1.3] - 2026-07-07

### Fixed
- **`templates/ci/.github/workflows/review.yml` Combined verdict gate**: PR mode and `workflow_dispatch` mode now share symmetric tolerance. Previously PR mode `exit 1`'d on missing verdicts (`Missing verdict (review='' security='')`) whenever the `/dev-kit:*` agents skipped posting a `**Verdict:**` comment as the first line of a PR comment, while `workflow_dispatch` mode defaulted to Approve. The hard-fail contradicted the gate's own documented tolerance contract (lines 354-358) for unparseable verdicts. The patched gate surfaces a `::warning::` in both modes when a verdict is missing and defaults the missing dim to `Approve`. The human gate (`REVIEW_REQUIRED` / `CHANGES_REQUESTED`) remains authoritative for merge-block.

### Added
- **`lib/ci_setup.py:lint_installed_workflows()`** + **`_KNOWN_STALE_PATTERNS` tuple**: a non-fatal scan over installed `EXPECTED_PATHS` for known-stale patterns whose root cause previously slipped past local smoke tests (`scripts/validate.py` + `scripts/ci-local.sh` both pass on stale installs because they don't exercise the GitHub Actions gate). The first known-stale pattern is the pre-0.1.3 gate hard-fail. Findings populate `InstallReport.warnings` and the skill body prints them in the install summary table.
- **`InstallReport.warnings: List[str]`** field (defaults to `[]`); backward-compatible with existing test contracts.
- **`install_ci_config(..., lint: bool = True)`** kwarg: lint runs by default on every install, including no-op idempotent re-installs (so a user running ci-setup with no `--force` still gets the warning if their previously-installed `review.yml` is stale). Set `lint=False` to suppress.
- **`skills/ci-setup/SKILL.md`**: new `## Phase 1.7 -- Lint pass` section and Iron-Law paragraph documenting the warning-class output.

### Notes
- `MARKER_SCHEMA_VERSION` unchanged (`1.0.0`); consumers who re-run `ci-setup --force` get the gate-tolerance fix without any version gate.
- The new lint pass is the surface area for adding more known-stale patterns in future: add a tuple to `_KNOWN_STALE_PATTERNS`, ship a release.

## [0.1.2] - 2026-07-07

### Fixed
- **`templates/ci/.github/workflows/review.yml` verdict regex** (and the sibling `.github/workflows/review.yml`): anchor with `^` so prose lines containing the substring `**Verdict:**` mid-sentence are NOT picked by `tail -1` as the verdict header. Without the anchor, the gate's `severity_gate` reads `verdict=""` on PRs where the agent's review output mentions the verdict keyword mid-sentence, and exits 1 with `Missing verdict (review='' security='')`. Regression test: `tests/test_review_gate.py` (6 regex + 2 byte-equality tests). Same patch applied to `.github/workflows/review.yml` so the two files stay in lockstep.

### Added
- **`lib/ci_setup.py:POST_INSTALL_CHECKLIST`** (5 items) and **`lib/ci_setup.py:_print_post_install_checklist()`**: rendered opt-in via the new `print_checklist: bool = False` kwarg on `install_ci_config()`. Covers the secrets, hooks activation, and the first-PR validation-skip rule. `<OWNER>/<REPO>` is auto-filled from `git remote get-url origin` when available.
- **`lib/ci_setup.py:preflight_probe()`** + **`ProbeResult` dataclass**: 5-line `gh` probe (auth status, repo reachable, three secret checks). All read-only; the skill never prints secret values. Returns `[SKIP]` for every probe when `gh` is absent or unauthenticated -- the install still proceeds.
- **`skills/ci-setup/SKILL.md`**: new `## Phase 1.5 -- Pre-flight probe` and `## Phase 4 -- Post-install checklist` sections. Refreshed the "Files Installed (8 expected paths)" table to 15 entries (was stale since 0.1.1).
- **`docs/ci-setup.md`**: new `## Post-install checklist` section near the top + `## FAQ` section that documents the bootstrap-first-PR validation-skip rule.
- **`tests/test_ci_setup.py`**: 3 new tests (`test_post_install_checklist_is_complete`, `test_preflight_probe_skips_on_missing_gh`, `test_print_checklist_kwarg_does_not_break_existing_callers`).

### Notes
- `MARKER_SCHEMA_VERSION` unchanged (`1.0.0`); the marker stays content-only per the comment at `lib/ci_setup.py:73-77`. There is no marker-shape change in 0.1.2, so consumers running `ci-setup --force` get the verdict-regex fix without any version gate.
- Known issue (not fixed in 0.1.2): `skills/build/SKILL.md` pre-flight gate still references `ci_setup_version < "0.1.0"` while the marker no longer writes that field. The default `data.get("ci_setup_version", "0.0.0") < "0.1.0"` resolves to `False` (passes), so today's behaviour is silently permissive -- but the docs reference is misleading and should be aligned in a follow-up. Tracked separately.

## [0.1.1] - 2026-07-07

### Added
- **Worktree enforcement** (PR #22): 3 new hooks (`worktree-guard.sh`, `task-detector.sh`, `session-start-check.sh`) + `hooks/lib/worktree-detect.sh` shared discriminator + `.claude/rules/git-workflow.md` rule doc + 14 regression tests. Rule: every task = new worktree + new session + new branch; no edits in the main checkout.
- **`bin/devkit-refresh.sh`**: one-shot script that pulls the marketplace clone + rsyncs the cache. Used after PR merge to keep the plugin cache current without running `claude plugin install`.
- **ci-setup consumer-install** (PR #23 + #27): `lib/ci_setup.py` now ships 15 files (was 8). EXPANDED `EXPECTED_PATHS` with 4 worktree-rule files. New tests in `tests/test_ci_setup.py` for the new files.
- **Self-aware `review.yml`** (PR #27): the template's install step detects self-install vs consumer-install at runtime. Same workflow file works in both dev-harness-kit's own CI and consumer repos via `ci-setup`.
- **`tests/test_review_install.py`** (9 tests) + **`tests/test_worktree_guard.py`** (14 tests) + **`tests/test_ci_setup.py`** expanded (4 new tests for the 0.1.1 files).

### Changed
- **`.claude-plugin/marketplace.json`** (PR #28): `source` is now the schema-valid `url` object form (`{"source": "url", "url": "...", "ref": "main"}`) instead of a bare URL string. Fixes the "source type your Claude Code version does not support" install error.
- **`.claude-plugin/plugin.json`**: version `0.1.0` → `0.1.1`.
- **`lib/ci_setup.py`**: `MARKER_SCHEMA_VERSION` `1.0.0` → `1.2.0`; `DEFAULT_CI_SETUP_VERSION` `0.1.0` → `0.1.2`. Forces consumer repos to refresh templates on next `ci-setup --force`.
- **`tests/test_ci_setup.py`**: bumped version constants; added 4 new tests for the new files.

### Removed
- **Auto-update SessionStart hook** (PR #24 → reverted in PR #26): the SessionStart auto-update that pulled marketplace + ran `claude plugin install` was found to have a session-specific CLI bug and marginal value. Replaced with `bin/devkit-refresh.sh` (manual one-shot) for explicit opt-in refresh.

### Fixed
- **`claude plugin install` failure** (PR #28): bare string source was invalid per the marketplace schema. `url` object form makes install work.
- **Plugin cache 0.1.0 reference breakage** (post-#22 cleanup): an over-eager cache cleanup broke in-flight sessions keyed to `0.1.0`. The cache now keeps both version directories (`0.1.0/` + `0.1.1/`) so in-flight references resolve cleanly.

## [0.1.0] - 2026-07-04

### Added
- Plugin skeleton: `.claude-plugin/{marketplace, plugin/{plugin, hooks}}.json`
- 17 skills across 9 categories (bootstrap, plan, design, build, review, security, audit, shortcuts, ship)
- 15 commands (0-arg): `bootstrap / plan / design (alias) / build / review / security / ship / audit / eval / repair / config / status / onboard` + 2 shortcuts
- 5 hook scripts: `tdd-guard, bash-guard, secret-scan, slop-detector, stop-verify` (all `exit 0` advisory by default; `--strict` enables hard-block)
- lib modules: `state_codec, active_hooks_codec, write_claude_md, execute, methodology/{abc,tdd,__init__}, install.sh`
- Iron Laws SSOT in `CLAUDE.md §1` (5 laws)
- `.dev-kit/` state files (state.json, .active-hooks.json, hand-off/*.md)
- Pre-impl gate (`docs/PRE-IMPL-CHECK.md`) + 8-dimension cost analysis (`docs/COST-ANALYSIS.md`)
- 117 pytest tests passing

### Absorbed (5 → 1)
- `pm-prd-fast` → `skills/plan/plan-ralph/`
- `interview-harness-skills` → merged into `plan-ralph`
