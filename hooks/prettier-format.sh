#!/usr/bin/env bash
# prettier-format.sh — PostToolUse hook
# Auto-format edited files with prettier. Advisory only (exits 0 even on error).
#
# Input (Claude Code hook protocol, JSON via stdin):
#   {"tool_name": "Edit|Write|MultiEdit", "tool_input": {...}}
#
# Behavior:
#   - Extract file path from tool_input
#   - Skip if not a supported file type
#   - Run `npx prettier --write <file>` if prettier is available
#   - Never block — print warnings only
#
# Usage: enable in .claude/settings.json as PostToolUse matcher on Edit|Write|MultiEdit

set -uo pipefail

# Read hook input from stdin
INPUT="$(cat)"

# Extract file path (varies by tool)
FILE=""
for field in file_path path notebook_path; do
  FILE="$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('tool_input', {}).get('$field', '') or '')
except: print('')
" 2>/dev/null)"
  [ -n "$FILE" ] && break
done

# No file path → nothing to do
if [ -z "$FILE" ] || [ ! -f "$FILE" ]; then
  exit 0
fi

# Only format files prettier understands
case "$FILE" in
  *.js|*.jsx|*.ts|*.tsx|*.mjs|*.cjs|*.json|*.jsonc|*.md|*.mdx|*.css|*.scss|*.less|*.html|*.vue|*.svelte|*.yaml|*.yml) ;;
  *) exit 0 ;;
esac

# Find prettier
PRETTIER=""
for candidate in npx pnpm prettier; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PRETTIER="$candidate"
    break
  fi
done
[ -z "$PRETTIER" ] && exit 0

# Run prettier (advisory — never block)
STDERR_OUT=""
if [ "$PRETTIER" = "prettier" ]; then
  STDERR_OUT="$(prettier --write "$FILE" 2>&1)" || true
else
  STDERR_OUT="$($PRETTIER prettier --write "$FILE" 2>&1)" || true
fi

if [ -n "$STDERR_OUT" ]; then
  echo "prettier-format: $STDERR_OUT" >&2
fi

exit 0
