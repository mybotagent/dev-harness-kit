#!/usr/bin/env bash
# review-local.sh — Local equivalent of the GH-Actions review + maintenance
# workflow orchestration. Saves Action minutes when private repos hit
# the GH-Actions budget cap; same verdict extraction + combined gate +
# L3-evidence check + auto-approve as `review.yml` + `maintenance.yml`.
#
# This script is ADDITIVE: the GH-Actions workflows are unchanged. Use
# this when you want to run the same review pipeline locally without
# consuming a GitHub Actions run.
#
# Usage:
#   bin/review-local.sh --pr N
#   bin/review-local.sh --pr N --provider anthropic
#   bin/review-local.sh --pr N --auto-approve
#   bin/review-local.sh --pr N --review-only
#   bin/review-local.sh --pr N --maintenance-only --dry-run
#   bin/review-local.sh --help
#
# Flags:
#   --pr N                PR number to review (required).
#   --provider NAME       minimax | anthropic | deepseek (default: from
#                         .env:CI_REVIEW_PROVIDER via lib/ci_setup.read_provider).
#   --auto-approve        Cast `gh pr review --approve` when combined
#                         verdict = Approve AND L3-evidence gate passes
#                         AND PR touches production code. Default: OFF.
#   --review-only         Run only /dev-kit:review (skip security + maintenance).
#   --security-only       Run only /dev-kit:security.
#   --maintenance-only    Run only /dev-kit:maintenance.
#   --all                 Run all three (default).
#   --no-touch-probe      Skip the touch-probe sub-check (treat every PR
#                         as a production-touching PR). Default: auto-detect.
#   --dry-run             Print the planned env + commands + verdict post
#                         WITHOUT invoking `claude` or `gh pr review`.
#                         Useful for CI-budget planning + smoke tests.
#   -h, --help            Show this help.
#
# Provider switch (matches bin/set-provider.sh + the workflow's choice
# list). The corresponding API key must be in `.env` or the process env
# under the key name `lib/ci_setup.required_secrets_for_provider()` returns,
# e.g. `MINIMAX_API_KEY` / `ANTHROPIC_API_KEY` / `DEEPSEEK_API_KEY`.

set -euo pipefail

# ---------------------------------------------------------------------------
# Repo root + helpers.
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && git rev-parse --show-toplevel 2>/dev/null)" \
  || { echo "error: not in a git repo" >&2; exit 1; }
cd "$REPO_ROOT"

die() { echo "error: $*" >&2; exit 1; }
log() { echo "  $*"; }

usage() {
  sed -n '2,/^$/p' "$0" | sed 's/^# \?//'
}

# ---------------------------------------------------------------------------
# Arg parsing.
# ---------------------------------------------------------------------------
PR_NUMBER=""
PROVIDER_FLAG=""
AUTO_APPROVE=0
TOUCH_PROBE=1
DRY_RUN=0
RUN_REVIEW=1
RUN_SECURITY=1
RUN_MAINTENANCE=1

while [ $# -gt 0 ]; do
  case "$1" in
    --pr)               [ $# -ge 2 ] || die "--pr requires N"; PR_NUMBER="$2"; shift 2 ;;
    --provider)         [ $# -ge 2 ] || die "--provider requires name"; PROVIDER_FLAG="$2"; shift 2 ;;
    --auto-approve)     AUTO_APPROVE=1; shift ;;
    --no-touch-probe)   TOUCH_PROBE=0; shift ;;
    --dry-run)          DRY_RUN=1; shift ;;
    --review-only)      RUN_SECURITY=0; RUN_MAINTENANCE=0; shift ;;
    --security-only)    RUN_REVIEW=0; RUN_MAINTENANCE=0; shift ;;
    --maintenance-only) RUN_REVIEW=0; RUN_SECURITY=0; shift ;;
    --all)              RUN_REVIEW=1; RUN_SECURITY=1; RUN_MAINTENANCE=1; shift ;;
    -h|--help)          usage; exit 0 ;;
    *)                  die "unknown flag: $1 (try --help)" ;;
  esac
done

[ -n "$PR_NUMBER" ] || die "missing --pr N"
case "$PR_NUMBER" in
  *[!0-9]*) die "--pr must be numeric: '$PR_NUMBER'" ;;
esac

# ---------------------------------------------------------------------------
# 1. Resolve provider + read API key (mirrors review.yml:99-117).
# ---------------------------------------------------------------------------
PROVIDER_INFO="$(python3 - <<PY
import sys
from pathlib import Path
sys.path.insert(0, str(Path("$REPO_ROOT") / "lib"))
from ci_setup import read_provider, read_env_key, required_secrets_for_provider
target = Path("$REPO_ROOT")
p = read_provider(target)
key = read_env_key(target / ".env", required_secrets_for_provider(p)[-1])
print(p)
print(key)
PY
)"
PROVIDER="$(printf '%s\n' "$PROVIDER_INFO" | sed -n '1p')"
API_KEY="$(printf '%s\n' "$PROVIDER_INFO" | sed -n '2p')"

