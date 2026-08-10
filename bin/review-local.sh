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
#                         Applied BEFORE the API key is resolved so the
#                         flag always wins, even on a process env that
#                         has the .env provider's key already loaded.
#   --auto-approve        Cast `gh pr review --approve` when combined
#                         verdict = Approve AND L3-evidence gate passes
#                         AND PR touches production code AND every
#                         enabled judge produced a parseable verdict.
#                         A missing/empty verdict REFUSES auto-approve
#                         (a gate that approves when its input is missing
#                         is worse than no gate). Default: OFF.
#   --review-only         Run only /dev-kit:review (skip security + maintenance).
#   --security-only       Run only /dev-kit:security.
#   --maintenance-only    Run only /dev-kit:maintenance.
#   --all                 Run all three (default).
#   --no-touch-probe      Treat every PR as production-touching (skip
#                         the auto-detect file-path probe) but STILL
#                         run the L3-evidence pytest-tail regex. The
#                         flag does not disable the gate; it disables
#                         only the upstream detection. Default: auto-detect.
#   --dry-run             Print the planned env + commands + verdict post
#                         WITHOUT invoking `claude` or `gh pr review`.
#                         Useful for CI-budget planning + smoke tests.
#   -h, --help            Show this help.
#
# Verdict extraction model:
#   The script captures each `claude -p "$prompt"` invocation's stdout
#   into a per-skill variable, then pipes that variable directly into
#   `python3 -m lib.maintenance_gate --extract-verdict-from-stdin`.
#   This is the same helper the workflow shells out to (so the
#   extractor stays single-sourced). It is more robust than reading
#   PR comments because local `claude -p` has no `claude[bot]` login
#   to filter on, and the workflow's per-job extraction relied on
#   temporal locality (each job's judge was its own "last comment")
#   which a sequential local run cannot replicate.
#
#   The agent still posts inline comments directly via `gh pr comment`
#   for the human reviewer; the captured stdout is for the gate only.
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

# shellcheck source=lib/review_local_lib.sh
. "$REPO_ROOT/lib/review_local_lib.sh"

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
#
# Order of resolution: --provider flag > CI_REVIEW_PROVIDER env >
# .env:CI_REVIEW_PROVIDER. The flag is read FIRST so the API key is
# resolved for the provider the operator actually wants (a previous
# bug resolved the .env provider's key and then silently swapped
# providers, leaking the wrong key to the wrong endpoint).
# ---------------------------------------------------------------------------
if [ -n "$PROVIDER_FLAG" ]; then
  PROVIDER="$PROVIDER_FLAG"
elif [ -n "${CI_REVIEW_PROVIDER:-}" ]; then
  PROVIDER="$CI_REVIEW_PROVIDER"
else
  PROVIDER="$(python3 -c "
import sys
from pathlib import Path
sys.path.insert(0, 'lib')
from ci_setup import read_provider
print(read_provider(Path('${REPO_ROOT}')))
")"
fi

case "$PROVIDER" in
  minimax|anthropic|deepseek) ;;
  *) die "invalid provider '$PROVIDER'; allowed: minimax, anthropic, deepseek (set via --provider or bin/set-provider.sh)" ;;
esac

# Resolve the provider's API key secret NAME by name (not by index) so a
# future reorder of lib/ci_setup.required_secrets_for_provider() cannot
# silently pick the wrong secret. The current tuple is
# (DEV_KIT_GITHUB_TOKEN, <PROVIDER>_API_KEY); we want the second one.
read_provider_api_key() {
  python3 -c "
import sys
from pathlib import Path
sys.path.insert(0, 'lib')
from ci_setup import read_env_key, required_secrets_for_provider
provider = '${PROVIDER}'
target = Path('${REPO_ROOT}')
for name in required_secrets_for_provider(provider):
    if name == 'DEV_KIT_GITHUB_TOKEN':
        continue
    v = read_env_key(target / '.env', name)
    if v:
        print(v)
        sys.exit(0)
print('')
"
}
API_KEY="$(read_provider_api_key)"

# Process env can override the .env lookup so a CI runner can pass the
# key via env: without writing to .env. Guard dropped intentionally:
# the documented use case is ".env has no key", which is the case where
# [ -n "$API_KEY" ] would be false. Without the guard, the env override
# only fires when the .env lookup also succeeded.
case "$PROVIDER" in
  minimax)   API_KEY="${MINIMAX_API_KEY:-$API_KEY}" ;;
  anthropic) API_KEY="${ANTHROPIC_API_KEY:-$API_KEY}" ;;
  deepseek)  API_KEY="${DEEPSEEK_API_KEY:-$API_KEY}" ;;
