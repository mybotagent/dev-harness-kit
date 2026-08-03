---
name: linear
category: config
description: Optional Linear task tracker. Reconcile the current repository task with a canonical project and non-duplicate issue. Auto-syncs on every Claude Code edit when configured.
alpha: state
when_to_use: |
  - User types /dev-kit:linear
  - User types /dev-kit:linear on | off | status | setup | project-name <name>
  - A workflow skill starts a new implementation, debugging, refactor, or plan task
  - The user asks to register, reconcile, or update work in Linear
  - Every Edit|Write|MultiEdit fires the auto-sync hook (when configured)
allowed-tools: Read Write Bash Glob
model: sonnet
disable-model-invocation: false
user-invocable: true
---
> [← Skills index](../README.md)

## What it does

`linear` is an optional task-tracking skill. It can be invoked directly by a user, called once by a workflow skill at task start, or fired automatically on every Edit|Write when Linear is configured. The skill itself describes the reconciliation contract; the actual sync is implemented by `tools/linear_sync.py` and invoked through `hooks/linear-autosync.sh`. The skill never treats an existing handoff as proof of registration, and it never blocks normal work when Linear is unavailable.

## Optional capability

Resolve the current repository name and the user's Linear capability before making a request.

- If this is an implicit workflow call and Linear is disabled or unavailable, return `LINEAR_SKIP` and let the caller continue.
- If this is an explicit `/dev-kit:linear` call and Linear is unavailable, report the missing connection/setup clearly; do not pretend the task was registered.
- If `.dev-kit/.enabled.json` exists, respect its Linear/MCP selection. Missing configuration means `auto`, not a hard failure.
- Do not invoke Linear for read-only work such as inspect, review, security, or code-viz unless the user explicitly requests registration.

## Auto-sync trigger (every Edit|Write)

When Linear is configured (`LINEAR_API_KEY` env var OR per-worktree `.dev-kit/linear-config.json:enabled` OR legacy `.dev-kit/.enabled.json:mcp.linear` ∈ {`auto`, `on`}), `hooks/linear-autosync.sh` runs `tools/linear_sync.py` before every Edit|Write|MultiEdit. The script:

1. Resolves the task description in priority order: the active hand-off's `prompt` field → the latest commit subject on the current branch → the branch name. The hand-off is keyed by worktree slug, so two parallel sessions in two worktrees never share or overwrite each other's state.
2. Skips read-only / non-task prompts (`/`, `#`, `!`, `ls `, `cat `, `grep `, `git status`, and prompts that lack a work verb).
3. Finds or creates the project named after the configured project-name (per-worktree override) or the repository basename.
4. Searches for an open issue whose `description` starts with `<!-- scope:<branch>::<prompt-head> -->`.
5. Updates the existing issue OR creates a new one with the same scope marker.
6. Writes the updated handoff at `.dev-kit/hand-off/linear/<worktree-slug>.json` so the next edit reuses the same issue.

