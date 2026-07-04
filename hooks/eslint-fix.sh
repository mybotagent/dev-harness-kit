#!/usr/bin/env bash
# eslint-fix.sh — PostToolUse hook
# Auto-fix lint issues on edited TS/JS files. Advisory only (exits 0 even on error).
#
# Input (Claude Code hook protocol, JSON via stdin):
#   {"tool_name": "Edit|Write|MultiEdit", "tool_input": {...}}
#
# Behavior:
#   - Extract file path from tool_input
#   - Skip if not a .ts/.tsx/.js/.jsx file
#   - Run `npx eslint --fix <file>` (or local ./node_modules/.bin/eslint)
#   - Never block — print warnings only
#
# Usage: enable in .claude/settings.json as PostToolUse matcher on Edit|Write|MultiEdit

set -uo pipefail

INPUT="$(cat)"

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

if [ -z "$FILE" ] || [ ! -f "$FILE" ]; then
  exit 0
fi

# Only lint TS/JS files
case "$FILE" in
  *.ts|*.tsx|*.js|*.jsx|*.mjs|*.cjs) ;;
  *) exit 0 ;;
esac

# Find eslint (prefer local install)
ESLINT=""
for candidate in ./node_modules/.bin/eslint npx pnpm eslint; do
  if command -v "${candidate##*/}" >/dev/null 2>&1 && { [ -x "$candidate" ] || [ "${candidate##*/}" != "${candidate}" ]; }; then
    ESLINT="$candidate"
    break
  fi
done

# Simpler: just check if npx eslint works
if command -v npx >/dev/null 2>&1; then
  ESLINT="npx eslint"
fi

[ -z "$ESLINT" ] && exit 0

# Run eslint --fix (advisory — never block)
STDERR_OUT=""
STDERR_OUT="$($ESLINT --fix "$FILE" 2>&1)" || true

if [ -n "$STDERR_OUT" ]; then
  echo "eslint-fix: $STDERR_OUT" >&2
fi

exit 0
