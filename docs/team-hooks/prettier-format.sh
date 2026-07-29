#!/usr/bin/env bash
# prettier-format.sh — PostToolUse hook (team install).
# Auto-format edited files with prettier. Advisory only (exits 0).
#
# Input (Claude Code hook protocol, JSON via stdin):
#   {"tool_name": "Edit|Write|MultiEdit", "tool_input": {...}}
#
# Behavior:
#   - Extract file path via jq (not inline python3 — project convention)
#   - Skip if not a supported file type
#   - Prefer local node_modules/.bin/prettier; skip if missing
#     (avoids the npx install-prompt hang that reads /dev/tty)
#   - Run `prettier --write <file>` if found
#   - **Disk-drift warning**: after running, print `MODIFIED <path>` to
#     stdout so Claude re-reads the file (Claude's in-memory view would
#     otherwise drift from disk after auto-format)
#   - Never block — print warnings only
#
# This script is a TEMPLATE — copy into your project's .claude/hooks/
# and reference from .claude/settings.json (see docs/adoption/team-adoption.md).

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

# Only format files prettier understands
case "$FILE" in
  *.js|*.jsx|*.ts|*.tsx|*.mjs|*.cjs|*.json|*.jsonc|*.md|*.mdx|*.css|*.scss|*.less|*.html|*.vue|*.svelte|*.yaml|*.yml) ;;
  *) exit 0 ;;
esac

# Find prettier — PREFER local install (avoids npx hang on /dev/tty)
# Try in order: local node_modules, pnpm exec, then global prettier binary
# Skip npx entirely (it prompts to install missing packages).
PRETTIER=""
if [ -x "./node_modules/.bin/prettier" ]; then
  PRETTIER="./node_modules/.bin/prettier"
elif [ -x "../node_modules/.bin/prettier" ]; then
  PRETTIER="../node_modules/.bin/prettier"
elif command -v pnpm >/dev/null 2>&1; then
  PRETTIER="pnpm exec prettier"
elif command -v prettier >/dev/null 2>&1; then
  PRETTIER="prettier"
fi
[ -z "$PRETTIER" ] && exit 0

# Capture pre-format content hash so we can detect "did prettier change anything?"
# (using a hash, not mtime — mtime rounds to whole seconds and misses any
# format run that completes within the same wall-clock second as the edit,
# leaving Claude's in-memory view silently out of sync with disk.)
PRE_HASH="$(shasum -a 256 "$FILE" 2>/dev/null | awk '{print $1}' || sha256sum "$FILE" 2>/dev/null | awk '{print $1}' || echo 0)"

# Run prettier (advisory — never block). Capture stdout+stderr separately.
LOG_FILE="$(mktemp -t prettier.XXXXXX.log)"
if ! $PRETTIER --write "$FILE" >"$LOG_FILE" 2>&1; then
  echo "prettier-format: failed to format $FILE (non-fatal):" >&2
  cat "$LOG_FILE" >&2
  rm -f "$LOG_FILE"
  exit 0
fi
rm -f "$LOG_FILE"

# Disk-drift warning: if content changed, Claude's in-memory copy is stale
POST_HASH="$(shasum -a 256 "$FILE" 2>/dev/null | awk '{print $1}' || sha256sum "$FILE" 2>/dev/null | awk '{print $1}' || echo 0)"
if [ "$PRE_HASH" != "$POST_HASH" ] && [ "$PRE_HASH" != "0" ]; then
  # MODIFIED line: Claude's hook stdout parser can pattern-match on this
  echo "MODIFIED $FILE"
  echo "prettier-format: $FILE was reformatted by prettier. Re-read before further edits." >&2
fi

exit 0
