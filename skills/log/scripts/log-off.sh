#!/usr/bin/env bash
# log-off.sh — remove loghooks-managed entries from the target project's settings.
#
# Strips only entries tagged _loghooks_managed=true. User-authored hooks
# (any entry without the sentinel) are left untouched. If, after removal,
# a settings.json has no hooks key at all, the file is left in place but
# the key is removed for cleanliness.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

usage() {
    cat <<EOF
Usage: $(basename "$0") [--target DIR | --global] [--codex-only | --claude-only]

Removes only the loghooks-managed entries (those tagged
_loghooks_managed=true by log-on.sh) from the target project's settings.
User-authored hooks are preserved.

  --target DIR     target project (default: \$PWD)
  --global         strip entries from \$HOME/.claude/settings.json instead
                   of a per-project target. Must match the --global
                   used at install time. Mutually exclusive with --target.
  --claude-only    touch only .claude/settings.json
  --codex-only     touch only .codex/hooks.json

If neither flag is set, both files are touched.

Env:
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
if [[ "$GLOBAL" -eq 1 ]]; then
    TARGET_DIR="$(resolve_global_dir)"
else
    TARGET_DIR="$(resolve_target_dir)"
fi

touch_claude=1
touch_codex=1
if [[ "$CLAUDE_ONLY" -eq 1 ]]; then touch_codex=0
elif [[ "$CODEX_ONLY" -eq 1 ]]; then touch_claude=0
fi

# --global: target IS the global dir ($HOME/.claude), so the settings
# file lives at $TARGET_DIR/settings.json (no .claude/ prefix). Per-project
# install: TARGET_DIR is the project root, settings at .claude/settings.json.
if [[ "$GLOBAL" -eq 1 ]]; then
    CLAUDE_DST="$TARGET_DIR/settings.json"
    CODEX_DST="$HOME/.codex/hooks.json"
else
    CLAUDE_DST="$TARGET_DIR/.claude/settings.json"
    CODEX_DST="$TARGET_DIR/.codex/hooks.json"
fi

removed_total=0
if [[ "$touch_claude" -eq 1 ]]; then
    DST="$CLAUDE_DST"
    PREV="$(count_managed "$DST")"
    if [[ "$PREV" -gt 0 ]]; then
        remove_managed_from "$DST"
        POST="$(count_managed "$DST")"
        echo "claude: $DST  ($PREV → $POST managed entries)"
        removed_total=$((removed_total + PREV - POST))
    else
        echo "claude: $DST  (no loghooks-managed entries)"
    fi
fi

if [[ "$touch_codex" -eq 1 ]]; then
    DST="$CODEX_DST"
    PREV="$(count_managed "$DST")"
    if [[ "$PREV" -gt 0 ]]; then
        remove_managed_from "$DST"
        POST="$(count_managed "$DST")"
        echo "codex:  $DST  ($PREV → $POST managed entries)"
        removed_total=$((removed_total + PREV - POST))
    else
        echo "codex:  $DST  (no loghooks-managed entries)"
    fi
fi

if [[ "$removed_total" -eq 0 ]]; then
    echo
    echo "Logging was not on. Nothing removed."
else
    echo
    echo "Logging OFF. ${removed_total} managed entries stripped."
    echo "Note: tools/save_log.py + logs/ scaffold were left in place."
    echo "Remove them manually if no longer needed."
fi