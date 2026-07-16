#!/usr/bin/env bash
# set-provider.sh — switch the CI review/security provider explicitly.
#
# Why: previous design auto-rewrote .github/ci-review-provider.txt from
# .env on every commit (via .githooks/pre-commit). That behavior silently
# inverted user intent: a worktree whose .env disagreed with the main
# checkout's .env would flip the tracked file with no abort and no clear
# signal. This helper replaces that with an explicit, user-initiated
# switch — review the diff, then commit + push yourself.
#
# Usage:
#   bin/set-provider.sh                          # show current provider
#   bin/set-provider.sh minimax                  # set provider
#   bin/set-provider.sh anthropic --dry-run      # show what would change
#   bin/set-provider.sh --show                   # alias for no-arg form
#   bin/set-provider.sh --help
#
# Allowlist: minimax, anthropic, deepseek (must match the choice list
# declared in .github/workflows/review.yml -> workflow_dispatch.inputs).
#
# The matching *_API_KEY secret must be set on the GitHub repo before CI
# can actually use a given provider:
#   gh secret set MINIMAX_API_KEY    --body "<value>"
#   gh secret set ANTHROPIC_API_KEY  --body "<value>"
#   gh secret set DEEPSEEK_API_KEY   --body "<value>"

set -euo pipefail

PROVIDER_FILE=".github/ci-review-provider.txt"
ALLOWLIST=(minimax anthropic deepseek)
DEFAULT_PROVIDER="minimax"

die() { echo "error: $*" >&2; exit 1; }

show_help() {
  sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
}

# Initialize the file to default if it doesn't exist yet (first-time
# setup). Idempotent — never overwrites an existing value.
ensure_file() {
  if [ ! -f "$PROVIDER_FILE" ]; then
    echo "$DEFAULT_PROVIDER" > "$PROVIDER_FILE"
    echo "created $PROVIDER_FILE with default: $DEFAULT_PROVIDER"
  fi
}

current_provider() {
  if [ -f "$PROVIDER_FILE" ]; then
    tr -d '[:space:]' < "$PROVIDER_FILE"
  else
    echo "(unset)"
  fi
}

is_allowed() {
  local p="$1"
  for a in "${ALLOWLIST[@]}"; do
    [ "$p" = "$a" ] && return 0
  done
  return 1
}

# Parse args. Support provider as first positional, then flags.
PROVIDER_ARG=""
DRY_RUN=0
SHOW_ONLY=0

if [ $# -eq 0 ]; then
  SHOW_ONLY=1
else
  case "$1" in
    -h|--help) show_help; exit 0 ;;
    --show)    SHOW_ONLY=1 ;;
    --dry-run) DRY_RUN=1; PROVIDER_ARG="${2:-}"; [ -n "$PROVIDER_ARG" ] || die "--dry-run requires a provider name" ;;
    -*)        die "unknown flag: $1 (try --help)" ;;
    *)         PROVIDER_ARG="$1"
               # Allow --dry-run as second arg too.
               if [ $# -ge 2 ] && [ "${2:-}" = "--dry-run" ]; then DRY_RUN=1; fi ;;
  esac
fi

# Resolve repo root (works in main checkout and worktrees alike).
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || die "not inside a git repo"
cd "$REPO_ROOT"

if [ "$SHOW_ONLY" = "1" ]; then
  ensure_file
  echo "current: $(current_provider)"
  echo "file:    $PROVIDER_FILE"
  echo "allowlist: ${ALLOWLIST[*]}"
  echo "to switch: bin/set-provider.sh <provider>"
  exit 0
fi

# Switch path: validate first, fail fast.
is_allowed "$PROVIDER_ARG" || die "invalid provider '$PROVIDER_ARG'; allowed: ${ALLOWLIST[*]}"

CURRENT="$(current_provider)"
NEW="$PROVIDER_ARG"

if [ "$CURRENT" = "$NEW" ]; then
  echo "already $NEW; nothing to do."
  exit 0
fi

echo "current: $CURRENT"
echo "new:     $NEW"
echo

if [ "$DRY_RUN" = "1" ]; then
  echo "[dry-run] would update $PROVIDER_FILE"
  echo "[dry-run] would print this diff (vs HEAD):"
  TMP="$(mktemp)"
  trap 'rm -f "$TMP"' EXIT
  echo "$NEW" > "$TMP"
  git diff --no-index --no-color "$PROVIDER_FILE" "$TMP" 2>/dev/null | sed 's/^/[dry-run] /' || true
  exit 0
fi

# Apply the change. Print the diff vs HEAD so the user reviews before
# committing. Don't auto-commit or push — that's the user's call.
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
echo "$NEW" > "$TMP"
mv "$TMP" "$PROVIDER_FILE"
trap - EXIT

echo "diff vs HEAD:"
git diff --no-color "$PROVIDER_FILE" | sed 's/^/  /'
echo
echo "next steps:"
echo "  git add $PROVIDER_FILE"
echo "  git commit -m \"ci(provider): switch $CURRENT -> $NEW\""
echo "  git push"
echo
echo "reminder: ensure $NEW's *_API_KEY is set as a GitHub repo secret:"
case "$NEW" in
  minimax)   echo "  gh secret set MINIMAX_API_KEY   --body '<value>'" ;;
  anthropic) echo "  gh secret set ANTHROPIC_API_KEY --body '<value>'" ;;
  deepseek)  echo "  gh secret set DEEPSEEK_API_KEY  --body '<value>'" ;;
esac