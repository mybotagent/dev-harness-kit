# Skills documentation index

This is the detailed, human-readable documentation layer for every skill
shipped by the `dev-kit` plugin — one page per skill under `docs/skills/`,
expanding on the terse `skills/<name>/SKILL.md` source each is generated
from. For the machine-facing summary table (the one `SKILL.md` frontmatter
drives directly), see [`skills/README.md`](../../skills/README.md); for a
one-line pointer from the project root, see the main
[`README.md`](../../README.md#skills-by-audience).

Every skill declares two frontmatter fields that matter for navigation:

- **`user-invocable`** — `true` means you type `/dev-kit:<name>`; `false`
  means it's an internal sub-skill the model invokes automatically as part
  of a parent skill's flow, and it never appears in slash autocomplete.
- **`alpha`** — `state` (drives the harness state machine), `enforcement`
  (a deterministic guard the user can't talk their way past), or `analysis`
  (pure reasoning over a corpus). See `CLAUDE.md` §1 (L6/L7) and
  `rules/skill-authoring.md` for the full rationale.

The current count is volatile (skills are added and removed as the plugin
evolves). Discover it with:

```bash
find skills -mindepth 2 -maxdepth 2 -name SKILL.md | wc -l
grep -lE '^user-invocable: false' skills/*/SKILL.md | wc -l   # model-invoked sub-skills
```

---

## Human-invocable skills (type `/dev-kit:<name>`)

### Setup / bootstrap

| Skill | Alpha | Summary |
|---|---|---|
| [`bootstrap`](bootstrap.md) | `state` | First entry — generates minimal `CLAUDE.md` + `AGENTS.md` + `active-hooks.json` on a fresh repo. |
| [`bootstrap-full`](bootstrap-full.md) | `state` | One-shot `bootstrap` + `ci-setup` — the new-project default. |
| [`ci-setup`](ci-setup.md) | `enforcement` | Installs dev-kit's reusable CI workflow templates into a target project. |
| [`config`](config.md) | `state` | Skill / MCP / hook / methodology picker. |

### Plan → Build

| Skill | Alpha | Summary |
|---|---|---|
| [`plan`](plan.md) | `state` | Idea → `PRD.md` + `phases/<name>/` through a 5-gate loop. |
| [`build`](build.md) | `state` | Per-step sub-agent delegation with an integrated TDD + auto-fix loop. |
| [`feat-remove`](feat-remove.md) | `state` | Safely remove a feature: call-graph sweep, dependent flagging, deletion report. |

### Review → Ship

| Skill | Alpha | Summary |
|---|---|---|
| [`review`](review.md) | `analysis` | Parallel correctness + security + architecture review with a false-positive filter. |
| [`security`](security.md) | `enforcement` | Full OWASP Top 10 2025 (A01–A10) fan-out with a verifier pass. |
| [`audit`](audit.md) | `state` | 0-arg cross-cutting bulk slop + secret audit (read-only). |
| [`inspect`](inspect.md) | `analysis` | 8-dimension read-only code-health audit. |
| [`refactor`](refactor.md) | `analysis` | 3-phase cleanup chain: `inspect → build-refactor → review`. |
| [`prune`](prune.md) | `analysis` | 4-phase deletion sweep: sweep → dependents → report → verify. |
| [`babysit-pr`](babysit-pr.md) | `state` | PR babysitter loop: poll CI, fix, commit, re-iterate to a green Approve. |
| [`ship`](ship.md) | `state` | Release tag emit; gate check only. |
| [`bump`](bump.md) | `state` | Explicit `plugin.json` version bump + push. |

### Eval / cost / reporting

| Skill | Alpha | Summary |
|---|---|---|
| [`eval`](eval.md) | `analysis` | Agent-behavior eval across review/security/plan dimensions + a 20-checkbox code-sanity rubric. |
| [`repair`](repair.md) | `state` | 8-step Eval-Repair loop ending in a single Human Review approval. |
| [`report`](report.md) | `analysis` | HTML viewer combining the latest eval + inspect reports. |
| [`token-analyzer`](token-analyzer.md) | `analysis` | Token-efficiency dashboard rendered from session log transcripts. |
| [`cost-gate`](cost-gate.md) | `enforcement` | Live, read-only cost ledger + PR cost-flag trailer. |
| [`status`](status.md) | `state` | HOTL visualization: loop progress + cycles + hand-off chain + eval score. |
| [`ci-doctor`](ci-doctor.md) | `enforcement` | Read-only PASS/FAIL audit of CI readiness. |
| [`docs-maintenance`](docs-maintenance.md) | `analysis` | Audits stale docs and refreshes the README without recording volatile facts. |
| [`prune-propose`](prune-propose.md) | `state` | Usage-telemetry dump + per-skill delete proposal, user-approved. |

### Shortcuts / maintenance

| Skill | Alpha | Summary |
|---|---|---|
| [`log`](log.md) | `state` | Toggle session loghooks (`setup`/`on`/`off`/`status`) per project. |
| [`codex-cache-update`](codex-cache-update.md) | `analysis` | Refresh the Codex marketplace checkout + versioned plugin cache. |
| [`llm-refresh`](llm-refresh.md) | `analysis` | Refresh `docs/llm-info/<provider>.json` from each vendor's pricing page. |

### Design

| Skill | Alpha | Summary |
|---|---|---|
| [`proposal`](proposal.md) | `state` | Renders `docs/proposals/<main>/<sub>.yaml` to a self-contained review HTML. |

---

## Model-invoked sub-skills (internal — not in slash autocomplete)

These are `user-invocable: false`. The model invokes them automatically as a
step inside their parent skill's flow; you never type them directly.

| Skill | Alpha | Parent | Summary |
|---|---|---|---|
| [`build-tdd`](build-tdd.md) | `enforcement` | `/dev-kit:build` | Red-Green-Refactor cycle; `tdd-guard` hook enforces no production code without a failing test. |
| [`build-debug`](build-debug.md) | `enforcement` | `/dev-kit:build` | 4-phase systematic debugging; no fix before Phase 1 (reproduce) completes. |
| [`build-verify`](build-verify.md) | `enforcement` | `/dev-kit:build` | Verification-before-completion; no "done" without a quoted exit code + test count. |
| [`build-refactor`](build-refactor.md) | `enforcement` | `/dev-kit:refactor`, `/dev-kit:prune` | 4-pass cleanup (dead → dup → naming → coverage); no cleanup without a regression test. |
| [`hook-doctor`](hook-doctor.md) | `enforcement` | auto (visible hook failure) | Diagnose failed Claude Code / Codex hooks and repair safe cache + registration drift. |

---

## Alphabetical (all skills)

| Skill | Category | Alpha | Invocable |
|---|---|---|---|
| [`audit`](audit.md) | `audit` | `state` | human |
| [`babysit-pr`](babysit-pr.md) | `ship` | `state` | human |
| [`bootstrap`](bootstrap.md) | `bootstrap` | `state` | human |
| [`bootstrap-full`](bootstrap-full.md) | `bootstrap` | `state` | human |
| [`build`](build.md) | `build` | `state` | human |
| [`build-debug`](build-debug.md) | `build` | `enforcement` | model |
| [`build-refactor`](build-refactor.md) | `build` | `enforcement` | model |
| [`build-tdd`](build-tdd.md) | `build` | `enforcement` | model |
| [`build-verify`](build-verify.md) | `build` | `enforcement` | model |
| [`bump`](bump.md) | `ship` | `state` | human |
| [`ci-doctor`](ci-doctor.md) | `audit` | `enforcement` | human |
| [`ci-setup`](ci-setup.md) | `bootstrap` | `enforcement` | human |
| [`codex-cache-update`](codex-cache-update.md) | `shortcuts` | `analysis` | human |
| [`config`](config.md) | `config` | `state` | human |
| [`cost-gate`](cost-gate.md) | `audit` | `enforcement` | human |
| [`docs-maintenance`](docs-maintenance.md) | `audit` | `analysis` | human |
| [`eval`](eval.md) | `eval` | `analysis` | human |
| [`evaluate`](evaluate.md) | `eval` | `enforcement` | human |
| [`feat-remove`](feat-remove.md) | `build` | `state` | human |
| [`harness-audit`](harness-audit.md) | `audit` | `analysis` | human |
| [`hook-doctor`](hook-doctor.md) | `audit` | `enforcement` | model |
| [`inspect`](inspect.md) | `audit` | `analysis` | human |
| [`interview`](interview.md) | `design` | `enforcement` | human |
| [`lcs`](lcs.md) | `design` | `state` | model |
| [`llm-refresh`](llm-refresh.md) | `shortcuts` | `analysis` | human |
| [`log`](log.md) | `shortcuts` | `state` | human |
| [`plan`](plan.md) | `plan` | `state` | human |
| [`proposal`](proposal.md) | `design` | `state` | human |
| [`prune`](prune.md) | `build` | `analysis` | human |
| [`prune-propose`](prune-propose.md) | `audit` | `state` | human |
| [`refactor`](refactor.md) | `build` | `analysis` | human |
| [`repair`](repair.md) | `repair` | `state` | human |
| [`report`](report.md) | `audit` | `analysis` | human |
| [`research`](research.md) | `design` | `enforcement` | human |
| [`review`](review.md) | `review` | `analysis` | human |
| [`security`](security.md) | `security` | `enforcement` | human |
| [`ship`](ship.md) | `ship` | `state` | human |
| [`status`](status.md) | `status` | `state` | human |
| [`token-analyzer`](token-analyzer.md) | `audit` | `analysis` | human |
| [`valuate`](valuate.md) | `design` | `enforcement` | human |

Skill detail pages (`docs/skills/<name>.md`) are generated for user-facing
skills on a rolling basis; the per-skill row above links to the page when it
ships, and the frontmatter (`name:`, `description:`, `alpha:`,
`user-invocable:`) is the source of truth either way. Use the frontmatter
search below to see what's currently live.
