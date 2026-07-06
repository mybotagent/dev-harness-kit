#!/usr/bin/env bash
# eslint-fix.sh — PostToolUse hook (team install).
# Auto-fix lint issues on edited TS/JS files. Advisory only (exits 0).
#
# Input (Claude Code hook protocol, JSON via stdin):
#   {"tool_name": "Edit|Write|MultiEdit", "tool_input": {...}}
#
# Behavior:
#   - Extract file path via jq (not inline python3 — project convention)
#   - Skip if not a .ts/.tsx/.js/.jsx file
#   - Prefer local node_modules/.bin/eslint; skip if missing
#     (avoids the npx install-prompt hang that reads /dev/tty)
#   - Run `eslint --fix <file>` if found
#   - **Disk-drift warning**: after running, print `MODIFIED <path>` to
#     stdout so Claude re-reads the file (Claude's in-memory view would
#     otherwise drift from disk after --fix)
#   - Never block — print warnings only
#
# This script is a TEMPLATE — copy into your project's .claude/hooks/
# and reference from .claude/settings.json (see docs/team-adoption.md).

set -uo pipefail

INPUT="$(cat)"

# Extract file path (jq, not inline python3)
FILE=""
for field in file_path path notebook_path; do
  candidate="$(printf '%s' "$INPUT" | jq -r ".tool_input.${field} // empty" 2>/dev/null)"
  if [ "$candidate" != "empty" ] && [ "$candidate" != "null" ] && [ -n "$candidate" ]; then
    FILE="$candidate"
    break
  fi
done

# No file path → nothing to do
[ -z "$FILE" ] || [ ! -f "$FILE" ] && exit 0

# Only lint TS/JS files
case "$FILE" in
  *.ts|*.tsx|*.js|*.jsx|*.mjs|*.cjs) ;;
  *) exit 0 ;;
esac

# Find eslint — PREFER local install (avoids npx hang on /dev/tty)
ESLINT=""
if [ -x "./node_modules/.bin/eslint" ]; then
  ESLINT="./node_modules/.bin/eslint"
elif [ -x "../node_modules/.bin/eslint" ]; then
  ESLINT="../node_modules/.bin/eslint"
elif command -v pnpm >/dev/null 2>&1; then
  ESLINT="pnpm exec eslint"
elif command -v eslint >/dev/null 2>&1; then
  ESLINT="eslint"
fi
[ -z "$ESLINT" ] && exit 0

# Capture pre-fix content hash to detect "did eslint change anything?"
# (using a hash, not mtime — mtime rounds to whole seconds and misses
# any lint run that completes within the same wall-clock second as the
# edit, leaving Claude's in-memory view silently out of sync with disk.)
PRE_HASH="$(shasum -a 256 "$FILE" 2>/dev/null | awk '{print $1}' || sha256sum "$FILE" 2>/dev/null | awk '{print $1}' || echo 0)"

# Run eslint --fix. Capture stdout+stderr to a temp file (not a misnamed
# STDERR_OUT variable) so we can include them in the warning if needed.
LOG_FILE="$(mktemp -t eslint.XXXXXX.log)"
if ! $ESLINT --fix "$FILE" >"$LOG_FILE" 2>&1; then
  # --fix may still apply some changes even on non-zero exit (unfixable
  # remaining errors). Treat the run as successful-but-with-warnings.
  echo "eslint-fix: $FILE has unfixable issues (non-fatal):" >&2
  cat "$LOG_FILE" >&2
  rm -f "$LOG_FILE"
  # Fall through to disk-drift check below
fi
rm -f "$LOG_FILE"

# Disk-drift warning: if content changed, Claude's in-memory copy is stale
POST_HASH="$(shasum -a 256 "$FILE" 2>/dev/null | awk '{print $1}' || sha256sum "$FILE" 2>/dev/null | awk '{print $1}' || echo 0)"
if [ "$PRE_HASH" != "$POST_HASH" ] && [ "$PRE_HASH" != "0" ]; then
  # MODIFIED line: Claude's hook stdout parser can pattern-match on this
  echo "MODIFIED $FILE"
  echo "eslint-fix: $FILE was modified by eslint --fix. Re-read before further edits." >&2
fi

exit 0
