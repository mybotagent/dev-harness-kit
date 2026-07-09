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
Usage: $(basename "$0") [--target DIR] [--codex-only | --claude-only]

Installs the loghooks Stop/SessionEnd entries into the target project's
Claude Code + Codex settings. Existing hooks are preserved.

  --target DIR     target project (default: \$PWD)
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
while [[ $# -gt 0 ]]; do
    case "$1" in
        --target)       TARGET_DIR="$2"; shift 2 ;;
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

require_jq
LOGHOOKS_DIR="$(resolve_loghooks_dir)"
TARGET_DIR="$(resolve_target_dir)"

if [[ ! -d "$TARGET_DIR" ]]; then
    echo "ERROR: target dir does not exist: $TARGET_DIR" >&2
    exit 4
fi

# Refuse if /log setup hasn't run yet — the hooks call a script that
# must live in the target project.
if [[ ! -x "$TARGET_DIR/tools/save_log.py" ]]; then
    echo "ERROR: $TARGET_DIR/tools/save_log.py missing." >&2
    echo "Run: /dev-kit:log setup   first." >&2
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

if [[ "$touch_claude" -eq 1 ]]; then
    SRC="$LOGHOOKS_DIR/.claude/settings.json"
    DST="$TARGET_DIR/.claude/settings.json"
    mkdir -p "$TARGET_DIR/.claude"
    PREV="$(count_managed "$DST")"
    merge_loghooks_into "$SRC" "$DST"
    POST="$(count_managed "$DST")"
    echo "claude: $DST  ($PREV → $POST managed entries)"
fi

if [[ "$touch_codex" -eq 1 ]]; then
    SRC="$LOGHOOKS_DIR/.codex/hooks.json"
    DST="$TARGET_DIR/.codex/hooks.json"
    mkdir -p "$TARGET_DIR/.codex"
    PREV="$(count_managed "$DST")"
    merge_loghooks_into "$SRC" "$DST"
    POST="$(count_managed "$DST")"
    echo "codex:  $DST  ($PREV → $POST managed entries)"
fi

echo
echo "Logging ON. Stop/SessionEnd will write transcripts to:"
echo "  $TARGET_DIR/logs/claude-code/"
[[ "$touch_codex" -eq 1 ]] && echo "  $TARGET_DIR/logs/codex/"
echo
echo "Turn off with: /dev-kit:log off"