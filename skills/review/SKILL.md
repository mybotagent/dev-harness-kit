---
name: review
category: review
description: "Parallel multi-dimension code review with a false-positive filter. Fans out to per-dim experts (correctness, security, architecture) that run in parallel and return evidence-backed findings; a verifier pass confirms/rejects each candidate before rendering per-line inline comments plus a PR-style summary with a verdict."
when_to_use:
  - User types /dev-kit:review [paths] [--diff] [--diff --staged] [--fast]
  - User asks to review code, the diff, or the PR
  - Before merge — wants structured, severity-ranked, low-noise review
allowed-tools: Read Grep Glob Bash Agent
model: opus
disable-model-invocation: false
---

Multi-dim code review. Delegates to `lib.analysis_core.run_analysis(dimensions=group("review"), mode="read-only", paths=...)`. The engine owns the registry, evidence schema, FP filter, verifier, renderer. This skill owns the parallel Agent fan-out, the verifier call, and the inline + summary rendering.

## Scope

1. No paths -> whole project directory. `--diff` -> diff vs default branch. `--diff --staged` -> working-tree changes only. `--fast` -> skip verifier.
2. Filter to source files. Empty -> tell user, stop. >~40 files -> narrow subset.
3. On diff run, capture `git diff -U0`. Experts must only flag issues introduced by the changed lines, not pre-existing code.

## Fan-out + verify

Issue all Agent calls inside ONE assistant message so they run concurrently. Each: `subagent_type: "general-purpose"`, `model: "sonnet"`. Pass each expert its charter from `lib.analysis_core.dimensions` + the shared contract (`file, line, severity, confidence, failure_scenario, title, tldr, good, fix`). Return a fenced `json` array.

**Dimensions:** correctness, security, architecture (see `group("review")`).

One verifier Agent (`general-purpose`, `model: "sonnet"`) returns `[{id, verdict: CONFIRMED|PLAUSIBLE|REJECTED, reason}]`. Drop REJECTED; keep CONFIRMED + PLAUSIBLE. Skipped with `--fast`.

## Render

**Layer 2 (one PR summary at top):** `## Review summary` with verdict (`Blocked`/`Changes Requested`/`Approve`), severity counts, walkthrough, strengths, blocking findings, next actions. Verdict: Blocked (>=1 critical) -> Changes Requested (>=1 major) -> Approve.

**Layer 1 (inline, one per finding):** Call `mcp__github_inline_comment__create_inline_comment` with `path`, `line`, `body` shaped `[<severity> · <verdict>] <title> @ path:line (dim: ...) / TL;DR: ... / ✓ Good: ... / Fix: <snippet>`. Skip when 0 findings (clean Approve).

## Hooks

`slop-detector, secret-scan, stop-verify` ON. `tdd-guard` OFF (review stage).

Next: `/dev-kit:security` (10-dim OWASP) or `/dev-kit:ship`.
