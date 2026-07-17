---
name: session-monitor
category: audit
description: Pick a Claude Code or Codex session across this repo's worktrees and emit the exact `cd <wt> && claude --resume <sid>` resume command. The skill drives the picker via `AskUserQuestion`; the tool also ships an inline arrow-key picker for shell users.
when_to_use: |
  - User types /dev-kit:session-monitor
  - User wants to see every running/stopped CC + Codex session across worktrees
  - User wants to resume a session and land in the correct worktree cwd
  - User mentions a specific session id and wants its resume command
  - User types /dev-kit:session-monitor cli-setup (install a `session-monitor` shell alias)
allowed-tools: Read Bash
disallowed-tools: Write Edit
model: haiku
user-invocable: true
disable-model-invocation: true
---

# /dev-kit:session-monitor -- skill-driven session picker

The skill's job is to surface up to 4 candidate sessions from this repo's
`/dev-kit:log` capture, let the user pick one with the harness's native
arrow-key UI (`AskUserQuestion`), and print the exact resume command for
them to run with the `!` prefix. The user never has to leave Claude Code
to drive the picker, and never has to type a session id from memory. The
shared log-parsing layer lives in `tools/token_efficiency_analyzer.py`;
this skill adds the `--json` discovery mode, the branch-enrichment step
that pulls the worktree's current HEAD branch (so the picker shows the
branch the worktree is *actually* on, not the one captured at log time),
and the `os.execvp` resume hand-off for the shell-only path.

There is also an inline arrow-key picker built on `termios` + ANSI
escapes (`python3 tools/session_monitor.py`, no args) intended for shell
sessions over `ssh` or in CI. Inside Claude Code, prefer the
`AskUserQuestion` flow below -- the user keeps their prompt scrollback,
the harness handles rendering, and resume does not require re-attaching
to a TTY.

## Flow

### Step 1 -- Discover

```bash
python3 tools/session_monitor.py --json --days 30
```

The output is a single JSON document. Top-level keys:
`logs_dir`, `generated_at`, `total_sessions`, `live_sessions`,
`worktrees` (list of worktree records). Each worktree has `name`, `state`,
`path` (absolute or null when the worktree is gone), `has_live`, and
`sessions` (list of session records). Each session has the **full**
`session_id`, `source` (`"claude-code"` or `"codex"`), `branch` (already
enriched from the worktree's current HEAD), `model`, `status`, `last_ts`,
`last_rel`, `pids`, `subagent_count`, and `log_path`.

Parse the output. If `total_sessions == 0`, tell the user
"[session-monitor] no sessions found; run `/dev-kit:log setup` then
`/dev-kit:log on` to start capturing" and stop.

### Step 2 -- Narrow to 2-4 candidates

`AskUserQuestion` caps options at 4. Selection rule, in order:

1. If the user mentioned a worktree, branch, model, source, or status in
   their prompt, filter to matching sessions first.
2. From the filtered set (or the full set), take sessions with
   `status == "live"` first; if any, sort by `last_ts` descending and
   keep the 4 newest.
3. If zero `live` sessions match, take the 4 IDLE with the most-recent
   `last_ts`.
4. If the filtered set is larger than 4 after step 1, mention in the
   confirmation that the rest are available via `--list` and surface a
   brief example line.

For each candidate, build the option as:

- `label`: `<8-char session id>  <branch>` (e.g. `79101dd7  main`). The
  8-char prefix is the same one shown in `claude --resume --help` and
  is enough for the user to disambiguate.
- `description`: `<glyph> <status>  <src>  <model>  <last_rel>  worktree=<wt>`
  (e.g. `● live  cc  MiniMax-M3  13m ago  worktree=main`). The
  status glyph matches `Status.LIVE -> "●"`, `IDLE -> "○"`, `STALE -> "⌀"`.

The `header` field of the `AskUserQuestion` call itself should be
`Pick a session to resume`.

### Step 3 -- Resume

After the user picks an option, build the resume command from the
matching JSON record:

- Claude Code session (`source == "claude-code"`):
  `cd <worktree.path> && claude --resume <session_id>`
- Codex session (`source == "codex"`):
  `cd <worktree.path> && codex resume <session_id>`

If `worktree.path` is null or `state` is `"merged"` / `"gone"`, fall
back to the main repo checkout. The main checkout is the
`logs_dir` parent directory (the dir that contains `logs/`); discover it
with `git -C "$(dirname <logs_dir>)" rev-parse --show-toplevel`. Mention
the fallback in the confirmation so the user knows why.

Print the confirmation and the command in a single block:

```
[session-monitor] resuming: 79101dd7  ● live  cc  MiniMax-M3  13m ago  → main checkout
! cd /Users/sanghee/dev/dev-harness-kit && claude --resume 79101dd7-ee12-414b-b76d-6b144a76ed81
```

Tell the user to run the `!` line so the new session replaces the
current one. **Do not exec the resume command yourself** -- Claude Code
resuming from inside a Claude Code session would fork-loop. The
`AskUserQuestion` path ends here.

## Status semantics

- `live` -- a running `claude`/`codex` process is cwd'd into the
  session's worktree (attributed to that worktree's newest session), or
  the session's last turn landed within `RECENCY_WINDOW_SECONDS` (180s).
- `idle` -- captured, inside the `--days` window, but not recently
  active.
- `stale` -- the session's worktree is merged into main or gone. Still
  listed so its conversation can be resumed, but resume falls back to
  the main checkout.

## Flags the tool supports

- `--days N` (default 30)
- `--repo <name>` substring filter
- `--logs-dir <path>` (default `<main-repo>/logs`)
- `--list` plain stdout (debugging / non-TTY previews). Each worktree
  group prints a `STATUS SRC ID MODEL BRANCH AGE` column-label line above
  its sessions.
- `--json` machine-readable (this skill's primary input)
- `--print-resume-command` print the cwd + argv for the first session,
  no picker
- `--cli-setup` install a `session-monitor` shell alias into the user's
  rc, then exit (see below). Add `--dry-run` to preview the block.

## `cli-setup` -- install the shell alias

When the user types `/dev-kit:session-monitor cli-setup` (or asks to "set
up the session-monitor CLI / alias"), run the installer instead of the
picker flow:

```bash
python3 tools/session_monitor.py --cli-setup
```

This appends a marker-wrapped managed block to the user's login rc
(`~/.zshrc` for zsh, `~/.bashrc` for bash, else `~/.profile`) defining:

```
alias session-monitor='<python> <abs path to tools/session_monitor.py>'
```

It is idempotent -- re-running refreshes the block in place (no
duplicates), and points at the current interpreter + script path. After
it runs, tell the user to activate the alias in their current shell:

```
! source ~/.zshrc
```

Then `session-monitor` (arrow-key picker), `session-monitor --list`, and
`session-monitor --days 90` work from any cwd; the tool resolves the
repo it is invoked from. To preview without touching the rc file, run
`python3 tools/session_monitor.py --cli-setup --dry-run`.

## Shell-only fallback (inline picker)

For users who want a single keystroke picker in a normal shell (e.g. over
`ssh`, in CI, or when stepping away from Claude Code):

```bash
python3 tools/session_monitor.py        # arrow keys + Enter
python3 tools/session_monitor.py --days 90
```

Same data, same resume hand-off. Picks the session, restores `termios`
cleanly, `cd`s into the worktree, and `exec`s the resumed CLI. The
inline picker is a full inline redraw per keystroke; the terminal's
scrollback is preserved when the picker exits.

## Next step

Hand off to `/dev-kit:token-analyzer` to drill into per-session token
spend and cost once a session of interest is identified here.
