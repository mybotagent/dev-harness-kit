# Personal vs Team adoption

dev-kit is one plugin, two adoption levels. Pick one based on whether you use Claude Code solo or in a team.

## Two levels

| Level | Lives in | Configured via | Who edits it |
|---|---|---|---|
| **Personal** | `~/.claude/plugins/dev-kit/` (User-level install) | `~/.claude/CLAUDE.md` | you, only you |
| **Team** | `<project>/.claude/plugins/dev-kit/` (Project-level install) | `<project>/CLAUDE.md` + `<project>/<subfolder>/CLAUDE.md` | the team, via PR |

Both installs use the same plugin artifact. Only the install location and config layer differ.

## Install

```bash
# Personal (User-level) — applies to every project you open
claude plugin marketplace add sh-ai-x/dev-harness-kit
claude plugin install dev-kit --scope user

# Team (Project-level) — applies only to this project, committed via PR
cd your-project
claude plugin marketplace add sh-ai-x/dev-harness-kit
claude plugin install dev-kit --scope project
git add .claude/ && git commit -m "chore: install dev-kit plugin"
```

## CLAUDE.md patterns

### Project root — `<project>/CLAUDE.md`

The single source of truth for the whole repo. Commit this. It includes:

- Iron Laws (no test no code, root-cause-first, …)
- Project-wide conventions (language, framework, test runner, formatter)
- Build / lint / test commands
- Stage gates and what each one blocks

### Sub-folder overrides — `<project>/<subfolder>/CLAUDE.md`

Loaded automatically when Claude Code works in that folder. Used for:

- Per-package conventions (e.g. `packages/api/CLAUDE.md` says "zod validation mandatory")
- Per-area guards (e.g. `migrations/CLAUDE.md` says "never edit a committed migration")
- Per-stack rules (e.g. `frontend/CLAUDE.md` says "vitest, no jest")

These override root rules only when narrower. They never contradict the root Iron Laws.

### Personal layer — `~/.claude/CLAUDE.md`

Loaded on top of project rules for every session. Used for:

- Your personal prefs (default model, preferred editor, key bindings)
- Cross-project shortcuts
- Things you never want to commit to a repo

## Team hooks (opt-in)

The plugin ships 8 hooks. 5 are **personal** (auto-on at user install), 3 are **team** (opt in per-project).

| Hook | Stage | Mode | Default |
|---|---|---|---|
| `tdd-guard` | PreToolUse (Edit/Write) | advisory | personal ✅ |
| `bash-guard` | PreToolUse (Bash) | advisory | personal ✅ |
| `secret-scan` | PostToolUse (Edit/Write) | advisory | personal ✅ |
| `slop-detector` | PostToolUse (Edit/Write) | advisory | personal ✅ |
| `stop-verify` | Stop | advisory | personal ✅ |
| `prettier-format` | PostToolUse (Edit/Write) | advisory | **team** (opt in) |
| `block-dangerous-commands` | PreToolUse (Bash) | **hard-block** | **team** (opt in) |
| `eslint-fix` | PostToolUse (Edit/Write) | advisory | **team** (opt in) |

### Why team hooks are opt-in, not auto-on

Auto-formatting (`prettier`, `eslint --fix`) and hard-blocks on `rm -rf` are team policies, not personal preferences. A solo dev who works in 5 repos shouldn't be forced into a 6th repo's formatter. So the plugin ships them but doesn't auto-activate them. Each repo opts in.

### Enable team hooks in a project

Edit `<project>/.claude/settings.json`:

```json
{
  "permissions": {
    "allow": ["Edit", "Write", "Bash"]
  },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/block-dangerous-commands.sh" }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit",
        "hooks": [
          { "type": "command", "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/prettier-format.sh" },
          { "type": "command", "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/eslint-fix.sh" }
        ]
      }
    ]
  }
}
```

This file is committed. The team shares the policy.

### Override per-folder

A sub-folder can override by adding its own `.claude/settings.json`. Example: `packages/legacy/` opts out of `prettier-format` because the legacy code is excluded from prettier for now.

## Why the split

- **Personal = your machine.** Always on, never committed, changes with your mood.
- **Team = the repo.** Always committed, changes via PR, reviewed by humans.
- **Folder = a sub-area.** Inherits project, overrides for one directory.

Three layers, one plugin, zero conflict.
