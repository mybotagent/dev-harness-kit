#!/usr/bin/env bash
# bin/babysit-pr-local.sh — single-call wrapper for /dev-kit:babysit-pr-local.
#
# Routes the iteration step that would normally call `gh pr checks --watch`
# (a GH-Actions wait) into `bin/review-local.sh --pr N` instead, so the
# local LLM-judge verdict (`/dev-kit:review` + `/dev-kit:security` +
# `/dev-kit:maintenance`) drives iteration in place of the GH-Actions
# review verdict. Saves GH-Actions minutes when a private repo has hit
# its monthly cap.
#
# Returns the verdict script's exit code:
#   0  = Approve  (loop terminates)
#   1  = Changes Requested or Blocked  (loop iterates)
#   2  = parse failure or operator error (loop exits 1)
#
# MUST-NO-SKIP: refuses any `--auto-approve` flag. The babysit variant
# never auto-merges; the operator runs `gh pr merge` manually after the
# audit comment shows `verdict=Approve`. This scan is enforced at three
# layers (wrapper arg scan + downstream script's own --auto-approve
# branch in `bin/review-local.sh` + audit trail in the comment body).
#
# Usage:
#   bin/babysit-pr-local.sh <PR_NUMBER>
#
# Example:
#   bin/babysit-pr-local.sh 605
set -euo pipefail

# --- arg validation ----------------------------------------------------
if [[ $# -lt 1 ]]; then
  echo "usage: $0 <PR_NUMBER>" >&2
  echo "       calls bin/review-local.sh --pr \$PR_NUMBER" >&2
  exit 2
fi

# MUST-NO-SKIP enforcement: refuse any --auto-appearing flag in argv
# BEFORE the numeric check. The --auto-approving refusal is the
# primary defense; running the numeric check first would surface
# `--auto-approve 123` as "PR_NUMBER must be numeric" instead of the
# clear "auto-approve forbidden" message operators need.
# bin/review-local.sh also refuses the flag as a belt-and-suspenders
# backstop.
for arg in "$@"; do
  case "$arg" in
    --auto-approve|--auto|--approve)
      echo "error: babysit-pr-local must NOT pass $arg to review-local.sh" >&2
      echo "       (operator-driven merging is the contract;" >&2
      echo "        use bin/review-local.sh --auto-approve directly)" >&2
      exit 2
      ;;
  esac
done

PR_NUMBER="$1"

if ! [[ "$PR_NUMBER" =~ ^[0-9]+$ ]]; then
  echo "error: PR_NUMBER must be numeric (got '$PR_NUMBER')" >&2
  exit 2
fi

# --- delegate to bin/review-local.sh -----------------------------------
# SCRIPT_DIR resolves to the directory holding THIS script at runtime,
# so the lookup stays valid when the wrapper is invoked from any cwd.
# `exec` replaces the wrapper process with the downstream script; the
# downstream's exit code becomes the wrapper's exit code 1:1, so the
# babysit iteration loop's TERMINATE / iterate branches fire
# deterministically (exit 0 = Approve / exit 1 = Changes|Blocked).
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
exec "$SCRIPT_DIR/review-local.sh" --pr "$PR_NUMBER"
