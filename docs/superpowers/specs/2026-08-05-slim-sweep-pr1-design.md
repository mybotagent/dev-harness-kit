# PR-1: slim sweep — design spec

**Date:** 2026-08-05
**Branch:** `chore/slim-sweep-pr1`
**Source review:** dev-harness-kit code-review (2026-08-05, sub-agent `aa8be82811cfd87f8`)
**Trigger:** User requested "no duplicate skills, fit project nature, remove unnecessary, work slim"
**Bundle order:** PR-1 (this) → PR-2 (lint locks in slim) → PR-3 (hook observability + shell tests) → PR-4 (plugin self-bootstrap)

---

## Goal

Cut or merge skills with no production callers in observed telemetry, without removing observability/recovery tooling that has value at low usage. Document the MCP integration decision. Single PR, 4 actions, no inter-dependencies.

## Non-goals

- Adding new features (deferred per user slim directive)
- Renaming skills beyond what's required for the bootstrap merge
- Touching any non-skill code (lib/, hooks/, bin/, templates/, tests/) except where required to fold audit's secret/slop scans into inspect
- Changing slash names except `/dev-kit:bootstrap-full` → `/dev-kit:bootstrap`

---

## Action 1 — Drop `user-invocable: true` from `valuate`

**Why:** `/dev-kit:valuate` has 0 user invocations in any 30/90/all-time window. The auto-gate that previously made it mandatory was removed in #463. Keeping the skill + lib code as model-use preserves the option for `/dev-kit:plan` or future stages to call into the rubric without exposing the slash to operators.

**Diff:**
```yaml
# skills/valuate/SKILL.md frontmatter
- user-invocable: true
+ user-invocable: false
```

**Untouched:** `lib/valuation_engine.py`, `lib/llm_judge.py`, all `tests/test_llm_judge*.py`, `tests/test_push_intent_judge.py`, all tests in `tests/test_eval_session.py`, `tests/test_interview_engine.py`, `tests/test_harness_audit.py`. SKILL.md body unchanged.

**Risk:** None material. Skill still callable by model; disappears from user slash menu.

**Rollback:** Revert single frontmatter line.

---

## Action 2 — Cut `/dev-kit:audit` slash; fold secret-scan + slop-scan into `/dev-kit:inspect` as flags

**Why:** `/dev-kit:audit` has 0 user invocations in 30/90/all-time windows. The grep across `lib/`, `bin/`, `hooks/`, `tests/` returns only test files (which assert audit exists), README/CHANGELOG/docs, and `.claude/worktrees/` (ignored). No production caller invokes `/dev-kit:audit`. The two modes that have standalone value (secret-scan, slop-scan) are already wired to hooks (`hooks/secret-scan.sh`, `hooks/references/slop/`) — surfacing them via inspect flags preserves the capability with one fewer slash.

The third audit mode (outdated-skill drift via `lib/ci_setup.py:per_skill_drift`) is already used by `/dev-kit:ci-doctor` and remains untouched.