# CLI flag overrides the .env resolution.
if [ -n "$PROVIDER_FLAG" ]; then
  PROVIDER="$PROVIDER_FLAG"
fi

case "$PROVIDER" in
  minimax|anthropic|deepseek) ;;
  *) die "invalid provider '$PROVIDER'; allowed: minimax, anthropic, deepseek (set via --provider or bin/set-provider.sh)" ;;
esac

# Process env can override the .env lookup so a CI runner can pass the
# key via env: without writing to .env.
case "$PROVIDER" in
  minimax)   [ -n "$API_KEY" ] && API_KEY="${MINIMAX_API_KEY:-$API_KEY}" ;;
  anthropic) [ -n "$API_KEY" ] && API_KEY="${ANTHROPIC_API_KEY:-$API_KEY}" ;;
  deepseek)  [ -n "$API_KEY" ] && API_KEY="${DEEPSEEK_API_KEY:-$API_KEY}" ;;
esac
[ -n "$API_KEY" ] || die "no API key for provider '$PROVIDER' (set .env:${PROVIDER^^}_API_KEY or env var)"

# ---------------------------------------------------------------------------
# 2. Per-provider env mapping (mirrors review.yml:120-131 + 175-181).
# ---------------------------------------------------------------------------
case "$PROVIDER" in
  minimax)
    export ANTHROPIC_BASE_URL="https://api.minimax.io/anthropic"
    export ANTHROPIC_MODEL="MiniMax-M3[1m]"
    export ANTHROPIC_DEFAULT_SONNET_MODEL="MiniMax-M3[1m]"
    export ANTHROPIC_DEFAULT_OPUS_MODEL="MiniMax-M3[1m]"
    export ANTHROPIC_DEFAULT_HAIKU_MODEL="MiniMax-M3[1m]"
    ;;
  deepseek)
    export ANTHROPIC_BASE_URL="https://api.deepseek.com/anthropic"
    export ANTHROPIC_MODEL="deepseek-v4-pro"
    export ANTHROPIC_DEFAULT_SONNET_MODEL="deepseek-v4-flash"
    export ANTHROPIC_DEFAULT_OPUS_MODEL="deepseek-v4-pro"
    export ANTHROPIC_DEFAULT_HAIKU_MODEL="deepseek-v4-flash"
    ;;
  anthropic)
    : # Default Anthropic base URL; no MODEL override needed.
    ;;
esac
export ANTHROPIC_API_KEY="$API_KEY"
export ANTHROPIC_AUTH_TOKEN="$API_KEY"

# ---------------------------------------------------------------------------
# 3. Resolve PR metadata + bump-PR skip (mirrors review.yml:75).
# ---------------------------------------------------------------------------
PR_JSON="$(gh pr view "$PR_NUMBER" --json number,state,title,reviewDecision,body,files \
  --jq '{number, state, title, reviewDecision, body, files: [.files[].path]}' \
  2>/dev/null)" || die "gh pr view $PR_NUMBER failed (is gh authenticated? is the PR open?)"

PR_STATE="$(printf '%s' "$PR_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["state"])')"
PR_TITLE="$(printf '%s' "$PR_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["title"])')"
PR_DECISION="$(printf '%s' "$PR_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("reviewDecision") or "")')"
PR_BODY="$(printf '%s' "$PR_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("body") or "")')"
PR_FILES="$(printf '%s' "$PR_JSON" | python3 -c 'import json,sys; print("\n".join(json.load(sys.stdin)["files"]))')"

if [ "$PR_STATE" != "OPEN" ]; then
  die "PR #$PR_NUMBER is $PR_STATE (must be OPEN)"
fi

# Bump-PR skip mirrors review.yml:75.
if [[ "$PR_TITLE" == "chore(release): bump dev-kit to v"* ]]; then
  log "bump-PR detected — skipping LLM judge (auto-pass per review.yml:75)"
  REPLY_BODY="<!-- dev-kit-verdict-audit --> run=local-$$ job=review status=success verdict=Approve source=bin_review_local (bump-PR skip)"
  if [ "$DRY_RUN" = "0" ]; then
    gh pr comment "$PR_NUMBER" --body "$REPLY_BODY" >/dev/null
  else
    log "would post: $REPLY_BODY"
  fi
  exit 0
fi

# ---------------------------------------------------------------------------
# 4. Run the configured LLM-judge skills (mirrors review.yml:120-195).
# ---------------------------------------------------------------------------
REPO_FULL="$(gh repo view --json nameWithOwner -q .nameWithOwner)"

