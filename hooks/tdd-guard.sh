#!/usr/bin/env bash
# tdd-guard.sh — PreToolUse hook. Blocks prod code edits without adjacent test file.
# MUST-L1 / MUST-12: advisory mode by default (exit 0). Hard-block (exit 2) only with --strict.
#
# Adapted from dev-harness/.claude/hooks/tdd-guard.sh (sh-ai-x/dev-harness).

set -eo pipefail
INPUT=$(cat)
FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // ""' 2>/dev/null)
[ -z "$FILE" ] && exit 0
case "$FILE" in
  *.md|*.txt|*.json|*.yaml|*.yml|*.toml|*.cfg|*.ini|*.sh|*.md) exit 0 ;;
esac

# Enforce paths
case "$FILE" in
  */lib/*|*/app/api/*|*/src/lib/*|*/src/utils/*|*/src/services/*|*/src/domain/*|*/utils/*|*/services/*|*/domain/*)
    BASENAME=$(basename "$FILE")
    DIR=$(dirname "$FILE")
    TEST_GLOB=("${DIR}/tests/test_${BASENAME%.*}.py" "${DIR}/test_${BASENAME%.*}.py" "${DIR}/${BASENAME%.*}.test.py" "${DIR}/${BASENAME%.*}.spec.py" "../tests/test_${BASENAME%.*}.py" "../../tests/test_${BASENAME%.*}.py")
    for f in "${TEST_GLOB[@]}"; do
      [ -e "$f" ] && exit 0
    done
    # Strict mode → hard block
    if [ "${DEV_KIT_STRICT:-0}" = "1" ]; then
      echo "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"TDD GUARD (strict): '${FILE}'에 대한 테스트 파일이 없습니다.\"}}" >&2
      exit 2
    fi
    # Default: advisory stderr warning (MUST-12)
    echo "[tdd-guard] ${FILE}: no adjacent test (advisory, write allowed). tip: write test first then code." >&2
    exit 0
    ;;
esac
exit 0
