---
name: inspect
category: audit
description: 0-arg read-only code health audit. 6-dim fan-out (dead, dup, smell, over-eng, clean-code, slop) -> markdown report.
when_to_use: |
  - User types /dev-kit:inspect
  - Pre-release hygiene sweep
  - Periodic codebase health check
allowed-tools: Read Grep Glob Bash Agent
disallowed-tools: Write Edit
model: opus
user-invocable: true
---

# /dev-kit:inspect -- read-only code health audit

Whole-codebase health sweep across **6 dimensions in parallel**. Produces
one markdown report at `.dev-kit/inspect-report.md`. **Never edits.**
Distinct from `/dev-kit:review` (per-PR/diff) and `/dev-kit:build-simplify`
(mutating 4-pass cleanup). Use inspect to *find* problems, then simplify
to *fix* them.

## Iron Law

**Read-only invariant.** No file modifications. The harness enforces
this via `disallowed-tools: Write Edit` in frontmatter; the verifier
pass below enforces it operationally by dropping any candidate that
would require an edit to validate.

## Step 1 -- Resolve scope

1. No positional arg (default) -> whole project directory.
2. `<path>` -> that subtree only.
3. `--dim <name>` -> restrict to one of `dead | dup | smell | overeng |
   cleancode | slop`. Multiple `--dim` allowed.
4. Empty source set -> tell user, stop.

Filter: source files only. Skip `.git/`, `node_modules/`, `dist/`,
`__pycache__/`, `build/`, `target/`, lockfiles, generated `.pb.go`,
`.min.js`, `.min.css`. ~40+ files -> narrow with a positional arg.

## Step 2 -- Fan out (THE PARALLEL STEP)

> **Issue all 6 `Agent` calls inside ONE assistant message** so they run
> concurrently. Separate messages run sequentially and defeat the
> purpose.

Each call: `subagent_type: "general-purpose"`, `model: "sonnet"`,
`run_in_background: false`.

### Shared contract (prepend to every expert prompt)

```
You are a code-health expert for ONE dimension: <DIMENSION>. Read each
file and report ONLY real, demonstrable issues in your dimension.
Precision matters more than completeness -- a false positive is worse
than a missed nit.

Files to inspect (read each one):
<file list, absolute paths>

MANDATORY per finding:
- failure_scenario: a CONCRETE trigger -- specific inputs/state that
  lead to a real problem (latent bug, maintenance trap, security gap,
  runtime cost, or misleading-reader). If you cannot write one, the
  issue is speculative -> DROP.
- confidence: high | medium | low -- your certainty the issue is real
  AND reaches production readers/maintainers.

DO NOT report:
- Style, naming, or formatting preferences with no functional impact.
- Hypothetical issues with no reachable trigger.
- "Missing" validation when a visible guard, type, or caller covers it.
- Defensive-programming suggestions that are not a real defect.
- Anything outside your dimension.
- A weaker restatement of a more fundamental issue you are also
  reporting.

Severity: critical (data loss / exploitable / silent correctness break
  -> blocks release) | major (real defect, real cleanup backlog) |
  minor (non-blocking improvement) | nit (trivial).

Return ONLY a fenced ```json array:
[{
  "file": "<absolute path>",
  "line": <1-indexed anchor int>,
  "dim": "<DIMENSION>",
  "severity": "critical|major|minor|nit",
  "confidence": "high|medium|low",
  "title": "<short imperative title>",
  "tldr": "<one line: what's wrong and why it matters>",
  "failure_scenario": "<concrete inputs/state -> problem>",
  "fix_hint": "<one-line fix recommendation>"
}]
Return [] if you find nothing real. Prefer 2 solid findings over 8
speculative ones.
```

### Dimension charters

- **dead** -- unused exports, unreachable branches after a return,
  commented-out code blocks (>3 lines), orphan config keys (YAML/JSON
  keys no code reads), dead env vars (declared but never referenced),
  TODO/FIXME > 90 days old with no tracking issue.
- **dup** -- copy-paste of >= 5 near-identical lines across 2+ files,
  parallel class hierarchies (A/B/C each with the same shape and one
  differing field), repeated test-setup blocks, repeated try/except
  boilerplate.
- **smell** -- long methods (>50 lines), long parameter lists (>4
  positional params), deep nesting (>4 levels), primitive obsession
  (loose dicts where a typed model would prevent bugs), feature envy
  (method that uses another class more than its own), data clumps (the
  same 3+ fields passed together through 3+ call sites).
- **overeng** -- interface with exactly one implementer that adds no
  indirection value, speculative parameters (declared but unused),
  premature generalization (Strategy/Factory/Builder for a single
  implementation), expensive operations in hot paths (N+1 queries,
  repeated full-list scans, per-request recompiles), missing caching
  on hot-path lookups, deep inheritance (>3 levels with no clear
  contract), 1-class-per-file without justification.
- **cleancode** -- SRP/DRY/KISS/YAGNI violations with concrete evidence;
  vague names (`helper`, `util`, `manager`, `data`, `stuff` -- any of
  these in a public/exported symbol), bare `except:`, swallowed errors
  (`except: pass`), magic numbers without named constants, mutable
  default arguments, comparison to `True`/`None` with `==`.
- **slop** -- semantic AI slop: dead `else` branches after `return`,
  hallucinated API calls (lib/function not in the project's declared
  dependencies), over-defensive `try/except Exception: pass` around
  already-safe code, no-op interfaces that wrap a single concrete
  class, verbose docstrings that restate the signature, AI-tell
  phrasing (`"Let's dive into"`, `"It's worth noting"`, `"In
  conclusion"`, `"delve into"` -- phrase-level banned phrases still
  belong to `/dev-kit:audit`; this dim catches semantic analogues).

