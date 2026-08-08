# Skill audit 2026-08-09 — Linear SHO-142

Audit goal: decide whether `/dev-kit:ship` and any other low-usage skills in this
plugin should remain public, merge with another workflow, or be removed.

Constraint (from Linear SHO-142):
- Do not duplicate PR #537 (feat-remove cleanup, merged 2026-08-02).
- Do not recreate PR #536 (report/inspect consolidation, merged 2026-08-02).
- Verify current release automation before changing ship.
- Record evidence and migration references before any deletion.

## Hard ambiguity — telemetry unavailable

`tools/skill_usage.py --days 90` returned `[skill-usage] no skills found under
logs/{claude-code,codex}/**/*.jsonl` and `~/.claude/logs/` contains only
`.gitkeep` + `.gitignore`. The 33 catalog skills all show `turns=0
invocations=0` because there is no log data to mine.

Per the task's hard-ambiguity rule, no cut proposals are made in this audit.
Per `memory/feedback-dont-cut-heavily-used-skills.md` and
`memory/feedback-read-code-before-cut-proposal.md`, cut proposals must be
gated on observed usage, not theoretical redundancy.

## Verdict table

| Skill | Verdict | Evidence line |
|---|---|---|
| `/dev-kit:ship` | KEEP | Referenced 12+ times as canonical release endpoint in user-facing docs; tag emit is automated by `.github/workflows/version-bump.yml` (lines 154-184) and marketplace refresh by `bin/devkit-refresh.sh`; no PR history of redundancy; SKILL.md has no lib/scripts/tests so the slash is a human gate-check anchor, not a code wrapper. |
| 32 other catalog skills | NO CHANGE | Cannot propose any cut without telemetry. All 33 catalog skills return 0 turns / 0 invocations in 90d because logs are absent, not because they are unused. Per `feedback-dont-cut-heavily-used-skills.md`, the burden of proof is on the proposer and cuts without observed-usage evidence get rejected. |

## Constraint verification

- **PR #537 (feat-remove cleanup)**: re-read; it removed a deprecated skill
  that was already superseded by `prune --target`. This audit does NOT touch
  `prune` or any equivalent.
- **PR #536 (report/inspect consolidation)**: re-read; it merged HTML
  rendering behind `inspect --html`. This audit does NOT touch `inspect`,
  `report`, or HTML rendering.
- **Release automation verification**: `.github/workflows/version-bump.yml`
  handles tag emission + manifest bump (lines 154-184: annotated tag at
  HEAD, push to origin); `bin/devkit-refresh.sh` handles cache refresh
  (marketplace git pull + rsync to `~/.claude/plugins/cache/dev-kit/dev-kit/
  <version>/`). Both run independently of `/dev-kit:ship`. Removing ship
  would not break the release pipeline (but we are NOT removing it).

## Why KEEP `/dev-kit:ship`

1. **Telemetry unavailable** — cannot confirm low usage. Per
   `feedback-dont-cut-heavily-used-skills.md` and the task constraints,
   "DO NOT delete any skill whose 90-day usage exceeds a sensible threshold
   without explicit user confirmation." Without telemetry, we cannot observe
   the threshold in either direction.
2. **High doc-graph coupling** — referenced as the canonical next-step in
   12+ user-facing docs: `README.md:127,144,780`, `README.ko.md:123,140,739`,
   `docs/home/00-index.md:18`, `docs/home/00-index.ko.md:18`,
   `docs/stages/STAGES.md:78`, `docs/stages/STAGES.ko.md:155`,
   `docs/observability/token-efficiency.md:305`, plus
   `docs/skills/{build,review,security,prune,refactor,docs-maintenance,
   babysit-pr,evaluate,research,bump}.md` and the matching SKILL.md files.
   Removing ship would require a coordinated docs purge for no measured
   gain.
3. **No PR history of redundancy** — no PR has ever proposed removing ship.
   PRs #537 and #536 cleaned up two *different* deprecated skills
   (`feat-remove`, `report`), not ship.
4. **Distinct human-facing role** — `/dev-kit:ship` is the only place where
   the release-gate state (Review verdict + main-block pass) is exposed as a
   single human-checkpoint slash. The actual tag emission, version bump, and
   marketplace refresh are all done by automation that already exists
   independently of the slash. The slash's value is human-anchoring the
   pipeline to the Stage 6 name in `docs/stages/STAGES.md`.
5. **Test coupling** — `tests/test_smoke.py:140` asserts `"ship"` is in
   `ahc.DEFAULT_MATRIX` (the 7 active-hook stages). Removing ship would
   require updating the smoke test alongside the skill deletion, which is
   exactly the kind of cross-file change that should be evidence-led, not
   pattern-matched.

## Open follow-up

If a future audit has telemetry, the candidates worth a second look are the
slash commands that appear in `prune-propose` 0-invocation output AND have no
internal (model) invocations. Without logs, we cannot draw that line today —
re-run this audit in 30 days once logs have accumulated.
