# Changelog

All notable changes to dev-harness-kit are documented here.

## [Unreleased]

### Fixed — `dev-kit:ci-setup --force` regression cluster (fix/ci-setup-regressions, issue #202)

Four `--force` regressions surfaced during the `sh-ai-x/claude-statusline` PR #9 refresh and surfaced again by `/dev-kit:security` on PR #11. All four addressed at the upstream template / install-engine level so future consumer refreshes don't re-introduce them.

- **fix(ci-setup)**: `templates/ci/.github/workflows/ci.yml` — `branch-policy` job now includes `actions/checkout@v4` before `scripts/branch-policy.sh`. Without this step, consumer repos whose branch-policy job depends on working-tree state (or that previously added a local checkout fix like commit `445a0b7` in `sh-ai-x/claude-statusline`) silently regressed on the next `--force` install — the upstream template had no checkout, so the consumer's local fix was overwritten away. With this change the upstream template owns the checkout, and consumer customizations layer on top.
- **fix(ci-setup)**: `templates/ci/.github/workflows/auto-fix-pr.yml` — cap step `exit 0` → `exit 1`. A zero exit let the subsequent agent steps run anyway, re-triggering the loop and defeating the 5-iteration cap. A non-zero exit fails this step → job stops → red CI check + human-review visibility. The label-based counter remains the primary cap mechanism; the exit-code change makes the cap actually a cap.
- **fix(ci-setup)**: `lib/ci_setup.py` — drift detection via per-file SHA-256 in `.dev-kit/ci-config.json`. The marker now records `installed_file_shas: { "<rel-path>": "<sha256>" }` for every EXPECTED_PATHS file. Before the next `--force`, `install_ci_config` compares each installed file's current SHA against the recorded SHA and emits a warning for every locally-modified file. Warnings are advisory — `--force` still proceeds, but the user sees what they're about to overwrite. Replaces the previous lint pass's pattern-only detection (which could not catch regressions like the missing checkout step).
- **feat(ci-setup)**: `templates/ci/.gitignore` — runtime-artifact gitignore fragment installed via marked-block merge. Covers `.dev-kit/.cost-gate/`, `.dev-kit/.eval-cache/`, `.dev-kit/logs/`, `logs/`. The marker file `.dev-kit/ci-config.json` is intentionally NOT in the fragment so the drift-detection SHA map keeps working. On install, the fragment is wrapped in `# >>> dev-kit >>>` / `# <<< dev-kit <<<` markers; the install merges into an existing `.gitignore` non-destructively (consumer-owned lines outside the block are preserved) and is idempotent on re-run.
- **test**: 9 new tests in `tests/test_ci_setup.py` covering all four fixes (checkout-step presence, cap-step exit code, SHA recording, drift warning, round-trip SHA after overwrite, gitignore fragment creation / preservation / idempotency). 40/40 ci-setup tests pass; the 15 unrelated failures in `tests/test_save_log*` and `tests/test_log_capture_coverage` are pre-existing worktree state from a prior interrupted session and not part of this fix.

### Removed — CI-side plugin-version gate (refactor/drop-ci-version-gate)

