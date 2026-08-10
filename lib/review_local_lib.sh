#!/usr/bin/env bash
# review_local_lib.sh — Pure-bash helpers sourced by bin/review-local.sh.
#
# Extracted from bin/review-local.sh so the worst-of rank, the L3
# pytest-tail regex, and the bump-PR title skip can be unit-tested
# hermetically (no `gh` / `claude` / network). Tests source this file
# directly via `bash -c 'source lib/review_local_lib.sh; ...'`.
#
# Functions (all pure; no I/O, no global state mutation beyond the
# declared variables each function reads):
#
#   rank <verdict>
#       Print 0 for Approve, 1 for Changes*, 2 for Blocked, 99 for
#       anything else (unparseable). Mirrors the workflow's combined
#       gate at review.yml:539-561.
#
#   is_bump_pr <pr_title>
#       Print "yes" if the title matches `chore(release): bump dev-kit
#       to v*`, else "no". Mirrors review.yml:75.
#
#   extract_pytest_tail < body
#       Print "yes" if the body contains a pytest tail line
#       (`<N> passed|failed ... in <Ns>s`), else "no". Used by the
#       L3-evidence gate.
#
#   provider_env_for <provider>
#       Print `KEY=VAL` lines (one per line, no `export`) for the
#       provider's ANTHROPIC_* mapping. Empty for anthropic (default).
#
#   verdict_default_for <verdict_var>
#       Print "yes" if the variable is empty/unset (i.e. the lenient
#       default-to-Approve policy should apply), else "no". Mirrors
#       review.yml:521-522.

# Guard against double-sourcing in test runners.
if [ -n "${REVIEW_LOCAL_LIB_SOURCED:-}" ]; then
  return 0
fi
REVIEW_LOCAL_LIB_SOURCED=1

rank() {
  case "$1" in
    Blocked) echo 2 ;;
    "Changes"*) echo 1 ;;
    Approve) echo 0 ;;
    *) echo 99 ;;
  esac
}

is_bump_pr() {
  case "$1" in
    "chore(release): bump dev-kit to v"*) echo yes ;;
    *) echo no ;;
  esac
}

extract_pytest_tail() {
  # POSIX-portable: no `[[ ... =~ ... ]]`. Use grep -E for portability.
  if printf '%s' "$1" | grep -qE '[0-9]+ (passed|failed)(, [0-9]+ (skipped|xfailed|xpassed))? in [0-9.]+s'; then
    echo yes
  else
    echo no
  fi
}

provider_env_for() {
  case "$1" in
    minimax)
      printf '%s\n' \
        "ANTHROPIC_BASE_URL=https://api.minimax.io/anthropic" \
        "ANTHROPIC_MODEL=MiniMax-M3[1m]" \
        "ANTHROPIC_DEFAULT_SONNET_MODEL=MiniMax-M3[1m]" \
        "ANTHROPIC_DEFAULT_OPUS_MODEL=MiniMax-M3[1m]" \
        "ANTHROPIC_DEFAULT_HAIKU_MODEL=MiniMax-M3[1m]"
      ;;
    deepseek)
      printf '%s\n' \
        "ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic" \
        "ANTHROPIC_MODEL=deepseek-v4-pro" \
        "ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-flash" \
        "ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro" \
        "ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash"
      ;;
    anthropic)
      : # Default Anthropic base URL; no override needed.
      ;;
    *)
      return 1
      ;;
  esac
}

verdict_default_for() {
  if [ -z "${1:-}" ]; then
    echo yes
  else
    echo no
  fi
}
