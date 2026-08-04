#!/usr/bin/env bash
# templates/init.sh — Long-running session bootstrap (Pattern 2).
#
# Verifies the environment, reads the feature list, picks the next
# failing feature, and records the baseline test result so the next
# session can resume without re-deriving it. Idempotent: safe to
# re-run on each session open.
#
# Exit codes (machine-readable; consumers branch on `$?`):
#   exit 0   — bootstrap complete; baseline test failures are recorded, not propagated
#   exit 2   — missing prerequisite (feature_list.json, tests dir, git)
#   exit 3   — no failing feature remaining (entire feature list is green)
#   exit 1   — generic failure (feature-list parse or git error)
#
# Designed to be invoked at the top of a >1-session task. Writes:
#   .session-baseline.json.baseline — last test output (for diff in session N+1)
#   .session-next-feature    — id of the next failing feature to work on
#
# Env overrides (all optional):
#   FEATURE_LIST   path to feature_list.json (default: ./feature_list.json)
#   TEST_CMD       pytest invocation (default: auto-detected)
#   DRY_RUN=1      print picks without writing files

set -eo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$REPO_ROOT"

# Default: feature list lives next to this script (templates/feature_list.json).
# When this script is symlinked or copied to a non-templates location, override
# via FEATURE_LIST=<path>.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FEATURE_LIST="${FEATURE_LIST:-${SCRIPT_DIR}/feature_list.json}"
TEST_CMD="${TEST_CMD:-}"
DRY_RUN="${DRY_RUN:-0}"

log() { printf '[init.sh] %s\n' "$*" >&2; }
die() { log "ERROR: $*"; exit "${2:-1}"; }

# ---- 1. Environment verification ----------------------------------------
command -v git >/dev/null 2>&1 || die "git not found in PATH" 2
command -v python3 >/dev/null 2>&1 || die "python3 not found in PATH" 2

[ -f "$FEATURE_LIST" ] || die "feature list not found at '$FEATURE_LIST' (set FEATURE_LIST)" 2

python3 -c "import json; json.load(open('$FEATURE_LIST'))" \
    || die "feature list is not valid JSON: $FEATURE_LIST" 2

if [ -z "$TEST_CMD" ]; then
  if [ -f "pytest.ini" ] || [ -d "tests" ]; then
    TEST_CMD="python3 -m pytest -q"
  else
    die "no tests/ dir or pytest.ini found; set TEST_CMD to override" 2
  fi
fi

log "feature list: $FEATURE_LIST"
log "test command: $TEST_CMD"

# ---- 2. Pick the next failing feature -----------------------------------
# A feature is "next" iff:
#   - status == "failing"
#   - every id in depends_on is "passing"
# Pick the lowest-id match so multiple agents working in parallel
# converge to the same answer.

NEXT_FEATURE="$(python3 - "$FEATURE_LIST" <<'PY'
import json, sys
path = sys.argv[1]
with open(path) as fh:
    features = json.load(fh)
by_id = {f["id"]: f for f in features}
remaining = []
for f in features:
    if f.get("status") != "failing":
        continue
    deps = f.get("depends_on") or []
    if all(by_id.get(d, {}).get("status") == "passing" for d in deps):
        remaining.append(f["id"])
if not remaining:
    sys.exit(3)
print(sorted(remaining)[0])
PY
)" || {
  rc=$?
  if [ "$rc" = "3" ]; then
    log "no failing feature remaining (entire list is green)"
    exit 3
  fi
  die "feature list parse failed" 1
}

log "next failing feature: $NEXT_FEATURE"

# ---- 3. Run the test suite to capture baseline --------------------------
if [ "$DRY_RUN" = "1" ]; then
  log "DRY_RUN=1: skipping test run and file writes"
  log "would have written: .session-baseline.json.baseline, .session-next-feature=$NEXT_FEATURE"
  exit 0
fi

log "running baseline tests: $TEST_CMD"
set +e
TEST_OUTPUT="$($TEST_CMD 2>&1)"
TEST_RC=$?
set -e

printf '%s\n' "$TEST_OUTPUT" > .session-baseline.json.baseline
printf '%s\n' "$NEXT_FEATURE" > .session-next-feature

log "baseline recorded (rc=$TEST_RC, output -> .session-baseline.json.baseline)"
log "next session: read .session-next-feature, work on '$NEXT_FEATURE'"
log "init.sh OK"
exit 0
