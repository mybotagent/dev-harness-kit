#!/usr/bin/env bash
# hook-doctor — deterministic runtime and plugin-hook diagnostic.
set -u

ROOT="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
PROVIDER="${DEV_KIT_PROVIDER:-auto}"
PLUGIN_CHECK_ROOT="${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT:-$ROOT}}"
FAILURES=0

pass() { printf 'PASS  %s\n' "$*"; }
warn() { printf 'WARN  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*"; FAILURES=$((FAILURES + 1)); }

printf 'hook-doctor root=%s provider=%s\n' "$ROOT" "$PROVIDER"

if command -v bash >/dev/null 2>&1; then
  pass 'dependency: bash'
else
  fail 'dependency missing: bash (exit 127 is expected)'
fi

for command_name in jq python3 rsync; do
  if command -v "$command_name" >/dev/null 2>&1; then
    pass "dependency: $command_name"
  else
    warn "optional recovery dependency missing: $command_name"
  fi
done

if [ -n "${PLUGIN_ROOT:-}" ]; then
  pass "PLUGIN_ROOT=${PLUGIN_ROOT}"
elif [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  pass "CLAUDE_PLUGIN_ROOT=${CLAUDE_PLUGIN_ROOT}"
else
  warn 'plugin root environment variable is unset; the current client must be restarted or reloaded'
fi

check_manifest() {
  local manifest="$1"
  local root="$2"
  if [ ! -f "$manifest" ]; then
    fail "manifest missing: $manifest"
    return
  fi
  pass "manifest: $manifest"
  if command -v jq >/dev/null 2>&1; then
    while IFS= read -r command_text; do
      [ -n "$command_text" ] || continue
      local hook_file
      hook_file="$(printf '%s' "$command_text" | sed -nE 's#.*hooks/([^" ]+\.sh).*#\1#p')"
      if [ -n "$hook_file" ] && [ ! -f "$root/hooks/$hook_file" ]; then
        fail "hook file missing: $root/hooks/$hook_file"
      fi
    done < <(jq -r '.hooks[][]?.hooks[]?.command // empty' "$manifest" 2>/dev/null)
  else
    warn "cannot inspect manifest commands without jq: $manifest"
  fi
}

case "$PROVIDER" in
  codex) check_manifest "$PLUGIN_CHECK_ROOT/.codex-plugin/hooks/hooks.json" "$PLUGIN_CHECK_ROOT" ;;
  claude) check_manifest "$PLUGIN_CHECK_ROOT/hooks/hooks.json" "$PLUGIN_CHECK_ROOT" ;;
  *)
    [ -f "$PLUGIN_CHECK_ROOT/.codex-plugin/hooks/hooks.json" ] && check_manifest "$PLUGIN_CHECK_ROOT/.codex-plugin/hooks/hooks.json" "$PLUGIN_CHECK_ROOT"
    [ -f "$PLUGIN_CHECK_ROOT/hooks/hooks.json" ] && check_manifest "$PLUGIN_CHECK_ROOT/hooks/hooks.json" "$PLUGIN_CHECK_ROOT"
    [ "$PLUGIN_CHECK_ROOT" != "$ROOT" ] && [ -f "$ROOT/.codex-plugin/hooks/hooks.json" ] && check_manifest "$ROOT/.codex-plugin/hooks/hooks.json" "$ROOT"
    [ "$PLUGIN_CHECK_ROOT" != "$ROOT" ] && [ -f "$ROOT/hooks/hooks.json" ] && check_manifest "$ROOT/hooks/hooks.json" "$ROOT"
    ;;
esac

if [ "$FAILURES" -eq 0 ]; then
  printf 'RESULT PASS\n'
  exit 0
fi
printf 'RESULT BLOCKED failures=%s\n' "$FAILURES"
exit 1
