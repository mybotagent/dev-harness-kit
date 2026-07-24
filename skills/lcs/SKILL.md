---
name: lcs
category: design
description: Open LCS state in chat (lcs://worktrees, lcs://branches, lcs://pr, lcs://sessions, lcs://spend, lcs://hooks/coverage, lcs://interview, lcs://research/cache).
alpha: state
when_to_use:
  - User wants to see LCS state (worktrees, branches, sessions, spend, hooks)
  - Operator is debugging a hook and needs to verify which runtime the hook fires against
  - Reviewer wants to confirm a PR's CI status + slot version before approving
allowed-tools: Read Bash Grep
---
> [← Skills index](../../README.md)

# /dev-kit:lcs — Live Context Server viewer

## What it does

The `lcs` skill opens a single, read-only window onto the harness's live
state — every resource the Live Context Server (LCS) knows about, fetched
on demand with one CLI call. It replaces ad-hoc `git worktree list`,
`gh pr checks`, and per-bucket token queries with a uniform
`lcs://<resource>` namespace, so the operator can answer "what is the
repo doing right now?" from a single tool surface.

## Available resources

| URI | Description |
|---|---|
| `lcs://worktrees` | List every git worktree in the repo with branch + dirty status. |
| `lcs://worktrees/<branch>` | Detail one worktree (HEAD sha, slot version, last commit). |
| `lcs://branches/<name>` | Local + remote branches, ahead/behind counts, last-CI status. |
| `lcs://branches/<name>/slot` | Slot metadata for a branch (slot-id, runtime, last release). |
| `lcs://pr/<n>` | A single PR's CI checks, review verdict, merge state, slot version. |
| `lcs://sessions/<id>` | One recorded Claude / Codex session (turns, tools, tokens). |
| `lcs://spend/<window>` | Token spend over a time window, bucketed by model + worktree. |
| `lcs://hooks/coverage` | Which hook fires against which runtime (claude-code vs codex). |
| `lcs://interview/<step>` | Current state of the skill / plugin interview (step + answers). |
| `lcs://research/cache` | Research cache contents (queries, hits, freshness). |

## How it works

- The skill shells out to `bin/dev-kit-lcs.py` — the LCS CLI driver
  (Phase 1.2). It speaks JSON-RPC on stdio or one-shot `--get URI` for
  the chat surface; both reach the same resource registry.
- Each resource lives in `lib/lcs_resources/<name>.py` and implements
  the `Resource` protocol (`name`, `fetch(parsed) -> dict`). The CLI
  parses the URI, walks the registry by `name`, and prints the JSON
  payload. Unknown URIs return exit code 2.
- Read-only by design: no resource mutates disk or the network beyond
  `gh api` / `git` reads. Use `Bash` only via `bin/dev-kit-lcs.py`; do
  not pipe the JSON through `jq` / `python -c` reformatters — the
  registry shape is the contract.

## Usage

```bash
python3 bin/dev-kit-lcs.py --list-resources         # discover what is registered
python3 bin/dev-kit-lcs.py --describe worktrees     # one resource's shape
python3 bin/dev-kit-lcs.py --get lcs://worktrees    # fetch by URI (exit 0 = OK)
python3 bin/dev-kit-lcs.py --get lcs://pr/427       # one PR's CI + slot version
```

## Next step

- For PR review / babysit: hand off to `/dev-kit:babysit-pr` after
  inspecting `lcs://pr/<n>` and `lcs://hooks/coverage`.
- For build follow-ups: hand off to `/dev-kit:build` once the relevant
  resource (worktrees / spend / sessions) shows the gap to close.
