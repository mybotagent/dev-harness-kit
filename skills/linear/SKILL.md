---
name: linear
category: config
description: Optional Linear task tracker. Reconcile the current repository task with a canonical project and non-duplicate issue. Auto-syncs on every Claude Code edit when configured.
alpha: state
when_to_use: |
  - User types /dev-kit:linear
  - A workflow skill starts a new implementation, debugging, refactor, or plan task
  - The user asks to register, reconcile, or update work in Linear
  - Every Edit|Write|MultiEdit fires the auto-sync hook (when configured)
allowed-tools: Read Write
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

When Linear is configured (`LINEAR_API_KEY` env var OR `.dev-kit/.enabled.json:mcp.linear` ∈ {`auto`, `on`}), `hooks/linear-autosync.sh` runs `tools/linear_sync.py` before every Edit|Write|MultiEdit. The script:

1. Reads the current task's first user prompt from `.dev-kit/hand-off/linear.json` (or a fresh prompt surfaced through the same handoff).
2. Skips read-only / non-task prompts (`/`, `#`, `!`, `ls `, `cat `, `grep `, `git status`, and prompts that lack a work verb).
3. Finds or creates the project named exactly after the repository.
4. Searches for an open issue whose `description` starts with `<!-- scope:<branch>::<prompt-head> -->`.
5. Updates the existing issue OR creates a new one with the same scope marker.
6. Writes the updated handoff so the next edit reuses the same issue.

The script always returns exit code 0. Transport errors, missing tokens, and GraphQL failures are logged to stderr and never block the edit (per #539: "Linear failures are non-blocking for implicit workflow calls."). Users without Linear configured are unaffected — the hook fast-paths on missing env var and `.enabled.json`.

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
