---
name: inspect
category: audit
description: 0-arg read-only code health audit. 8-dim fan-out (dead, dup, smell, overeng, overarch, cleancode, tokenbudget, slop) -> markdown report.
when_to_use: |
  - User types /dev-kit:inspect
  - Pre-release hygiene sweep
  - Periodic codebase health check
  - Pre-step for /dev-kit:refactor (baseline report) — refactor rewrites code
  - Pre-step for /dev-kit:prune (baseline report) — prune deletes slop/dead features
allowed-tools: Read Grep Glob Bash Agent
disallowed-tools: Write Edit
model: opus
user-invocable: true
---

# /dev-kit:inspect -- read-only code health audit

Whole-codebase health sweep across **8 dimensions in parallel**. Produces
one markdown report at `.dev-kit/inspect-report.md`. **Never edits.**
Distinct from `/dev-kit:review` (per-PR/diff), `/dev-kit:build-refactor`
(mutating 4-pass cleanup), and `/dev-kit:refactor` (3-phase wrap of
inspect + refactor + review). Use inspect to *find* problems, then
refactor (or `prune` for deletions) to *fix* them.

## Iron Law

**Read-only invariant.** No file modifications. The harness enforces
this via `disallowed-tools: Write Edit` in frontmatter; the verifier
pass below enforces it operationally by dropping any candidate that
would require an edit to validate.

## Step 1 -- Resolve scope

1. No positional arg (default) -> whole project directory.
2. `<path>` -> that subtree only.
3. `--dim <name>` -> restrict to one of `dead | dup | smell | overeng |
   overarch | cleancode | tokenbudget | slop`. Multiple `--dim` allowed.
4. Empty source set -> tell user, stop.

Filter: source files only. Skip `.git/`, `node_modules/`, `dist/`,
`__pycache__/`, `build/`, `target/`, lockfiles, generated `.pb.go`,
`.min.js`, `.min.css`. ~40+ files -> narrow with a positional arg.

## Step 2 -- Fan out (THE PARALLEL STEP)

> **Issue all 8 `Agent` calls inside ONE assistant message** so they run
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
  *Concrete patterns*: `grep -rE "^\s*#\s*(TODO|FIXME|XXX|HACK)" --include="*.py" --include="*.ts" --include="*.js"` (for date stamps); import-but-never-used (lint-clean baseline); `__all__` entries that no caller imports.
- **dup** -- copy-paste of >= 5 near-identical lines across 2+ files,
  parallel class hierarchies (A/B/C each with the same shape and one
  differing field), repeated test-setup blocks, repeated try/except
  boilerplate.
  *Concrete patterns*: 3+ functions with same shape and 1 differing field; identical test-fixture setup across files (no shared `conftest.py` / `setup.ts`); copy-pasted error-handler blocks (catch + log + rethrow same shape).
- **smell** -- long methods (>50 lines), long parameter lists (>4
  positional params), deep nesting (>4 levels), primitive obsession
  (loose dicts where a typed model would prevent bugs), feature envy
  (method that uses another class more than its own), data clumps (the
  same 3+ fields passed together through 3+ call sites).
  *Concrete patterns*: function body > 50 lines; function with > 4 positional params; `if/elif/else` chain > 4 levels deep; dict with same 3 keys threaded through 3+ functions.
- **overeng** -- interface with exactly one implementer that adds no
  indirection value, speculative parameters (declared but unused),
  premature generalization (Strategy/Factory/Builder for a single
  implementation), expensive operations in hot paths (N+1 queries,
  repeated full-list scans, per-request recompiles), missing caching
  on hot-path lookups, deep inheritance (>3 levels with no clear
  contract), 1-class-per-file without justification.
  *Concrete patterns*: `class IFoo(Protocol)` with one implementer; function arg with no in-body use; `if/elif type == "X"` chains that should be polymorphic; loop with inner `await`/DB call per item.
