> [← Skills index](README.md) · [Project README](../../README.md)

# `review`

**Category:** `review` · **Alpha:** `analysis` · **Invocation:** `/dev-kit:review [paths] [--diff] [--diff --staged] [--fast]` (human-invoked)

`review` is a parallel multi-dimension code review with a false-positive filter: it fans out to per-dimension experts (correctness, security, architecture) that run concurrently, then a verifier pass confirms or rejects each candidate finding before the skill renders per-line inline comments plus a PR-style summary with a verdict. It delegates to the shared `lib.analysis_core.run_analysis(dimensions=group("review"), mode="read-only", paths=...)` engine, which owns the registry, evidence schema, false-positive filter, verifier, and renderer; the skill itself owns the parallel `Agent` fan-out, the verifier call, and the inline-plus-summary rendering.

## When to use it

- The user types `/dev-kit:review [paths] [--diff] [--diff --staged] [--fast]`.
- The user asks to review code, the diff, or the PR.
- Before merge, when a structured, severity-ranked, low-noise review is wanted.

## How it works

**Scope.** No paths given → the whole project directory. `--diff` → diff against the default branch. `--diff --staged` → working-tree changes only. `--fast` → skips the verifier pass. Files are filtered to source files; an empty result tells the user and stops; more than ~40 files narrows to a subset. On a diff run, the skill captures `git diff -U0` and instructs experts to flag only issues introduced by the changed lines, not pre-existing code.

**Fan-out + verify.** All `Agent` calls are issued inside one assistant message so they run concurrently. Each uses `subagent_type: "general-purpose"` and `model: "sonnet"`, and each expert receives its charter from `lib.analysis_core.dimensions` plus the shared evidence contract (`file, line, severity, confidence, failure_scenario, title, tldr, good, fix`), returning a fenced `json` array. The three review dimensions are **correctness, security, architecture** (`group("review")`). One verifier `Agent` (also `general-purpose` / `sonnet`) returns `[{id, verdict: CONFIRMED|PLAUSIBLE|REJECTED, reason}]`; `REJECTED` findings are dropped, `CONFIRMED` and `PLAUSIBLE` are kept. The verifier pass is skipped entirely with `--fast`.

**Render.** Layer 2 is a single PR summary at the top: `## Review summary` with a verdict, severity counts, a walkthrough, strengths, blocking findings, and next actions. The verdict escalates from Approve → Changes Requested (≥1 major finding) → Blocked (≥1 critical finding). Layer 1 is one inline comment per finding, via `mcp__github_inline_comment__create_inline_comment`, shaped as `[<severity> · <verdict>] <title> @ path:line (dim: ...) / TL;DR: ... / ✓ Good: ... / Fix: <snippet>`. With 0 findings, no inline comments are posted (a clean Approve).

## Usage

```bash
/dev-kit:review [paths] [--diff] [--diff --staged] [--fast]
```

| Flag | Effect |
|---|---|
| *(no paths)* | Reviews the whole project directory. |
| `<paths>` | Narrows the review to the given paths. |
| `--diff` | Reviews the diff against the default branch. |
| `--diff --staged` | Reviews only staged working-tree changes. |
| `--fast` | Skips the verifier pass. |

## Output

A `## Review summary` block (verdict + severity counts + walkthrough + strengths + blocking findings + next actions) plus one inline comment per confirmed/plausible finding.

## Related

- [security](security.md) — the 10-dimension OWASP counterpart, run separately for deeper security focus.
- `/dev-kit:ship` — the next step once the review verdict is Approve.
- `lib.analysis_core` — the shared engine (registry, evidence schema, FP filter, verifier, renderer) this skill delegates to.

## Hooks

`slop-detector`, `secret-scan`, `stop-verify` are ON during this stage; `tdd-guard` is OFF (review is a read-only stage, not test authoring).

---
*Source: [`skills/review/SKILL.md`](../../skills/review/SKILL.md)*