esac
[ -n "$API_KEY" ] || die "no API key for provider '$PROVIDER' (set .env:${PROVIDER^^}_API_KEY or env var)"

# ---------------------------------------------------------------------------
# 2. Per-provider base URL / model mapping (mirrors review.yml:120-131
#    + 175-181). The API KEY is NOT exported here -- it is scoped to the
#    single `claude -p` invocation via `env KEY=... claude -p ...` so the
#    key never enters the parent shell's persistent env (any subsequent
#    subprocess, /proc/<pid>/environ reader, or core dump cannot leak
#    it).
# ---------------------------------------------------------------------------
declare -a PROVIDER_ENV=()
case "$PROVIDER" in
  minimax)
    PROVIDER_ENV=(
      "ANTHROPIC_BASE_URL=https://api.minimax.io/anthropic"
      "ANTHROPIC_MODEL=MiniMax-M3[1m]"
      "ANTHROPIC_DEFAULT_SONNET_MODEL=MiniMax-M3[1m]"
      "ANTHROPIC_DEFAULT_OPUS_MODEL=MiniMax-M3[1m]"
      "ANTHROPIC_DEFAULT_HAIKU_MODEL=MiniMax-M3[1m]"
    )
    ;;
  deepseek)
    PROVIDER_ENV=(
      "ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic"
      "ANTHROPIC_MODEL=deepseek-v4-pro"
      "ANTHROPIC_DEFAULT_SONNET_MODEL=deepseek-v4-flash"
      "ANTHROPIC_DEFAULT_OPUS_MODEL=deepseek-v4-pro"
      "ANTHROPIC_DEFAULT_HAIKU_MODEL=deepseek-v4-flash"
    )
    ;;
  anthropic)
    : # Default Anthropic base URL; no MODEL override needed.
    ;;
esac

# Build the env prefix for a single `claude -p` invocation: provider
# base URL / model vars + the API key scoped to this process only.
# Guard against an empty PROVIDER_ENV (anthropic): `${ARR[@]:-}`
# expands to a single empty token on an empty array, which makes
# `env '' KEY=... cmd` fail because '' is not a valid VAR=.
claude_env_args=()
if [ "${#PROVIDER_ENV[@]}" -gt 0 ]; then
  claude_env_args+=("${PROVIDER_ENV[@]}")
fi
claude_env_args+=("ANTHROPIC_API_KEY=$API_KEY")
claude_env_args+=("ANTHROPIC_AUTH_TOKEN=$API_KEY")

# ---------------------------------------------------------------------------
# 3. Resolve PR metadata + bump-PR skip (mirrors review.yml:75).
# ---------------------------------------------------------------------------
PR_JSON="$(gh pr view "$PR_NUMBER" --json number,state,title,reviewDecision,body,files \
  --jq '{number, state, title, reviewDecision, body, files: [.files[].path]}' \
  2>/dev/null)" || die "gh pr view $PR_NUMBER failed (is gh authenticated? is the PR open?)"

# One python call returns all five fields -- cheaper than five separate
# `python3 -c` startups and avoids quote-handling per call.
read_pr_field() {
  python3 -c "
import json, sys
d = json.loads(sys.stdin.read())
key = sys.argv[1]
print(d.get(key) if key != 'files' else '\n'.join(d.get('files', [])))
" "$1"
}
PR_STATE="$(printf '%s' "$PR_JSON" | read_pr_field state)"
PR_TITLE="$(printf '%s' "$PR_JSON" | read_pr_field title)"
PR_DECISION="$(printf '%s' "$PR_JSON" | read_pr_field reviewDecision)"
PR_BODY="$(printf '%s' "$PR_JSON" | read_pr_field body)"
PR_FILES="$(printf '%s' "$PR_JSON" | read_pr_field files)"

if [ "$PR_STATE" != "OPEN" ]; then
  die "PR #$PR_NUMBER is $PR_STATE (must be OPEN)"
fi

# Bump-PR skip mirrors review.yml:75.
if [ "$(is_bump_pr "$PR_TITLE")" = "yes" ]; then
  log "bump-PR detected — skipping LLM judge (auto-pass per review.yml:75)"
  REPLY_BODY="<!-- dev-kit-verdict-audit --> run=local-$$ job=review-local status=success verdict=Approve source=bin_review_local (bump-PR skip)"
  if [ "$DRY_RUN" = "0" ]; then
    gh pr comment "$PR_NUMBER" --body "$REPLY_BODY" >/dev/null \
      || log "warning: gh pr comment failed (audit skipped)"
  else
    log "would post: $REPLY_BODY"
  fi
  exit 0
