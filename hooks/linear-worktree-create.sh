#!/usr/bin/env bash
# linear-worktree-create.sh — PostToolUse:Bash hook.
#
# Catches a `git worktree add` after the Bash tool returns. The
# worktree-auto-cut.sh UserPromptSubmit hook covers the
# auto-cut case; this hook covers the manual case (e.g. the
# user runs `git worktree add -b feat/foo .worktrees/foo
# origin/main` themselves) so the new worktree's handoff gets
# registered before its first Edit|Write (or first SessionStart,
# if the user reopens Claude Code in the new path).
#
# The auto-sync is owner-gated inside tools/linear_sync.py::
# auto_sync — non-owners bail silently.
#
# Path resolution: prefer the path parsed out of the bash
# command (the only authoritative signal of "which worktree was
# just created"). Fall back to the most recent entry in `git
# worktree list --porcelain` if the parse fails (e.g. multi-line
# bash command, or an exotic flag the parser doesn't know).
#
# Always exits 0 (non-blocking per #539).

# Source the shared preamble (set -uo pipefail, INPUT=$(cat),
# worktree_detect, jq-missing warning).
# shellcheck source=lib/hook-preamble.sh
source "${BASH_SOURCE[0]%/*}/lib/hook-preamble.sh"

# Fail open with a stderr warning if jq is missing.
if ! command -v jq >/dev/null 2>&1; then
  worktree_detect_jq_missing_warn "linear-worktree-create.sh"
  exit 0
fi

# Pull the bash command + tool response from the payload. We need
# both: the command tells us which path was created; the response
# tells us whether git exited 0 (PostToolUse fires on every Bash
# call, not only successes).
COMMAND="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // ""' 2>/dev/null)"
RESPONSE="$(printf '%s' "$INPUT" | jq -r '.tool_response // ""' 2>/dev/null)"
[ -z "$COMMAND" ] && exit 0

# Only fire on `git worktree add` — the matcher is "Bash" so any
# command lands here. Avoid false positives on `git worktree list`,
# `git worktree remove`, or branches that just happen to contain
# the substring "worktree add" in their message.
case "$COMMAND" in
  *"git worktree add"*) ;;
  *) exit 0 ;;
esac

# The bash tool may chain multiple commands with `&&` or `;`. We
# only care about the git worktree add fragment. Walk the command
# left-to-right, splitting on `&&`, `;`, and `|`.
FRAGMENT=""
IFS_BACKUP="$IFS"
IFS=$'&;|\n'
for piece in $COMMAND; do
  case "$piece" in
    *"git worktree add"*)
      FRAGMENT="$piece"
      break
      ;;
  esac
done
IFS="$IFS_BACKUP"
[ -z "$FRAGMENT" ] && exit 0

# Parse the new worktree path out of the fragment. Supported
# forms (the canonical ones emitted by `git worktree add --help`):
#   git worktree add <path> [<commit-ish>]
#   git worktree add -b <branch> <path> [<commit-ish>]
#   git worktree add -B <branch> <path> [<commit-ish>]
#   git worktree add --detach [<path>] [<commit-ish>]
# The path is always the first non-flag positional arg after `add`.
# Flags that consume a value (-b, -B, --track) are skipped so
# the next positional is captured.
WT_PATH=""
FOUND_ADD=0
SKIP_NEXT=0
for tok in $FRAGMENT; do
  if [ "$SKIP_NEXT" = "1" ]; then
    SKIP_NEXT=0
    continue
  fi
  case "$tok" in
    add)
      FOUND_ADD=1
      continue
      ;;
    -b|-B|--track|--track=*)
      SKIP_NEXT=1
      continue
      ;;
    -*)
      # Other flags (--detach, --force, --checkout, --lock,
      # --no-checkout, --no-track, --quiet, ...) take no value.
      continue
      ;;
    *)
      if [ "$FOUND_ADD" = "1" ] && [ -z "$WT_PATH" ]; then
        WT_PATH="$tok"
        break
      fi
      ;;
  esac
done

# Fallback: if the parse failed, take the most recent worktree
# from `git worktree list --porcelain`. Each worktree is a 3-line
# block (worktree <path>\nHEAD <sha>\nbranch <refs>); we want the
# last block's first line.
if [ -z "$WT_PATH" ] || [ ! -d "$WT_PATH" ]; then
  WT_PATH="$(cd "$PWD" && git worktree list --porcelain 2>/dev/null \
    | awk 'BEGIN{block=""} /^worktree /{block=$2} END{print block}')"
fi
[ -z "$WT_PATH" ] || [ ! -d "$WT_PATH" ] && exit 0

# Resolve to absolute path so the subsequent `cd` is unambiguous.
WT_PATH="$(cd "$WT_PATH" && pwd -P 2>/dev/null || printf '%s' "$WT_PATH")"

# Not a dev-harness-kit checkout — bail silently (other Claude
# Code projects may share this hook).
if [ ! -f "$WT_PATH/tools/linear_sync.py" ]; then
  exit 0
fi

# Fast-path mirror of hooks/linear-autosync.sh: bail before
# forking Python when no activation source is present. The
# owner-gate + enabled checks live in Python.
USER_ENV_DIR="${XDG_CONFIG_HOME:-$HOME/.config}"
USER_ENV="$USER_ENV_DIR/dev-kit/.env"
if [ -z "${LINEAR_API_KEY:-}" ] && \
   [ ! -f "$USER_ENV" ] && \
   [ ! -f "$WT_PATH/.dev-kit/.env.linear" ] && \
   [ ! -f "$WT_PATH/.dev-kit/linear-config.json" ] && \
   [ ! -f "$WT_PATH/.dev-kit/.enabled.json" ]; then
  exit 0
fi

# Run the auto-sync from inside the new worktree so the handoff
# lands at .dev-kit/hand-off/linear/<worktree-slug>.json. The
# owner gate inside auto_sync bails silently for non-owners.
for py in python3 python py; do
  if command -v "$py" >/dev/null 2>&1; then
    (cd "$WT_PATH" && "$py" "$WT_PATH/tools/linear_sync.py" auto-sync) || true
    exit 0
  fi
done

exit 0
