#!/usr/bin/env bash
# log-status.sh — report current loghooks install state for the target project.
#
# Reports, per target file:
#   - whether the file exists
#   - how many entries are tagged _loghooks_managed=true
#   - whether tools/save_log.py is in place
#   - how many transcript files (.jsonl) have been captured

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

usage() {
    cat <<EOF
Usage: $(basename "$0") [--target DIR]

Prints the install state of loghooks in the target project:
  * .claude/settings.json — managed entry count
  * .codex/hooks.json     — managed entry count
  * tools/save_log.py     — present? executable?
  * logs/                 — captured transcript count per subdir

Env:
  TARGET_DIR     target project (default: \$PWD)
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --target) TARGET_DIR="$2"; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) echo "ERROR: unknown arg: $1" >&2; usage; exit 1 ;;
    esac
done

require_jq
TARGET_DIR="$(resolve_target_dir)"

printf 'project: %s\n\n' "$TARGET_DIR"

report_file() {
    local label="$1" path="$2"
    if [[ ! -f "$path" ]]; then
        printf '  %-9s %-44s  (not present)\n' "$label" "$path"
        return
    fi
    local n
    n="$(count_managed "$path")"
    printf '  %-9s %-44s  managed=%d\n' "$label" "$path" "$n"
}

report_file "claude:" "$TARGET_DIR/.claude/settings.json"
report_file "codex: " "$TARGET_DIR/.codex/hooks.json"

# setup artifacts
SETUP_PY="$TARGET_DIR/tools/save_log.py"
if [[ -x "$SETUP_PY" ]]; then
    printf '  setup:    %-44s  OK (executable)\n' "$SETUP_PY"
elif [[ -f "$SETUP_PY" ]]; then
    printf '  setup:    %-44s  WARN (not executable)\n' "$SETUP_PY"
else
    printf '  setup:    %-44s  MISSING — run /dev-kit:log setup\n' "$SETUP_PY"
fi

# captured transcripts (shell loop, no fork to find; tolerates any filename)
for sub in claude-code codex; do
    D="$TARGET_DIR/logs/$sub"
    if [[ -d "$D" ]]; then
        n=0
        for f in "$D"/*.jsonl; do
            [[ -f "$f" ]] || continue
            n=$((n + 1))
        done
        printf '  logs:     %-44s  captured=%d\n' "$D/" "$n"
    fi
done