run_skill() {
  local skill="$1"
  local prompt="$2"
  log "running /$skill via provider=$PROVIDER (dry_run=$DRY_RUN)"
  if [ "$DRY_RUN" = "1" ]; then
    log "would run: claude -p \"$prompt\""
    return 0
  fi
  # `claude -p` reads stdin for one-shot prompts and writes the agent's
  # output to stdout. The skill body posts inline comments via `gh pr
  # comment` (the workflow's `mcp__github_inline_comment__create_inline_comment`
  # is unavailable outside the claude-code-action; the agent adapter
  # already supports `gh pr comment` per skills/review/SKILL.md).
  claude -p "$prompt"
}

if [ "$RUN_REVIEW" = "1" ]; then
  run_skill "dev-kit:review" \
    "/dev-kit:review --diff $REPO_FULL/pull/$PR_NUMBER

Render the standard two-layer output (PR summary at top, per-finding
inline comments). The summary MUST begin with a single line exactly
of the form:

  **Verdict:** Approve
  **Verdict:** Changes Requested
  **Verdict:** Blocked

Map verdict strictly to severity (do NOT inflate):
  - critical >= 1     -> **Verdict:** Blocked
  - major >= 1, critical = 0 -> **Verdict:** Changes Requested
  - no critical, no major -> **Verdict:** Approve"
fi

if [ "$RUN_SECURITY" = "1" ]; then
  run_skill "dev-kit:security" \
    "/dev-kit:security --diff $REPO_FULL/pull/$PR_NUMBER

Render the security summary (per-category breakdown table + Verdict).
The summary MUST begin with a single line exactly of the form:

  **Verdict:** Approve
  **Verdict:** Changes Requested
  **Verdict:** Blocked"
fi

if [ "$RUN_MAINTENANCE" = "1" ]; then
  run_skill "dev-kit:maintenance" \
    "/dev-kit:maintenance --diff $REPO_FULL/pull/$PR_NUMBER

Apply the 20-checkbox code-sanity rubric (CC-1..8, OE-1..8, VM-1..4).
The summary MUST begin with a single line exactly of the form:

  **Verdict:** Approve
  **Verdict:** Changes Requested
  **Verdict:** Blocked"
fi

# ---------------------------------------------------------------------------
# 5. Extract verdicts from claude[bot] PR comments (mirrors review.yml:220-225).
# ---------------------------------------------------------------------------
# Reuses the same helper the workflow shells out to: extracts the LAST
# `**Verdict:** <Word>` line from the most recent claude[bot] comment
# whose body contains `**Verdict:**`. Pagination preserves correctness
# on PRs with > 30 comments.
PAGINATED="$(gh api "repos/$REPO_FULL/issues/$PR_NUMBER/comments" --paginate --slurp 2>/dev/null)" \
  || die "gh api comments failed for PR #$PR_NUMBER"

last_verdict() {
  local label="$1"
  printf '%s' "$PAGINATED" | jq -r --arg label "$label" '
    [ .[] | .[]? | select((.user.login // "") | startswith("claude"))
            | select(.body | test("\\*\\*Verdict:\\*\\*"))
            | {body: .body, updated_at: .updated_at} ]
    | sort_by(.updated_at) | .[-1].body // ""' \
    | python3 -m lib.maintenance_gate --extract-verdict-from-stdin
}

if [ "$DRY_RUN" = "1" ]; then
  log "would extract verdicts from PR comments"
  REVIEW_V=""; SECURITY_V=""; MAINTENANCE_V=""
else
  REVIEW_V=""; SECURITY_V=""; MAINTENANCE_V=""
  [ "$RUN_REVIEW" = "1" ]      && REVIEW_V="$(last_verdict review)"
  [ "$RUN_SECURITY" = "1" ]    && SECURITY_V="$(last_verdict security)"
  [ "$RUN_MAINTENANCE" = "1" ] && MAINTENANCE_V="$(last_verdict maintenance)"
fi
log "verdicts: review='${REVIEW_V:-<missing>}' security='${SECURITY_V:-<missing>}' maintenance='${MAINTENANCE_V:-<missing>}'"

# ---------------------------------------------------------------------------
# 6. Combined verdict gate (mirrors review.yml:539-561).
# ---------------------------------------------------------------------------
rank() {
  case "$1" in
    Blocked) echo 2 ;;
    "Changes"*) echo 1 ;;
    Approve) echo 0 ;;
    *) echo 99 ;;
  esac
}

# Default missing verdicts to Approve + warning (mirrors review.yml:521-522).
[ -z "$REVIEW_V" ]      && { log "::warning::review verdict missing; defaulting to Approve"; REVIEW_V="Approve"; }
[ -z "$SECURITY_V" ]    && { log "::warning::security verdict missing; defaulting to Approve"; SECURITY_V="Approve"; }
[ -z "$MAINTENANCE_V" ] && { log "::warning::maintenance verdict missing; defaulting to Approve"; MAINTENANCE_V="Approve"; }