**Diff:**
- **Delete** `skills/audit/SKILL.md` only. No `agents/`, `scripts/`, or supporting files to remove.
- **Edit** `skills/inspect/SKILL.md` body to add two new flags:
  - `--secrets` — runs `hooks/secret-scan.sh` against `paths`, renders findings as `dim="secret"` rows in the markdown report (matching audit's old Mode 1 output shape)
  - `--slop` — runs the T1 phrase + T2 structure scan from `hooks/references/slop/{phrases,structures}.md`, renders findings as `dim="slop"` rows (matching audit's old Mode 2 output shape)
- **Preserve** `lib/ci_setup.py:per_skill_drift` (live, used by ci-doctor).
- **Preserve** `hooks/secret-scan.sh` (still wired to PreToolUse).
- **Preserve** `hooks/references/slop/` (still wired to slop-detector.sh).

**Test changes:**
- Delete `tests/test_audit_*.py` (only if they test the slash; if they test the underlying scan logic, rename to `test_inspect_secrets.py` / `test_inspect_slop.py` and update imports).
- Add `tests/test_inspect_secrets_flag.py` and `tests/test_inspect_slop_flag.py` — assert that `inspect --secrets` and `inspect --slop` produce the same finding shape as the deleted audit tests.

**Risk:** In-flight consumer automation that hardcodes `/dev-kit:audit --secrets-only` or `/dev-kit:audit --slop-only`. Mitigated by CHANGELOG entry.

**Rollback:** Restore `skills/audit/SKILL.md` from git history.

---

## Action 3 — Merge `bootstrap` + `bootstrap-full` into single `/dev-kit:bootstrap`

**Why:** Both are onboarding skills with 0 invocations in 30/90/all-time windows (expected for day-1 skills — operators run them once per project then never again). The SKILL.md bodies are 80% identical. README documents the equivalence: "`bootstrap-full` is exactly `bootstrap` followed by `ci-setup`". Two slashes for one operation is the duplicate the user wants eliminated.

**Design choice (per user):**
- Slash name: `/dev-kit:bootstrap` (shorter, more natural).
- Directory: `skills/bootstrap/SKILL.md` (canonical home; old `bootstrap-full/SKILL.md` deleted).
- Behavior: current `bootstrap-full` behavior (CLAUDE.md + AGENTS.md + 4 index.md + ci-setup). The bare-bootstrap-only path is now an explicit decision the operator makes.
- Runtime prompt: when invoked, the skill prompts the operator: "Also install CI templates (ci-setup)? [Y/n]". If Y → run ci-setup as today. If N → print the unavailable-features list below.
- Documented unavailable-features list (printed on N):
  - `/dev-kit:ci-doctor` (drift detection) — requires `.dev-kit/ci-config.json` marker written by ci-setup
  - `/dev-kit:bump` version-bump workflow — requires pre-push hook from ci-setup
  - 15 CI workflow templates in `.github/workflows/` (validate.yml, test.yml, auto-fix.yml, etc.)
  - Pre-push hook (`.git/hooks/pre-push`)
  - `PreCompletionChecklistMiddleware` (PR-level cost flag aggregation)
  - `/dev-kit:evaluate` harness-quality gate (depends on ci-setup-installed workflows)
- **Old `/dev-kit:bootstrap-full` slash: removed** (hard cut, no alias — per user pushback toward clean integration).

**Diff:**
- **Edit** `skills/bootstrap/SKILL.md` body — replace current "Minimal First-Run Setup" content with the merged orchestrator that runs bootstrap + optional ci-setup, with the runtime prompt + unavailable-features list documented.
- **Delete** `skills/bootstrap-full/SKILL.md`.

**Test changes:**
- Add `tests/test_bootstrap_no_ci.py` — assert that running bootstrap and answering "N" to the ci-setup prompt prints the unavailable-features list and skips `lib/ci_setup.py:install_ci_config()`.
- Add `tests/test_bootstrap_with_ci.py` — assert that answering "Y" runs the full 4-phase orchestration and ends with the same on-disk state as today's `bootstrap-full`.
- Update `tests/test_smoke.py` fixture (remove `bootstrap-full` entry).

**Risk:** Anyone running `/dev-kit:bootstrap-full` (muscle memory or bookmark) gets "skill not found". CHANGELOG entry required. Also: the runtime prompt adds a new interactive element that didn't exist before — operators used to `bootstrap-full` getting the full setup automatically will now be interrupted. Mitigated by the documented unavailable-features list (operators who know what they're doing can pre-decide).

**Rollback:** Restore `skills/bootstrap-full/SKILL.md` and revert `skills/bootstrap/SKILL.md` body.

---

## Action 4 — MCP out-of-scope decision (docs only)

**Why:** The plugin has `commands/`, `skills/`, `hooks/`, `lib/`, `tools/`, `agents/` but no `mcp/` directory or MCP server entry. The `/dev-kit:config` skill lists "skill + MCP + hook + methodology picker" but only `skill` and `methodology` are wired. Without an explicit decision, future contributors may add MCP support ad-hoc, increasing surface area inconsistently with the slim directive.

**Diff:**
- **Add** a new file `docs/decisions/0001-no-mcp.md` (decision record) with:
  - Status: Accepted (2026-08-05)
  - Context: plugin surface, no MCP entry, slim directive
  - Decision: no MCP server entry in this plugin; intentional
  - Consequences: `/dev-kit:config` MCP picker removed; consumer-repo integration limited to slash + hooks + skills
  - Revisit when: 3+ consumer requests land, or MCP spec stabilizes for hooks/skills bundles
- **Edit** `README.md` — add a one-line note in the architecture section: "MCP integration: intentionally out of scope (see [docs/decisions/0001-no-mcp.md](../../docs/decisions/0001-no-mcp.md))."
- **Edit** `skills/config/SKILL.md` — remove the MCP option from the picker (keep skill + hook + methodology).

**Risk:** None. Docs-only change.

**Rollback:** Revert commit.

---

## Cross-cutting changes

- **CHANGELOG.md** — entry under unreleased: "feat(skills)!: slim sweep (PR-1) — drop valuate user-invocable; cut /dev-kit:audit; merge bootstrap-full into /dev-kit:bootstrap with ci-setup prompt; document MCP out-of-scope. Breaking: `/dev-kit:audit` and `/dev-kit:bootstrap-full` removed."
- **README.md** — update the skill table to remove the three deleted/renamed entries.
- **tests/test_skill_governance.py** — update fixture to reflect new skill inventory.
- **tests/test_smoke.py** — update fixture.

## Out of scope (deferred to later PRs)

- PR-2: SKILL.md governance lint tighten (Reinforce #1, #2 from review)
- PR-3: Hook observability + bats tests (Reinforce #3, #4 + Add #1, #9 + Cut #4)
- PR-4: Plugin self-bootstrap `--self` flag (Add #5 only; typed CLI shim deferred as YAGNI)
- Backlog (Linear): code-viz dark mode, consumer health badge, stage graph SVG generator

## Testing strategy

| Test | Covers | Status |
|---|---|---|
| `tests/test_skill_governance.py` | valuate `user-invocable: false`; no orphan `user-invocable: true` on removed skills; new inspect flags | Update |
| `tests/test_inspect.py` | `--secrets` produces same shape as old audit secret mode | New |
| `tests/test_inspect.py` | `--slop` produces same shape as old audit slop mode | New |
| `tests/test_bootstrap_no_ci.py` | N prompt → skip ci-setup + print unavailable-features list | New |
| `tests/test_bootstrap_with_ci.py` | Y prompt → full 4-phase orchestration, same on-disk state as old bootstrap-full | New |
| `tests/test_audit.py` | DELETE (slash no longer exists) | Delete |
| `tests/test_smoke.py` | All skill frontmatter satisfies naming + category | Update |
| Smoke: `/dev-kit:ci-doctor` | Drift detection still works after audit cut (uses `lib/ci_setup.py:per_skill_drift`) | Manual |
| Smoke: `/dev-kit:ci-doctor` after fresh bootstrap with N | Drift detection reports "no ci-config.json marker" (expected) | Manual |

## Risk + rollback (per action)

See per-action sections above. Net diff footprint: ~6–10 files. All four actions are independently revertible via git revert.

## Open questions

None at spec time. Bootstrap prompt wording finalized at implementation.
