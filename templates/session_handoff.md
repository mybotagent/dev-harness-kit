# Session handoff checklist — <task name>

> Resume-from-cold-context checklist. Pattern 2 from
> `docs/proposals/playbook-application/02-reanalysis.yaml`. Run this
> top-to-bottom at the start of every new session to recover the
> minimum context needed to continue without re-deriving it.

## 0. Confirm you are on the right branch + worktree

```bash
git rev-parse --abbrev-ref HEAD          # must show <branch>
git rev-parse --show-toplevel           # must be the worktree root
git worktree list                       # cross-check no duplicates
```

If the branch name is wrong, STOP — do not start work in the wrong
worktree. Switch via `git worktree add` or open a fresh worktree
following `rules/git-workflow.md`.

## 1. Read the previous session's exit state

Required reads, in order:

1. `templates/progress.log.md` — last `## Session N` section.
   Capture: Goal, Tests status, Blockers, Next session should.
2. `.session-next-feature` — single-line id of the next failing feature.
3. `.session-baseline.json.baseline` — last pytest output (used to
   diff against today's run; if today regresses, diff this first).

If any of these are missing, the previous session did not run
`templates/init.sh` to completion — re-run it now.

## 2. Verify the environment

Run `templates/init.sh` (idempotent). It will:

- Re-verify `feature_list.json` parses.
- Pick the same next-failing-feature id (deterministic by id order).
- Refresh `.session-baseline.json.baseline`.

If `init.sh` exits `3`, every feature is green and the task is done —
open the PR / hand off to review.

## 3. Verify the test suite is still green at HEAD

```bash
python3 -m pytest -q
```

Compare against `.session-baseline.json.baseline`. Any new failure is a
regression in this branch; diff against the previous session's last
green state before touching source.

## 4. State the goal of THIS session, out loud

Before any code change, write one sentence:

> "This session will <single concrete outcome>, measured by <single
> observable signal>."

If you cannot phrase that in one sentence, the session is too
scoped — split it into two sessions and update
`progress.log.md` accordingly.

## 5. Work, in scope

Stay within `.session-next-feature`. If the work reveals a second
feature that must precede this one, STOP, update `feature_list.json`
(insert a new `failing` entry, point `depends_on` at it), then
re-run `init.sh`.

## 6. Before ending the session — append to progress.log.md

Mandatory append (do not skip):

- New `## Session N+1 — <UTC date>` section.
- Fill **every** subsection: Goal, Work done, Tests status, Blockers,
  Next session should, Commits.
- Paste last 5 lines of pytest output verbatim under Tests status.
- Commit the progress log alongside your code change.

## 7. Push + sync

```bash
git add -A
git commit -m "<type>(<scope>): <subject>"
git push -u origin <branch>
python3 tools/linear_sync.py             # no-op if Linear not configured
```

## 8. Hand-off record

Write `.dev-kit/hand-off/build→next-session.md` with:

- Branch + last commit SHA.
- Next feature id (same as `.session-next-feature`).
- Open blockers (or "none").
- Operator-readable one-liner: "Next session should <...>".

This file is what the cold-start agent reads FIRST, before
`progress.log.md`.

## Anti-patterns — STOP if you find yourself doing any of these

- Skipping a session without first reading `progress.log.md`.
- Editing prior progress entries instead of appending a new section.
- Picking a feature whose `depends_on` is not fully `passing`.
- Committing without running `pytest` first.
- Skipping the hand-off record because "the PR description covers it".
- Switching branches mid-session without updating the handoff file.