`ci_setup_version` + `min_version` (the `.dev-kit/ci-config.json` marker fields introduced in PR #61/#69) added a version-floor comparison consumers could opt into via `validate.py:validate_min_version`. Decision: dev-kit does not gate consumer CI on a plugin-version comparison — presence of the marker (and its content) is the only precondition. Removes duplicated/hardcoded version bookkeeping outside the single source of truth (`.claude-plugin/plugin.json`, read at runtime via `lib/ci_setup.py:plugin_version()`).

- **fix(ci-setup)**: `lib/ci_setup.py` — `_build_marker()` no longer writes `ci_setup_version`/`min_version`; `install_ci_config()` drops the min_version-preservation branch. `semver_lt()` removed (its only caller was the min_version comparison); `SEMVER_RE` kept (still used for general plugin-version format validation).
- **fix(validate)**: `templates/ci/scripts/validate.py` — `validate_min_version()` + `_semver_lt()` removed; `main()` runs 3 checks instead of 4. `templates/ci/ci-config.example.json` drops both fields.
- **docs**: `skills/build/SKILL.md`, `skills/ci-setup/SKILL.md`, `skills/audit-outdated/SKILL.md`, `README.md`, `docs/ci-setup.md` updated — pre-flight gates now read "marker absent" only, no version comparison language.
- **test**: `tests/test_validate_min_version.py` and `tests/test_semver_lt.py` deleted (dedicated to the removed feature; `SEMVER_RE` format coverage folded into `tests/test_smoke.py`). `tests/test_ci_setup.py` drops the 5 tests tied to `ci_setup_version`/`min_version`.

### Changed — rename `simplify` → `refactor`; add `/dev-kit:prune` (feat/refactor-rename-and-prune)

The `/dev-kit:simplify` skill was misnamed: it *refactors* (rewrites/extracts/renames) but does not delete code, so running it never reduced LOC. This release splits the verb along its real axis.

- **refactor!**: `skills/simplify/SKILL.md` → `skills/refactor/SKILL.md` (frontmatter `name: refactor`). The 3-phase wrapper now reads `inspect → build-refactor → review` and the body explicitly disambiguates from `/dev-kit:prune`. The internal `build-simplify` → `build-refactor` rename follows. The slash command `/dev-kit:simplify` is **not** preserved as an alias — update your muscle memory; `/dev-kit:refactor` is the new verb. ADR-0010 + docs/NAMING.md examples updated.
- **feat(skill)**: new `skills/prune/SKILL.md` (human-use, `user-invocable: true`, category=build, model=opus). 3-phase wrapper for project-wide *deletion* of AI slop, orphan code, and dead features: `inspect → build-prune → review`. Mirrors `/dev-kit:refactor` in shape; emits `rm`/`git rm` commands to a report and waits for the user to run them, mirroring `/dev-kit:feat-remove` discipline (no silent cascade, no self-deletion).
- **feat(skill)**: new `skills/build-prune/SKILL.md` (model-use, `user-invocable: false`). 3 internal passes: `orphan-code` (exports with no callers, files with no importers, unreachable branches) → `dead-feature` (capabilities with no live users) → `slop-pattern` (matches `audit-slop` heuristics but mutates rather than reports). Each pass ends with a quoted regression-test green.
- **feat(skill)**: new `skills/build-refactor/SKILL.md` (model-use, `user-invocable: false`). Internal 4-pass cleanup moved from the old `build-simplify`. No behavior change; rename only.
- **docs(readme)**: new "Skills by audience" section. Splits the 41 skills into user-facing (slash-autocomplete, 23) and model-use (auto-invoked, 18). Each user-facing row carries a one-line "when to use it" hint. New "Refactor" and "Prune" sections replace the old "Simplify" section, with a `refactor ≠ prune ≠ feat-remove` disambiguation table.
- **docs(adr)**: ADR-0010 + docs/NAMING.md example lists updated (`build-simplify` → `build-refactor`; `simplify` → `refactor`; add `prune` + `build-prune`).
- **test**: `tests/test_smoke.py` SKILL_COUNT 39 → 41. New `tests/test_refactor.py` (migrated from `test_simplify.py`; adds `disambiguates_from_prune` assertion). New `tests/test_prune.py` (covers both `prune/` and `build-prune/` schemas, MUST-L1..L4, never-rm-itself invariant). `tests/test_inspect.py` updated to assert both `/dev-kit:refactor` and `/dev-kit:prune` in the hand-off.
- **chore(skill-authoring)**: `.claude/rules/skill-authoring.md` human-use list (24 skills) and model-use list (14 skills) updated to match. The 38 → 41 count note corrected.

### Added — /dev-kit:bootstrap-full: one-shot CLAUDE.md + CI setup (feat/bootstrap-full)

New human-use skill that runs `/dev-kit:bootstrap` (CLAUDE.md + AGENTS.md + .dev-kit/.active-hooks.json) and `/dev-kit:ci-setup` (15 CI templates + pre-push hook + marker) in a single call. End state on disk is identical to running both parents in sequence, with no intermediate prompt. Hidden flags only: `--target DIR`, `--skip-ci`, `--force`, `--skip-verify`, `--slim|--full`, `--skip-sanity`, `--skip-map`, `--strict`, `--persist-audit`. `/dev-kit:bootstrap` and `/dev-kit:ci-setup` remain standalone for granular cases (refreshing just one half, or onboarding an existing repo).

- **feat(skill)**: `skills/bootstrap-full/SKILL.md` (human-use, `user-invocable: true`, category=bootstrap). 4-phase orchestration: bootstrap sub-skills → write_project_md → install_ci_config → verify. Combined summary printed on success.
- **test**: `tests/test_smoke.py` SKILL_COUNT 38 → 39.

### Added — slop-detector v2: multi-tier scanner + KO structural coverage + 5-dim audit (feat/slop-detector-v2)

The slop-detector shipped as a single regex (`hooks/slop-detector.sh`) covering ~24 KO+EN patterns. v2 splits detection into two tiers — phrase (T1, high-signal n-grams) and structure (T2, regex shapes incl. KO structural crutches, lazy extremes, false agency) — sourced from a single SSOT under `hooks/references/slop/`. Pattern count grew from 24 to ~110 (KO + EN + KO structural). The audit-slop subskill (`skills/audit-slop/SKILL.md`) is now a real multi-dim scanner that buckets files HIGH/MEDIUM/LOW against the 5-dim rubric (Directness / Rhythm / Trust / Authenticity / Density) defined in `hooks/references/slop/scoring.md`, replacing the previous count-only bucket. Bank files are portable POSIX ERE — BSD-grep and ugrep on macOS reject `\b`/`\m`/`\s`/`\w` in ERE mode (per the `BankFileInvariants` regression in `tests/test_slop_detector.py`), so the hook normalizes POSIX classes to Python `\s`/`\w`/`\d` for its in-process scan while leaving the bank readable by grep for manual eyeballing.

- **feat(hook)**: `hooks/slop-detector.sh` rewritten as a two-tier scanner. T1 always on, T2 default-on via `SLOP_LEVEL=2`. Severity ladder: KO phrase or KO structure → HIGH; ≥3 distinct T1 OR (≥1 T1 + ≥1 T2) → HIGH; ≥2 T1 → MEDIUM; 1 T1 OR 1 T2 → LOW. `SLOP_STRICT=1` exits 2 on HIGH. Lockfile and minified paths are skipped. The scan runs through Python `re` (Unicode-native) so the KO bank loads cleanly under POSIX-locale CI without LC_ALL gymnastics.
- **feat(references)**: new `hooks/references/slop/{phrases,structures,examples,scoring,README}.md` — single source of truth. ~50 phrase patterns (KO+EN), ~30 structural regexes (binary contrast, false agency, Wh-starters, lazy extremes, KO structural crutches, adverbs, three-item lists), 5-dim rubric, before/after examples, loader contract.
- **feat(audit-slop)**: `skills/audit-slop/SKILL.md` upgraded from "regex + bucket by count" to a real multi-dim scanner that walks paths, applies T1+T2, scores per the rubric, and emits HIGH/MEDIUM/LOW with per-file fix hints. Same haiku model, same read-only invariant, `Write`/`Edit` remain disallowed-tools.
- **test**: new `tests/test_slop_detector.py` (14 cases) covers clean / HIGH-EN / HIGH-KO / HIGH-KO-structure / binary contrast / Wh-starter / lockfile skip / minified skip / strict mode / inline fallback / regression fixtures / bank-file invariants. Fixtures: `tests/fixtures/slop/{sample-with-slop.md, sample-clean.md}`. `BankFileInvariants` rejects any regression that re-introduces non-portable ERE escapes.

Reference: implementation borrows the categorization shape from hardikpandya/stop-slop (MIT).

### Added — plugin-level version management + per-skill drift audit (feat/skill-versions)

This started as per-skill `version:` frontmatter on each of the 30 skills. The design was scrapped and replaced with a single-plugin-level version + diff-based per-skill audit — per-skill bookkeeping was bureaucratic tax with no real benefit at this scale (most "consumer-visible" changes touch multiple skills; the version number is a label without an enforced meaning). Final design:

- **feat(plugin)**: `.claude-plugin/plugin.json` now declares `version: "0.2.0"` (single source of truth, restoring the field PR #31 had dropped). `lib/ci_setup.py:plugin_version()` reads it; `SEMVER_RE` + `semver_lt` validate semver 2.0.0 (no `packaging` dep).
- **feat(ci-setup)**: the `.dev-kit/ci-config.json` marker carries `ci_setup_version` (mirror of `plugin.json:version`, auto-written) plus a single new opt-in field `min_version` (defaults to `"0.0.0"`; every released plugin satisfies the permissive default). `/dev-kit:ci-setup --force` rewrites `ci_setup_version` but **preserves** the consumer's `min_version` declaration.
- **feat(validate)**: `templates/ci/scripts/validate.py` appends a 4th check `validate_min_version()`. Single plugin-version compare (`ci_setup_version >= min_version`). Empty/missing `min_version` SKIPs (no behavior change for consumers who never edit the field). The check uses a self-contained `_semver_lt` (no `packaging` dep) so consumer repos don't need an extra requirement. 8 unit cases in `tests/test_validate_min_version.py` cover marker absent / no floor / empty floor / satisfied / violated / invalid semver (floor + installed).
- **feat(audit)**: new subskill `skills/audit-outdated/SKILL.md` (model-use, `user-invocable: false`) backs the user-facing `/dev-kit:audit --outdated` flag (added to parent `skills/audit/SKILL.md` Rules). Uses `lib/ci_setup.py:per_skill_drift()` to compare installed snapshot bytes vs HEAD on each `skills/<name>/SKILL.md` — no frontmatter parsing, no per-skill metadata to maintain. Stdout table, exit 1 on any drift, no `audit-report.md` file (KISS).
- **fix(refresh)**: `bin/devkit-refresh.sh` no longer `die`s on missing `version` field (PR #31's orphan); falls back to `git rev-parse --short HEAD` for the cache-dir segment with a one-line note. With `version:` restored in `plugin.json`, the fallback is now rarely needed but kept for forward-compat.
- **fix(ci-setup)**: self-contained regex-based frontmatter parser (replaces `yaml.safe_load` path that failed at runtime when `pyyaml` wasn't installed on CI Python 3.12).

### Changed — simplify `plan` skill gates (5 instead of 8)

- 8-gate flow (`frame → evidence → diff → non-goals → socratic → phase-decompose → seed-convergence → prd-writer`) collapsed to 5 gates (`frame → validate → non-goals → decompose → emit`) by merging the three overlapping "is this idea worth building?" gates (evidence / diff-profit / socratic-deepen) into a single `validate` gate with quantified inputs.
- 5-question grill-me replaced by a quantified loop: `value_score = LTV × reachable_users_year1 / total_cost` (threshold ≥ 3.0) and `ambiguity_score` 0-10 (target ≤ 3, narrowed each iteration). Evidence floor stays at 3 independent sources.
- Phase `index.json` schema now documented in `skills/plan/SKILL.md` (gate 4): per-step `status` machine (`unimplemented` / `pending` / `in_progress` / `completed` / `error` / `blocked`) wired to `lib/execute.py:register_step()` + `update_step_status()`. Plan only writes `unimplemented` + `pending`; runner owns the rest.
- Convergence frontmatter: `composite (ambiguity_score <= 3 AND value_score >= 3.0)`; `dedup_metric: identical-ambiguity-cycle=2`; `safety_valve=8`.

### Note — LLM review on workflow-file PRs

`anthropics/claude-code-action@v1` does its own workflow-validation and
silently skips when any workflow file in the PR differs from main. This
is a GitHub security feature, not a bug in our setup. The action prints
to the run log:

> Workflow validation failed. The workflow file must exist and have
> identical content to the version on the repository's default branch.

Practical impact:
- PRs that touch `.github/workflows/*.yml` cannot get the auto-fired LLM review.
- Use `gh workflow run review.yml --ref <branch>` (or `workflow_dispatch`
  with `pr_number` input) to manually invoke the review on those PRs.
- The LLM review DOES fire on PRs that don't modify any workflow file.

Verified: PR #42 (no workflow changes) got 4 inline review comments from
the LLM. PRs that modify workflows get zero inline comments — the gate
still extracts the verdict but the action had already skipped.

## [0.1.4] - 2026-07-07

### Changed — split into PR A and PR B (this PR = A)

This release rolls up three pending PRs (#38, #39, #40) but is split
into two PRs because GitHub's self-trigger block prevents the workflow
file from firing on PRs that modify it. **PR A (this one)** drops the
bootstrap/body phase split and fixes the doc/test drift; **PR B**
applies the `pull_request_target` migration + fork-safety guards to
the local workflow files (PR B can't get auto-reviewed, but is
mechanical and well-tested).

### PR A — drops #38 bootstrap/body phase split

The split was intended to work around `anthropics/claude-code-action@v1`'s
workflow-validation gate by landing the 3 workflow files in their own PR.
The `pull_request_target` migration (PR B) solves the same problem
more cleanly without forcing consumers into a 2-PR install. The
bootstrap-body split also introduced a critical regression: the
bootstrap-only install state could not pass `scripts/validate.py`
(the marker was intentionally absent, so the validator saw
`phase='missing'` and checked ALL_REQUIRED, reporting 8 spurious
missing files).

- `lib/ci_setup.py:install_ci_config()` is back to its single-shot signature.
  `BOOTSTRAP_PATHS` / `BODY_PATHS` / `_resolve_paths` / `phase=` kwarg /
  marker-skip-during-bootstrap are removed.
- `templates/ci/scripts/validate.py` reverted to flat `REQUIRED_FILES`
  (8 entries) with no `phase` parameter.
- `skills/ci-setup/SKILL.md` Two-phase install section removed;
  Iron-Law flag list restored; Files Installed table back to single
  15-row list.
- `tests/test_ci_setup_split_install.py` deleted (194 lines of tests
  for the dropped phase split).
- `tests/test_ci_setup.py::test_post_install_checklist_is_complete`
  needle list restored (removed `'/dev-kit:ci-setup'` added by #38).
- `tests/test_review_gate.py` now reads the consumer template SSOT
  (`templates/ci/.github/workflows/review.yml`) instead of the local
  `.github/workflows/review.yml`. The two were drift-prone: a future
  edit to one copy would silently pass tests against whichever copy
  was in lockstep.
- `docs/ci-setup.md` FAQ rewritten to describe the new gate-tolerance
  contract (Approve + warning, not hard fail).

### PR B (separate, follow-up) — extends #40 to local workflow

PR #40 only migrated the consumer template; the dev-kit repo's OWN
`.github/workflows/review.yml` still had `on: pull_request:` and the
same workflow-validation skip bug. PR B applies the full migration
to the local workflow (pull_request_target trigger, concurrency
group, per-job fork-safety guard on review/security/gate), adds the
fork guard to `.github/workflows/auto-fix-pr.yml`, and adds a visible
`gh pr comment` signal when the gate defaults to Approve on missing
verdict (so silent skips aren't invisible to the PR author).

### Notes
- Bootstrap trade-off (unchanged from PR #40): a PR that ADDS
  `review.yml` for the first time cannot be triggered under
  `pull_request_target` (file isn't yet on main). The fix assumes
  `review.yml` is already on the consumer repo's main.
- No schema or marker version bump — `MARKER_SCHEMA_VERSION` is
  unchanged.

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
- lib modules: `state_codec, active_hooks_codec, write_project_md, execute, methodology/{abc,tdd,__init__}, install.sh`
- Iron Laws SSOT in `CLAUDE.md §1` (5 laws)
- `.dev-kit/` state files (state.json, .active-hooks.json, hand-off/*.md)
- Pre-impl gate (`docs/PRE-IMPL-CHECK.md`) + 8-dimension cost analysis (`docs/COST-ANALYSIS.md`)
- 117 pytest tests passing

### Absorbed (5 → 1)
- `pm-prd-fast` → `skills/plan/plan-ralph/`
- `interview-harness-skills` → merged into `plan-ralph`
