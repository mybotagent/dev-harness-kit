# logs/

Conversation transcripts captured by the `/dev-kit:log` hooks.

## What's in here

| Path | Source | Contents |
|---|---|---|
| `claude-code/<branch>/` | Claude Code `Stop` + `SessionEnd` hooks | One `.jsonl` per session, grouped by `gitBranch` |
| `codex/<branch>/` | Codex `Stop` + `SessionEnd` hooks | One `.jsonl` per session, grouped by `gitBranch` |

Captured files are gitignored (`logs/.gitignore` ignores `*.jsonl`). Only the empty subdirs are tracked, via `.gitkeep`. The transcripts stay local — they are NOT shipped, NOT pushed, NOT indexed by the eval harness.

The `<branch>` bucket is one of:

- `<branch-name>` — attached HEAD on a real branch (e.g. `main`, `feature-x`).
- `detached-<short-sha>` — `git checkout <commit>` / CI checkout of a tag.
- `no-git` — non-git cwd OR `git` binary missing on PATH.

The tokenizer reads the branch from each JSONL line's top-level `gitBranch` field (Claude Code sets this on every record), with a path-based fallback for legacy flat files. `/dev-kit:token-analyzer` filters with `--branch <name>` and renders a "Cost by Branch" panel.

## Why this exists

`/dev-kit:log` wraps the standalone [`~/dev/loghooks`](https://github.com/sh-ai-x/loghooks) repo as a one-command on/off per project. Hooks are tagged with a sentinel (`_loghooks_managed=true`) so:

- `on`  merges `Stop` + `SessionEnd` entries into `.claude/settings.json` + `.codex/hooks.json` without touching your pre-existing hooks.
- `off` strips only the sentinel-tagged entries. Your hooks stay.

This folder + `tools/save_log.py` are the runtime artifacts. Both are scaffolded once via `/dev-kit:log setup`; a future `on` skips the setup step.

## Quick start

```bash
# Once per project
/dev-kit:log setup     # copies tools/save_log.py + creates logs/{claude-code,codex}/
/dev-kit:log on        # merges hooks into .claude/settings.json + .codex/hooks.json

# ... use Claude Code / Codex — transcripts land in logs/<tool>/<branch>/<sid>.jsonl ...

/dev-kit:log status    # managed=N captured=N (read-only)
/dev-kit:log off       # strips sentinel-tagged entries; scaffold left in place
```

## Source

The hook payloads come from `${HOME}/dev/loghooks` (override with `LOGHOOKS_DIR`). The skill scripts live at `skills/log/scripts/{log-setup,log-on,log-off,log-status}.sh`. See `skills/log/SKILL.md` for the full contract.

## Cleanup

`off` deliberately leaves `tools/save_log.py` + `logs/` in place — they cost nothing and a future `on` is a no-op setup. To remove everything:

```bash
git rm -rf tools/save_log.py logs/
```