## Step 3 -- Verify (false-positive filter)

Parse each expert's JSON array.

### 3a. Deterministic filter

Drop if:
- Missing or empty `failure_scenario`.
- `confidence: low` AND severity is `minor` or `nit`.
- Anchor line is outside the inspected file list (paranoia check).

### 3b. Dedupe

Same `file + line + dim` -> keep highest severity.
Cross-dimension root cause -> collapse to one finding at the root dim.

### 3c. Verifier pass

Spawn one verifier subagent (`general-purpose`, `model: "sonnet"`).
Give it the surviving candidates + the file list. Prompt:

```
You are a strict verifier. RE-READ the cited code and decide if each
candidate is REAL. Try hard to REFUTE. Return only:
[{ "id": <index>, "verdict": "CONFIRMED|PLAUSIBLE|REJECTED",
   "reason": "<one line>" }]
- CONFIRMED: the failure_scenario you re-read is real and reachable.
- PLAUSIBLE: likely real but cannot fully confirm from the given scope.
- REJECTED: the code already handles it, or the scenario does not
  trigger, or the candidate is speculative.
```

Drop every REJECTED. Keep CONFIRMED + PLAUSIBLE.

### 3d. Sort

By severity (critical -> nit), CONFIRMED before PLAUSIBLE, then file,
then line.

## Step 4 -- Render

Write the report to **`.dev-kit/inspect-report.md`** (the only artifact).
Do NOT post PR comments, do NOT edit source. Format:

```markdown
# Code Health Inspection -- {ISO date} -- {scope}

**Verdict:** <Critical | Major drift | Minor drift | Healthy>
**Coverage:** {N} files inspected -- {K} findings ({H} HIGH, {M} MED,
{L} LOW)
**Precision:** {K} verified -- {K} filtered as false positive

## HIGH ({N})

- [HIGH | CONFIRMED] <title> -- path:line
  Dim: <dim> -- Confidence: <high|medium>
  TL;DR: <one line>
  Scenario: <failure scenario>
  Fix: <fix_hint>

(remaining HIGH findings, one bullet block each)

## MED ({N})

(same shape)

## LOW ({N})

(same shape)

## Per-dimension summary

| dim       | HIGH | MED | LOW |
|-----------|------|-----|-----|
| dead      |  ... | ... | ... |
| dup       |  ... | ... | ... |
| smell     |  ... | ... | ... |
| overeng   |  ... | ... | ... |
| cleancode |  ... | ... | ... |
| slop      |  ... | ... | ... |

## Notes

- <1-line caveat about scope (e.g., "scoped to src/; build/, dist/
  excluded")>
- <1-line note if any dim returned 0 findings>
```

Verdict rules:
- `Critical`     -- >= 1 HIGH
- `Major drift`  -- 0 HIGH AND >= 3 MED
- `Minor drift`  -- 0 HIGH AND 0~2 MED AND >= 1 LOW
- `Healthy`      -- 0 findings

## Hand-off

The report is the only artifact. Inspect itself does not fix anything.

- **HIGH findings** -> feed the top items into `/dev-kit:plan` to scope a
  cleanup PRD (one phase per finding cluster), then `/dev-kit:build` to
  execute the 4-pass cleanup. Or fix the highest-severity items by
  hand and re-run `/dev-kit:inspect` to confirm the backlog shrunk.
- **MED/LOW**       -> logged in the report for the next sweep. Do not
  start a new build cycle for these alone.
- **Cross-check**    -> if the report is suspiciously empty on a project
  that has obvious smells, run `/dev-kit:audit` (fast, deterministic
  slop+secret scan) and `/dev-kit:security` (10-dim OWASP) to
  triangulate.

Next step: `/dev-kit:plan` (if HIGH > 0 and you want a structured
cleanup) or `/dev-kit:review` (if you want a per-PR check on changes
you make).

## Related

- `/dev-kit:report` reads `.dev-kit/inspect-report.md` (this skill's
  output) and renders it as a self-contained HTML page alongside the
  eval report. Run report after inspect to share findings with
  non-technical reviewers.