# Plan: <topic>

> Phase 2 of the research → plan → implement pipeline.
> Source: `templates/plan.md`. Consumed by `skills/research-plan-build/SKILL.md`.
> Predecessor: `templates/research.md`. Successor: implement phase
> (`/dev-kit:build` for harnessed steps).

## Goal

One sentence. The Goal here must match the Question-Verdict in
`research.md`; if they diverge, return to research.

```
goal: <single sentence>
acceptance_metric: <the single number that moves if this works>
out_of_scope: <what we explicitly will not change>
```

## Steps

Each plan step maps to ONE BUILD RUN. The build runner emits the
canonical 2-commit protocol (`feat(...)` then `chore(...)`) per step
on the feature branch - see `lib/execute.py:_run_sequential`. `plan.md`
is the human-readable companion to `phases/<name>/index.json` +
`step<N>.md`; the build runner consumes the phases artifacts, not
`plan.md`.

| # | Step | Owner | Acceptance | Dependencies |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |

### Step detail (one block per step)

```
step: N
name: <slug>
owner: <agent or human role>
acceptance:
  - <observable behavior 1>
  - <observable behavior 2>
dependencies:
  - <step # or external contract>
estimated_complexity: low | medium | high
verification:
  - <test name or command>
  - <test name or command>
files_touched:
  - <path>
  - <path>
```

Add one `### Step detail` block per row in the table above.

## Commit protocol

The build runner (`lib/execute.py:_run_sequential`) emits the canonical
2-commit protocol per step on the feature branch. `plan.md` does NOT
override this; it is the human-readable companion.

```text
feat(<scope>): step N — <name>

Implements plan.md step N (<topic>).
- Acceptance: <paste acceptance criteria>
- Verification: <test command + exit code>
- Files: <list>

chore(<scope>): step N output

Writes phases/<name>/step<N>-output.json (real subprocess exit code,
stdout, stderr, duration_seconds).
```

The build runner enforces this contract - `plan.md` describes what the
reviewer should see, not what the runner emits. A reviewer reading the
commit log can cross-walk each `feat(...)` to its `plan.md` step row
via the step number in the body.

## Risks

A short list of the things that could derail the plan, with the
mitigation the implement phase should run if the risk fires.

| Risk | Trigger | Mitigation |
|---|---|---|
| | | |

## Hand-off

`/dev-kit:build` (or `/dev-kit:build-tdd` when methodology=tdd) for the
implement phase. The build runner reads `phases/<name>/step<N>.md` for
step content; this `plan.md` is the human-readable companion that the
reviewer reads alongside the per-step commits.

## Next step

Hand off to the implement phase via `/dev-kit:build`. The research → plan →
implement chain is complete when every row in the Steps table above has
(a) a matching `phases/<name>/step<N>.md` emitted by `/dev-kit:plan`,
(b) the runner's 2-commit protocol on the feature branch, and
(c) verification commands in `### Step detail` that exit 0.