The script always returns exit code 0. Transport errors, missing tokens, and GraphQL failures are logged to stderr and never block the edit (per #539: "Linear failures are non-blocking for implicit workflow calls."). Users without Linear configured are unaffected — the hook fast-paths on missing env var and config. Set `LINEAR_DEBUG=1` to surface every skip reason on stderr.

## Per-worktree CLI

`/dev-kit:linear` accepts subcommands. Each one delegates to `tools/linear_sync.py`, which is the authoritative implementation. The skill exists so the user does not have to remember the script path; the script exists so the hook, the skill, and any future caller share one code path.

| Subcommand | Effect |
|---|---|
| `/dev-kit:linear` (no args) | Run one auto-sync round (re-evaluates the current task and creates/updates the matching Linear issue). |
| `/dev-kit:linear on` | Enable auto-sync in this worktree. Writes `enabled: true` to `<worktree>/.dev-kit/linear-config.json`. |
| `/dev-kit:linear off` | Disable auto-sync in this worktree. Writes `enabled: false`. Project name and team id are preserved. |
| `/dev-kit:linear setup` | Print the one-time setup checklist + the current state (whether `LINEAR_API_KEY` is set, what the resolved project name is, whether the worktree config exists). |
| `/dev-kit:linear project-name <name>` | Override the auto-detected project name for this worktree. Without an argument, prints the resolved name. |
| `/dev-kit:linear status` | Print a JSON snapshot of the resolved state (worktree path, slug, config, env-var presence, resolved project + team). |

The skill must invoke the CLI rather than replicate its logic. The standard pattern for each subcommand is:

```bash
python3 tools/linear_sync.py <subcommand> [args...]
```

The CLI writes the config at `<repo>/.dev-kit/linear-config.json` (untracked) and the handoff at `<repo>/.dev-kit/hand-off/linear/<worktree-slug>.json`. The API key is **never** read from or written to disk; set it once in your shell environment (e.g. `export LINEAR_API_KEY=...` in `~/.zshrc`).

### Setup (one-time, per machine)

Two equivalent ways to provide `LINEAR_API_KEY`. Pick one.

**Option A — shell env (recommended for shared machines):**

```bash
export LINEAR_API_KEY=<your-linear-api-token>     # https://linear.app/settings/api
cd .worktrees/<your-worktree>
python3 tools/linear_sync.py on
python3 tools/linear_sync.py project-name "<name>"    # optional
```

**Option B — per-worktree env file (recommended for solo dev):**

The script also reads `.dev-kit/.env.linear` (untracked, `.gitignore`'d) as a fallback when `LINEAR_API_KEY` is not in the shell env. Shell env always wins; the file only fills in missing values.

```bash
# .dev-kit/.env.linear (you create this yourself — never committed)
LINEAR_API_KEY=<your-linear-api-token>
# LINEAR_TEAM_ID=...    # optional
# LINEAR_PROJECT_NAME=...   # optional override
```

Lines starting with `#` are comments. Values may be quoted (`"..."` or `'...'`); trailing `# comment` is stripped. Then:

```bash
cd .worktrees/<your-worktree>
python3 tools/linear_sync.py on
python3 tools/linear_sync.py project-name "<name>"    # optional
```

Run `python3 tools/linear_sync.py setup` to print both checklists and the current state.

Or, equivalently, through the skill:

```
/dev-kit:linear on
/dev-kit:linear project-name "My Project"
```

### Config file shape

```json
{
  "enabled": true,
  "project_name": "My Linear Project",
  "team_id": "",
  "set_at": "2026-08-03T00:54:03Z"
}
```

### Why per-worktree?

Each worktree represents a different task, branch, and Linear scope. Storing the config under `<worktree>/.dev-kit/` means parallel Claude Code sessions in different worktrees each get their own enabled flag, their own project-name override, and their own hand-off state under `.dev-kit/hand-off/linear/<slug>.json` — no cross-talk, no shared mutable state.

### State priority (Linear API > hand-off file)

The hand-off file is a *cache*, not a source of truth. The priority order is:

1. **Linear API** — every sync round issues `_find_issue(projectId, scope)` which lists the project's open issues and matches by the `<!-- scope:<branch>::<prompt-head> -->` prefix. This is the only mechanism that decides "reuse vs. create."
2. **Hand-off file** — `<worktree>/.dev-kit/hand-off/linear/<slug>.json` is consulted only to:
   - carry the previous prompt across sessions when the hook fires on a brand-new task
   - fall back to a human-readable identifier (`SHO-151`) when the API returns a bare uuid
   - record the resolution timestamp and the action taken

   The file ships with a `_meta` block declaring its priority and its source of truth:

   ```json
   {
     "_meta": {
       "priority": 2,
       "kind": "cache",
       "source_of_truth": "linear_api",
       "written_by": "tools/linear_sync.py"
     },
     "issue": "SHO-151 (d81ee2dd-...)",
     "project": "dev-harness-kit",
     ...
   }
   ```

A stale or wrong issue id in the hand-off file can never cause a duplicate or a wrong-target update — the next sync round always re-validates against the API and overwrites the file with the authoritative result.

## Reconciliation workflow

1. Read the current repository, branch/worktree, task request, and any existing handoff as context.
2. List or search the user's Linear teams and projects. Use the canonical repository name as the project name.
3. If that project does not exist, create it in the selected team. Do not silently substitute a similarly named project.
4. Search open and recently updated issues in that project using the current task's concrete scope and keywords.
5. Reuse an issue only when its scope and intended outcome match the current task. A present, old, closed, or unrelated handoff is not sufficient evidence.
6. Create a new issue when no matching issue exists or when an old issue represents a different task. Use the appropriate Feature, Improvement, or Bug label when available.
7. Set a newly started issue to `Todo` or `In Progress` according to the caller's stage. Preserve existing status when merely reconciling.
8. Write a small handoff record only after the Linear result is known. The record is a resume hint, not an authorization gate.

## Workflow callers

When called by `plan`, `build`, `build-debug`, or `refactor`, perform this workflow once at the start of that skill and return a compact result:

```text
LINEAR_OK: project=<name> issue=<identifier> action=<reused|created> status=<state>
LINEAR_SKIP: reason=<disabled|not-connected|not-configured>
LINEAR_ERROR: reason=<actionable failure>; continue=<yes for implicit calls>
```

The caller must continue on `LINEAR_SKIP` and implicit `LINEAR_ERROR`. It must not duplicate Linear calls inside loops, phases, retries, or every user prompt.

## Handoff and PR linking

Use `.dev-kit/hand-off/linear.json` when the repository has a handoff directory. Replace the current task entry when the task changes; do not use file age or presence as a gate. Include the project, issue identifier, task summary, registration action, and timestamp.

When a PR exists, add its URL to the matching issue and update the issue status only when the caller explicitly owns that transition. Never create a second issue solely because a PR already exists.

## Next step

After direct reconciliation, continue with the requested workflow, usually `/dev-kit:plan`, `/dev-kit:build`, `/dev-kit:build-debug`, or `/dev-kit:refactor`.