# PARSE_FAILED → hard fail (mirrors review.yml:528-536).
if [ "$REVIEW_V" = "PARSE_FAILED" ] || [ "$SECURITY_V" = "PARSE_FAILED" ] || [ "$MAINTENANCE_V" = "PARSE_FAILED" ]; then
  die "verdict parser failed: review=$REVIEW_V security=$SECURITY_V maintenance=$MAINTENANCE_V"
fi

# Worst-of wins across the enabled skills.
WORST="Approve"
V_RANK=0
for V in "$REVIEW_V" "$SECURITY_V" "$MAINTENANCE_V"; do
  R=$(rank "$V")
  if [ "$R" -gt "$V_RANK" ]; then V_RANK="$R"; WORST="$V"; fi
done
log "combined verdict: $WORST"

# ---------------------------------------------------------------------------
# 7. L3-evidence gate (mirrors review.yml:471-491).
# ---------------------------------------------------------------------------
L3_OK=1
if [ "$TOUCH_PROBE" = "1" ]; then
  TOUCHES_PROD="$(printf '%s\n' "$PR_FILES" | grep -E '^(lib|tools|hooks|skills|\.githooks|\.claude|\.codex|\.github)/' || true)"
  if [ -n "$TOUCHES_PROD" ]; then
    L3_PATTERN='[0-9]+ (passed|failed)(, [0-9]+ (skipped|xfailed|xpassed))? in [0-9.]+s'
    if printf '%s' "$PR_BODY" | grep -qE "$L3_PATTERN"; then
      log "L3 evidence: pytest tail line found in PR body"
    else
      L3_OK=0
      log "L3 evidence: pytest tail line MISSING in PR body (touches_prod=true)"
    fi
  else
    log "L3 evidence: docs/infra-only PR; advisory only"
  fi
fi

# ---------------------------------------------------------------------------
# 8. Auto-approve (mirrors review.yml:609-618, only on the local opt-in).
# ---------------------------------------------------------------------------
if [ "$AUTO_APPROVE" = "1" ]; then
  if [ "$WORST" != "Approve" ]; then
    die "auto-approve refused: combined verdict=$WORST (must be Approve)"
  fi
  if [ "$L3_OK" != "1" ]; then
    die "auto-approve refused: L3-evidence gate failed (PR body lacks pytest tail line)"
  fi
  if [ "$PR_DECISION" = "APPROVED" ]; then
    log "PR already APPROVED; skipping auto-approve (idempotent)"
  else
    if [ "$DRY_RUN" = "1" ]; then
      log "would run: gh pr review $PR_NUMBER --approve --body 'Auto-approved by review-local.sh on clean combined verdict.'"
    else
      gh pr review "$PR_NUMBER" --approve \
        --body "Auto-approved by bin/review-local.sh on clean combined verdict (review=$REVIEW_V security=$SECURITY_V maintenance=$MAINTENANCE_V touches_prod=$( [ "$TOUCH_PROBE" = "1" ] && [ -n "$TOUCHES_PROD" ] && echo true || echo false ) L3-passed=$L3_OK). The operator still owns the final merge step." \
        || die "gh pr review --approve failed"
      log "auto-approve posted for PR #$PR_NUMBER"
    fi
  fi
else
  log "auto-approve not requested (pass --auto-approve to enable)"
fi

# ---------------------------------------------------------------------------
# 9. Audit comment (mirrors review.yml:226-227).
# ---------------------------------------------------------------------------
AUDIT_BODY="<!-- dev-kit-verdict-audit --> run=local-$$ job=review-local status=success verdict=$WORST review=$REVIEW_V security=$SECURITY_V maintenance=$MAINTENANCE_V provider=$PROVIDER source=bin_review_local"
if [ "$DRY_RUN" = "1" ]; then
  log "would post: $AUDIT_BODY"
else
  gh pr comment "$PR_NUMBER" --body "$AUDIT_BODY" >/dev/null \
    || log "warning: gh pr comment failed (audit skipped)"
fi

# ---------------------------------------------------------------------------
# 10. Final exit (mirrors review.yml:557-561).
# ---------------------------------------------------------------------------
case "$WORST" in
  Approve) exit 0 ;;
  "Changes"*) echo "::error::Changes Requested (review=$REVIEW_V security=$SECURITY_V maintenance=$MAINTENANCE_V)" >&2; exit 1 ;;
  Blocked)   echo "::error::Blocked (review=$REVIEW_V security=$SECURITY_V maintenance=$MAINTENANCE_V)" >&2; exit 1 ;;
  *)         echo "::error::Unparseable verdict '$WORST'" >&2; exit 1 ;;
esac