fi

# ---------------------------------------------------------------------------
# 4. Run the configured LLM-judge skills (mirrors review.yml:120-195).
#
# Each skill's stdout is captured into a per-skill variable so the
# verdict-extraction step (5) can pipe it directly into
# `lib.maintenance_gate --extract-verdict-from-stdin` without round-
# tripping through PR comments. The agent also posts inline comments
# directly via `gh pr comment` (the workflow's
# `mcp__github_inline_comment__create_inline_comment` is unavailable
# outside the claude-code-action; the agent adapter already supports
# `gh pr comment` per skills/review/SKILL.md).
# ---------------------------------------------------------------------------
REPO_FULL="$(gh repo view --json nameWithOwner -q .nameWithOwner)"

run_skill() {
  local skill="$1"
  local prompt="$2"
  log "running /$skill via provider=$PROVIDER (dry_run=$DRY_RUN)"
  if [ "$DRY_RUN" = "1" ]; then
    log "would run: env <$PROVIDER env+key> claude -p \"$prompt\""
    LAST_SKILL_STDOUT=""
    return 0
  fi
  # Capture stdout into LAST_SKILL_STDOUT AND echo to the operator's
  # terminal in real time so progress stays visible.
  local out
  out="$(env "${claude_env_args[@]}" claude -p "$prompt" 2>&1)" \
    || die "$skill: claude -p exited non-zero (review the output above)"
  LAST_SKILL_STDOUT="$out"
  printf '%s\n' "$out"
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
  REVIEW_OUTPUT="$LAST_SKILL_STDOUT"
fi

if [ "$RUN_SECURITY" = "1" ]; then
  run_skill "dev-kit:security" \
    "/dev-kit:security --diff $REPO_FULL/pull/$PR_NUMBER

Render the security summary (per-category breakdown table + Verdict).
The summary MUST begin with a single line exactly of the form:

  **Verdict:** Approve
  **Verdict:** Changes Requested
  **Verdict:** Blocked"
  SECURITY_OUTPUT="$LAST_SKILL_STDOUT"
fi

if [ "$RUN_MAINTENANCE" = "1" ]; then
  run_skill "dev-kit:maintenance" \
    "/dev-kit:maintenance --diff $REPO_FULL/pull/$PR_NUMBER

Apply the 20-checkbox code-sanity rubric (CC-1..8, OE-1..8, VM-1..4).
The summary MUST begin with a single line exactly of the form:

  **Verdict:** Approve
  **Verdict:** Changes Requested
  **Verdict:** Blocked"
  MAINTENANCE_OUTPUT="$LAST_SKILL_STDOUT"
fi

# ---------------------------------------------------------------------------
# 5. Extract verdicts from captured stdout (mirrors review.yml:220-225).
# ---------------------------------------------------------------------------
# Reuses the same helper the workflow shells out to: extracts the LAST
# `**Verdict:** <Word>` line from the captured judge output. Per-skill
# variables mean each judge is its own bucket, not three calls into the
# same PR-comment list.
extract_verdict() {
  printf '%s' "$1" | python3 -m lib.maintenance_gate --extract-verdict-from-stdin
}

REVIEW_V=""; SECURITY_V=""; MAINTENANCE_V=""
if [ "$DRY_RUN" = "1" ]; then
  log "would extract verdicts from captured stdout"
else
  [ "$RUN_REVIEW" = "1" ]      && REVIEW_V="$(extract_verdict "${REVIEW_OUTPUT:-}")"
  [ "$RUN_SECURITY" = "1" ]    && SECURITY_V="$(extract_verdict "${SECURITY_OUTPUT:-}")"
  [ "$RUN_MAINTENANCE" = "1" ] && MAINTENANCE_V="$(extract_verdict "${MAINTENANCE_OUTPUT:-}")"
fi
log "verdicts: review='${REVIEW_V:-<missing>}' security='${SECURITY_V:-<missing>}' maintenance='${MAINTENANCE_V:-<missing>}'"

# ---------------------------------------------------------------------------
# 6. Combined verdict gate (mirrors review.yml:539-561).
# ---------------------------------------------------------------------------
# `rank()` is sourced from lib/review_local_lib.sh (unit-tested in
# tests/test_review_local_lib.py).

# Default missing verdicts to Approve + warning (mirrors review.yml:521-522).
# This is the lenient workflow policy; the stricter --auto-approve gate
# below refuses on any missing verdict rather than synthesising one.
[ -z "$REVIEW_V" ]      && { log "warning: review verdict missing; defaulting to Approve"; REVIEW_V="Approve"; }
[ -z "$SECURITY_V" ]    && { log "warning: security verdict missing; defaulting to Approve"; SECURITY_V="Approve"; }
[ -z "$MAINTENANCE_V" ] && { log "warning: maintenance verdict missing; defaulting to Approve"; MAINTENANCE_V="Approve"; }

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
#
# `--no-touch-probe` disables the auto-detect (file-path regex) but
# still runs the L3 regex on the PR body -- the flag is a "treat every
# PR as production-touching" toggle, NOT a "skip the gate" toggle.
# Touch-probe regex covers every directory that ships production code,
# including `bin/` and `commands/` which were missing in the previous
# version.
# ---------------------------------------------------------------------------
L3_OK=1
TOUCHES_PROD=""
if [ "$TOUCH_PROBE" = "0" ]; then
  # --no-touch-probe: every PR is treated as production-touching so the
  # L3 evidence check ALWAYS runs. The flag's documented intent is
  # "treat every PR as a production-touching PR", which means stricter
  # gating, not bypass.
  TOUCHES_PROD="forced (--no-touch-probe)"
elif [ "$TOUCH_PROBE" = "1" ]; then
  TOUCHES_PROD="$(printf '%s\n' "$PR_FILES" | grep -E '^(bin|commands|lib|tools|hooks|skills|\.githooks|\.claude|\.codex|\.github)/' || true)"
fi
if [ -n "$TOUCHES_PROD" ]; then
  L3_PATTERN='[0-9]+ (passed|failed)(, [0-9]+ (skipped|xfailed|xpassed))? in [0-9.]+s'
  if printf '%s' "$PR_BODY" | grep -qE "$L3_PATTERN"; then
    log "L3 evidence: pytest tail line found in PR body"
  else
    L3_OK=0
    log "L3 evidence: pytest tail line MISSING in PR body (touches_prod=$TOUCHES_PROD)"
  fi
else
  log "L3 evidence: docs/infra-only PR; advisory only"
fi

# ---------------------------------------------------------------------------
# 8. Auto-approve (mirrors review.yml:609-618, only on the local opt-in).
#
# --auto-approve is strict: it refuses on ANY missing judge verdict
# (the lenient default-to-Approve above stays for non-auto-approve
# runs, mirroring review.yml's workflow-level contract). A gate that
# approves when its input is missing is worse than no gate.
# ---------------------------------------------------------------------------
if [ "$AUTO_APPROVE" = "1" ]; then
  # Check whether any enabled judge failed to produce a verdict.
  MISSING=""
  [ "$RUN_REVIEW" = "1" ]      && [ -z "${REVIEW_OUTPUT:-}" ]      && MISSING="${MISSING:-}review "
  [ "$RUN_SECURITY" = "1" ]    && [ -z "${SECURITY_OUTPUT:-}" ]    && MISSING="${MISSING:-}security "
  [ "$RUN_MAINTENANCE" = "1" ] && [ -z "${MAINTENANCE_OUTPUT:-}" ] && MISSING="${MISSING:-}maintenance "
  if [ -n "$MISSING" ]; then
    die "auto-approve refused: empty judge output for: $MISSING(a missing verdict must not synthesise an approval)"
  fi
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
      log "would run: gh pr review $PR_NUMBER --approve --body 'Auto-approved by bin/review-local.sh on clean combined verdict (review=$REVIEW_V security=$SECURITY_V maintenance=$MAINTENANCE_V touches_prod=$([ -n "$TOUCHES_PROD" ] && echo true || echo false) L3-passed=$L3_OK). The operator still owns the final merge step.'"
    else
      TOUCHES_PROD_FLAG=$([ -n "$TOUCHES_PROD" ] && echo true || echo false)
      gh pr review "$PR_NUMBER" --approve \
        --body "Auto-approved by bin/review-local.sh on clean combined verdict (review=$REVIEW_V security=$SECURITY_V maintenance=$MAINTENANCE_V touches_prod=$TOUCHES_PROD_FLAG L3-passed=$L3_OK). The operator still owns the final merge step." \
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
  "Changes"*) echo "error: Changes Requested (review=$REVIEW_V security=$SECURITY_V maintenance=$MAINTENANCE_V)" >&2; exit 1 ;;
  Blocked)   echo "error: Blocked (review=$REVIEW_V security=$SECURITY_V maintenance=$MAINTENANCE_V)" >&2; exit 1 ;;
  *)         echo "error: Unparseable verdict '$WORST'" >&2; exit 1 ;;
esac
