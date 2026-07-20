---
name: inspect
category: audit
description: 0-arg read-only code health audit. 8-dim fan-out (dead, dup, smell, overeng, overarch, cleancode, tokenbudget, slop) -> markdown report.
alpha: analysis
when_to_use:
  - User types /dev-kit:inspect
  - Pre-release hygiene sweep
  - Pre-step for /dev-kit:refactor or /dev-kit:prune (baseline report)
allowed-tools: Read Grep Glob Bash Agent
disallowed-tools: Write Edit
model: opus
user-invocable: true
---

Read-only whole-codebase health sweep. Delegates to `lib.analysis_core.run_analysis(dimensions=group("inspect"), mode="read-only", paths=...)`. Engine owns registry, evidence schema, FP filter, verifier, renderer; this skill owns the parallel Agent fan-out and the markdown wrapper. **Iron Law.** Read-only. `disallowed-tools: Write Edit`.

## Scope

1. No positional arg -> whole project. `<path>` -> that subtree.
2. `--dim <name>` -> one of `dead | dup | smell | overeng | overarch | cleancode | tokenbudget | slop`.
3. Empty source set -> tell user, stop. >~40 files -> narrow with positional arg.
4. Skip `.git/`, `node_modules/`, `dist/`, lockfiles, generated `.pb.go`/`.min.js`/`.min.css`.

## Fan-out + verify

Issue all Agent calls inside ONE assistant message so they run concurrently. Each: `subagent_type: "general-purpose"`, `model: "sonnet"`. Pass each expert its charter from `lib.analysis_core.dimensions` + the shared contract (`file, line, severity, confidence, failure_scenario, title, tldr, fix_hint`). Return a fenced `json` array. One verifier Agent returns `[{id, verdict: CONFIRMED|PLAUSIBLE|REJECTED, reason}]`; REJECTED are dropped.

The dedupe (on `file,line,theme`) + verifier + synthesize pipeline routes through `tools/parallel_dispatch.py:fanout_and_synthesize` (issue #177). The skill body still issues the Agent calls; the helper owns the post-fan-out pipeline.

## Dimensions (charters live in `lib/analysis_core/dimensions.py`)

- **dead** — unused exports, unreachable branches, commented-out blocks (>3 lines), orphan config keys.
- **dup** — copy-paste of >= 5 near-identical lines across 2+ files, parallel class hierarchies.
- **smell** — long methods (>50 lines), long param lists (>4), deep nesting (>4), data clumps.
- **overeng** — interface with one implementer, speculative params, premature generalization, hot-path N+1.
- **overarch** — module-boundary leaks, premature layering, parallel hierarchies, circular imports.
- **cleancode** — SRP/DRY/KISS/YAGNI with evidence; vague names; bare except: pass; magic numbers.
- **tokenbudget** — file > 800 lines with low signal, dead-comment blocks, export/consumer skew.
- **slop** — dead else branches, hallucinated API calls, over-defensive try/except, AI-tell phrasing.

## Render

Append engine's markdown to `.dev-kit/inspect-report.md`. No PR comments, no source edits. Verdict: `Critical` (>=1 HIGH) | `Major drift` (>=3 MED) | `Minor drift` | `Healthy`.

## Hand-off

| Dim | Target | Pass |
|---|---|---|
| dead | build-refactor | [1/4] |
| dup | build-refactor | [2/4] |
| smell | build-refactor | [3/4] |
| overeng | build-refactor | [3/4] |
| overarch | /dev-kit:plan -> build | full cycle |
| cleancode | build-refactor | [3/4] |
| tokenbudget | build-refactor | [1/4]+[3/4] |
| slop | /dev-kit:prune | deletion sweep |

Next: `/dev-kit:refactor` (rewrite), `/dev-kit:prune` (delete), `/dev-kit:plan` (HIGH > 0), `/dev-kit:review` (per-PR).
