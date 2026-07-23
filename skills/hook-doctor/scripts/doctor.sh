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
  local command_text hook_file manifest_commands
  if [ ! -f "$manifest" ]; then
    fail "manifest missing: $manifest"
    return
  fi
  if ! command -v jq >/dev/null 2>&1; then
    fail "dependency missing: jq is required to inspect $manifest"
    return
  fi
  if ! manifest_commands="$(jq -er '.hooks[][]?.hooks[]?.command // empty' "$manifest" 2>/dev/null)"; then
    fail "manifest is not valid JSON or has an invalid hook shape: $manifest"
    return
  fi
  pass "manifest: $manifest"
  while IFS= read -r command_text; do
    [ -n "$command_text" ] || continue
    hook_file="$(printf '%s' "$command_text" | sed -nE 's#.*hooks/([^" ]+\.sh).*#\1#p')"
    if [ -n "$hook_file" ] && [ ! -f "$root/hooks/$hook_file" ]; then
      fail "hook file missing: $root/hooks/$hook_file"
    fi
  done <<< "$manifest_commands"
}

check_plugin_version() {
  local root="$1"
  local plugin_json=""
  local version cache_version
  for candidate in "$root/.codex-plugin/plugin.json" "$root/.claude-plugin/plugin.json"; do
    if [ -f "$candidate" ]; then
      plugin_json="$candidate"
      break
    fi
  done
  if [ -z "$plugin_json" ]; then
    fail "plugin version manifest missing under: $root"
    return
  fi
  if ! version="$(jq -er '.version // empty' "$plugin_json" 2>/dev/null)"; then
    fail "plugin version missing or malformed: $plugin_json"
    return
  fi
  pass "plugin version: $version ($plugin_json)"
  case "$root" in
    */plugins/cache/*)
      cache_version="${root##*/}"
      if [ "$cache_version" != "$version" ]; then
        fail "cache directory version $cache_version differs from plugin version $version"
      fi
      ;;
  esac
}

check_root() {
  local root="$1"
  local codex_manifest="$root/.codex-plugin/hooks/hooks.json"
  local claude_manifest="$root/hooks/hooks.json"
  local found=0
  if [ -f "$codex_manifest" ]; then
    check_manifest "$codex_manifest" "$root"
    found=1
  fi
  if [ -f "$claude_manifest" ]; then
    check_manifest "$claude_manifest" "$root"
    found=1
  fi
  if [ "$found" -eq 0 ]; then
    fail "no active provider hook manifest found under: $root"
    return
  fi
  check_plugin_version "$root"
}

case "$PROVIDER" in
  codex) check_manifest "$PLUGIN_CHECK_ROOT/.codex-plugin/hooks/hooks.json" "$PLUGIN_CHECK_ROOT"; check_plugin_version "$PLUGIN_CHECK_ROOT" ;;
  claude) check_manifest "$PLUGIN_CHECK_ROOT/hooks/hooks.json" "$PLUGIN_CHECK_ROOT"; check_plugin_version "$PLUGIN_CHECK_ROOT" ;;
  auto) check_root "$PLUGIN_CHECK_ROOT" ;;
  *) fail "unknown provider: $PROVIDER (use auto, codex, or claude)" ;;
esac

if [ "$FAILURES" -eq 0 ]; then
  printf 'RESULT PASS\n'
  exit 0
fi
printf 'RESULT BLOCKED failures=%s\n' "$FAILURES"
exit 1
