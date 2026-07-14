#!/usr/bin/env bash
# log-on.sh — install loghooks into the target project's settings.
#
# Merges:
#   <loghooks>/.claude/settings.json  →  <target>/.claude/settings.json
#   <loghooks>/.codex/hooks.json       →  <target>/.codex/hooks.json
#
# Every inserted entry is tagged _loghooks_managed=true so log-off.sh can
# strip exactly our additions without touching the user's existing hooks.
#
# Idempotent: re-running refreshes entries (replace-by-command, not duplicate).
# Safe to run on a project that has unrelated hooks already.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

usage() {
    cat <<EOF
Usage: $(basename "$0") [--target DIR | --global] [--codex-only | --claude-only]

Installs the loghooks Stop/SessionEnd entries into the target project's
Claude Code + Codex settings. Existing hooks are preserved.

  --target DIR     target project (default: \$PWD)
  --global         install to \$HOME/.claude/settings.json instead of a
                   per-project target. Recommended for multi-project /
                   multi-worktree users — a single install captures
                   every session anywhere on the machine. Mutually
                   exclusive with --target.
  --claude-only    touch only .claude/settings.json
  --codex-only     touch only .codex/hooks.json (no-op if loghooks has no codex config)

If neither flag is set, both files are touched when present in the source.

Env:
  LOGHOOKS_DIR   source repo (default: \$HOME/dev/loghooks)
  TARGET_DIR     target project (default: \$PWD)
EOF
}

CLAUDE_ONLY=0
CODEX_ONLY=0
GLOBAL=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)       TARGET_DIR="$2"; shift 2 ;;
        --global)       GLOBAL=1; shift ;;
        --claude-only)  CLAUDE_ONLY=1; shift ;;
        --codex-only)   CODEX_ONLY=1; shift ;;
        -h|--help)      usage; exit 0 ;;
        *) echo "ERROR: unknown arg: $1" >&2; usage; exit 1 ;;
    esac
done

if [[ "$CLAUDE_ONLY" -eq 1 && "$CODEX_ONLY" -eq 1 ]]; then
    echo "ERROR: --claude-only and --codex-only are mutually exclusive" >&2
    exit 1
fi
if [[ "$GLOBAL" -eq 1 && -n "${TARGET_DIR:-}" ]]; then
    echo "ERROR: --global is mutually exclusive with --target" >&2
    exit 1
fi

require_jq
LOGHOOKS_DIR="$(resolve_loghooks_dir)"
if [[ "$GLOBAL" -eq 1 ]]; then
    TARGET_DIR="$(resolve_global_dir)"
    if [[ ! -d "$TARGET_DIR" ]]; then
        mkdir -p "$TARGET_DIR"
    fi
    echo "Global install: $TARGET_DIR"
else
    TARGET_DIR="$(resolve_target_dir)"
fi

if [[ ! -d "$TARGET_DIR" ]]; then
    echo "ERROR: target dir does not exist: $TARGET_DIR" >&2
    exit 4
fi

# Refuse if /log setup hasn't run yet — the hooks call a script that
# must live in the target project. For --global, that script lives at
# $HOME/.claude/save_log.py; for per-project, at <target>/tools/.
if [[ "$GLOBAL" -eq 1 ]]; then
    SAVE_LOG_PATH="$TARGET_DIR/save_log.py"
else
    SAVE_LOG_PATH="$TARGET_DIR/tools/save_log.py"
fi
if [[ ! -x "$SAVE_LOG_PATH" ]]; then
    echo "ERROR: $SAVE_LOG_PATH missing." >&2
    if [[ "$GLOBAL" -eq 1 ]]; then
        echo "Run: /dev-kit:log setup --global   first." >&2
    else
        echo "Run: /dev-kit:log setup   first." >&2
    fi
    exit 5
fi

touch_claude=0
touch_codex=0
if [[ "$CLAUDE_ONLY" -eq 1 ]]; then touch_claude=1
elif [[ "$CODEX_ONLY" -eq 1 ]]; then touch_codex=1
else
    touch_claude=1
    [[ -f "$LOGHOOKS_DIR/.codex/hooks.json" ]] && touch_codex=1
fi

# For --global install, rewrite the source command paths so the merged
# hook references ${HOME}/.claude/save_log.py (self-contained) instead
# of ${CLAUDE_PROJECT_DIR}/tools/save_log.py (which assumes a per-project
# copy that doesn't exist in global mode).
#
# prepare_global_source() writes the rewritten JSON to its own mktemp'd
# file and prints the path on stdout. Capture it into a variable — DO
# NOT redirect the function's stdout, that would write the path itself
# (a string) into the file instead of the JSON. We also keep a per-call
# cleanup list so multiple invocations in a single run don't leak.
GLOBAL_SRC_FILES=()
cleanup_global_src() {
    if [[ ${#GLOBAL_SRC_FILES[@]} -gt 0 ]]; then
        rm -f "${GLOBAL_SRC_FILES[@]}"
    fi
}
trap cleanup_global_src EXIT

if [[ "$GLOBAL" -eq 1 && "$touch_claude" -eq 1 ]]; then
    SRC="$(prepare_global_source "$LOGHOOKS_DIR/.claude/settings.json")"
    GLOBAL_SRC_FILES+=("$SRC")
else
    SRC="$LOGHOOKS_DIR/.claude/settings.json"
fi

if [[ "$touch_claude" -eq 1 ]]; then
    # --global install: TARGET_DIR is already $HOME/.claude, so the
    # settings file is $TARGET_DIR/settings.json (no .claude/ prefix).
    # Per-project install: TARGET_DIR is the project root, settings live
    # at $TARGET_DIR/.claude/settings.json.
    if [[ "$GLOBAL" -eq 1 ]]; then
        DST="$TARGET_DIR/settings.json"
    else
        DST="$TARGET_DIR/.claude/settings.json"
    fi
    mkdir -p "$(dirname "$DST")"
    PREV="$(count_managed "$DST")"
    merge_loghooks_into "$SRC" "$DST"
    POST="$(count_managed "$DST")"
    echo "claude: $DST  ($PREV → $POST managed entries)"
fi

# Codex: --global rewrites the command path the same way. Codex settings
# live at $HOME/.codex/hooks.json for global installs (mirrors the
# project's <target>/.codex/hooks.json convention).
if [[ "$GLOBAL" -eq 1 && "$touch_codex" -eq 1 ]]; then
    SRC_CODEX="$(prepare_global_source "$LOGHOOKS_DIR/.codex/hooks.json")"
    GLOBAL_SRC_FILES+=("$SRC_CODEX")
else
    SRC_CODEX="$LOGHOOKS_DIR/.codex/hooks.json"
fi

if [[ "$touch_codex" -eq 1 ]]; then
    if [[ "$GLOBAL" -eq 1 ]]; then
        DST_CODEX="$HOME/.codex/hooks.json"
    else
        DST_CODEX="$TARGET_DIR/.codex/hooks.json"
    fi
    mkdir -p "$(dirname "$DST_CODEX")"
    PREV="$(count_managed "$DST_CODEX")"
    merge_loghooks_into "$SRC_CODEX" "$DST_CODEX"
    POST="$(count_managed "$DST_CODEX")"
    echo "codex:  $DST_CODEX  ($PREV → $POST managed entries)"
fi

echo
echo "Logging ON. Stop/SessionEnd will write transcripts to:"
echo "  $TARGET_DIR/logs/claude-code/"
[[ "$touch_codex" -eq 1 ]] && echo "  $TARGET_DIR/logs/codex/"
echo
echo "Turn off with: /dev-kit:log off"