- **overarch** -- module-boundary leaks (subpackage reaches into parent's privates via `from .._internal import`), premature layering (DTO ↔ service ↔ repo for a single CRUD endpoint), parallel hierarchies (one new field forces 3+ sibling classes to grow in lockstep), leaky abstractions (caller must know the implementation detail to use the API correctly), bidirectional coupling (A imports B and B imports A in non-trivial ways), circular imports.
  *Concrete patterns*: `from .._impl import _private` (skipping the public surface); 3+ classes added in lockstep per new entity; 2 modules with mutual top-level imports; `Repository` exposed to the HTTP handler (skipping service).
- **cleancode** -- SRP/DRY/KISS/YAGNI violations with concrete evidence;
  vague names (`helper`, `util`, `manager`, `data`, `stuff` -- any of
  these in a public/exported symbol), bare `except:`, swallowed errors
  (`except: pass`), magic numbers without named constants, mutable
  default arguments, comparison to `True`/`None` with `==`.
  *Concrete patterns*: function named `do_stuff` / `handle_data` / `process` (no verb specificity); `except: pass` blocks; `if x == None` (use `is None`); `def f(items=[]):` (mutable default); bare HTTP status code `200` / `404` in handlers without named constant.
- **tokenbudget** -- per-file line count > 800 with low signal (comment
  blocks, repeated boilerplate, exported symbols with no external
  consumer), dead-comment blocks (>5 lines of commented-out code that
  has no archaeological value), export-count vs consumer-count skew
  (module exports 30+ public symbols but only 3 are imported by the
  rest of the codebase), large dead enums (enum class with > 20
  members, half of which are never referenced), parameterized-but-
  unused config (config key declared and read once at init, never
  propagated to the call site), verbose docstrings that restate the
  signature line-for-line.
  *Concrete patterns*: `git ls-files | xargs wc -l | sort -rn | head -20` for the long-tail; `pylint --disable=all --enable=unused-public-symbol` for export skew; `find . -name "*.py" -exec grep -c "^\s*#" {} \;` for high comment density.
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

| dim         | HIGH | MED | LOW |
|-------------|------|-----|-----|
| dead        |  ... | ... | ... |
| dup         |  ... | ... | ... |
| smell       |  ... | ... | ... |
| overeng     |  ... | ... | ... |
| overarch    |  ... | ... | ... |
| cleancode   |  ... | ... | ... |
| tokenbudget |  ... | ... | ... |
| slop        |  ... | ... | ... |

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

## Hand-off -- per-dimension routing

The report is the only artifact. Inspect itself does not fix anything.
Use this table to route each finding cluster to the right mutating
skill. Do not start a build cycle for MED/LOW alone.

| Dim         | Primary target                                  | Pass / phase           |
|-------------|--------------------------------------------------|------------------------|
| `dead`      | `build-refactor` pass 1 (DEAD CODE)             | `[1/4]`                |
| `dup`       | `build-refactor` pass 2 (DUPLICATION)            | `[2/4]`                |
| `smell`     | `build-refactor` pass 3 (NAMING) / refactor      | `[3/4]` + manual       |
| `overeng`   | `build-refactor` pass 3 (NAMING) / refactor-3    | `[3/4]`                |
| `overarch`  | `/dev-kit:plan` -> `/dev-kit:build` (PRD-shaped) | full cycle, not 4-pass |
| `cleancode` | `build-refactor` pass 3 (NAMING)                 | `[3/4]`                |
| `tokenbudget` | `build-refactor` pass 1 (DEAD CODE) + pass 3   | `[1/4] + [3/4]`        |
| `slop`      | `/dev-kit:prune` (deletion sweep) or `/dev-kit:audit --slop-only` | `[2/3]` PRUNE or out-of-band |

- **HIGH findings** -> feed the top items into `/dev-kit:plan` to scope
  a cleanup PRD (one phase per finding cluster), then `/dev-kit:build`
  to execute. Or fix the highest-severity items by hand and re-run
  `/dev-kit:inspect` to confirm the backlog shrunk.
- **MED/LOW**       -> logged in the report for the next sweep. Do not
  start a new build cycle for these alone.
- **Cross-check**    -> if the report is suspiciously empty on a project
  that has obvious smells, run `/dev-kit:audit` (fast, deterministic
  slop+secret scan) and `/dev-kit:security` (10-dim OWASP) to
  triangulate.
- **Whole-pipeline**  -> for "clean up everything" intent, run
  `/dev-kit:refactor` (3-phase wrap of inspect + refactor + review).
  This skill is its phase 1 (the baseline report).
- **Whole-pipeline deletion** -> for "remove slop / dead code" intent,
  run `/dev-kit:prune` (3-phase wrap of inspect + prune + review).
  Same baseline, different phase 2.

Next step: `/dev-kit:refactor` (whole-pipeline refactor), `/dev-kit:prune`
(whole-pipeline deletion), `/dev-kit:plan` (if HIGH > 0 and you want a
structured cleanup), or `/dev-kit:review` (per-PR check).

## Related

- `/dev-kit:refactor` is the 3-phase wrapper: this skill (baseline) ->
  `build-refactor` (4-pass cleanup) -> `review` (verify). Rewrites code.
- `/dev-kit:prune` is the 3-phase wrapper: this skill (baseline) ->
  its inlined Phase 2 (3-pass deletion sweep) -> `review` (verify). Deletes code.
- `/dev-kit:report` reads `.dev-kit/inspect-report.md` (this skill's
  output) and renders it as a self-contained HTML page alongside the
  eval report. Run report after inspect to share findings with
  non-technical reviewers.
- `/dev-kit:feat-remove` removes a single named feature end-to-end
  (call-graph sweep + deletion report) -- the targeted sibling of
  inspect's whole-codebase audit. Use when you know the feature name;
  use `/dev-kit:prune` for an automatic whole-project sweep.
