> [← Skills index](README.md) · [Project README](../../README.md)

# `lcs`

**Category:** `design` · **Alpha:** `state` · **Invocation:** auto (model-invoked)

`lcs` opens the Live Context Server's read-only URI surface (`lcs://<resource>`) — every production resource registered by LCS, fetched on demand with one CLI call. It replaces ad-hoc `git worktree list`, `gh pr checks`, and per-bucket token queries with a uniform namespace, so the operator can answer "what is the repo doing right now?" from a single tool surface. Source: [`skills/lcs/SKILL.md`](../../skills/lcs/SKILL.md).

## When to use it

- The model needs to inspect LCS state (worktrees, branches, sessions, spend) during a parent skill's flow.
- An operator is debugging a hook and needs to verify which runtime the hook fires against.
- A reviewer wants to confirm a PR's CI status and slot version before approving.

## Resource URI contract

The default `bin/dev-kit-lcs.py` registry exposes the production handlers (`worktrees`, `branches`, `pr`, `sessions`, `spend`, and a growing set of Phase 1.x additions). Hooks consult `lcs://branches/<name>` and `lcs://worktrees` instead of shelling out to `git` directly.
