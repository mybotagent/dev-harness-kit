#!/usr/bin/env bash
# scripts/ci-local.sh — Local CI runner. No nektos/act required.
#
# Runs the same checks GitHub Actions runs in `.github/workflows/ci.yml`:
#   1. validate.py — installation + marker + bash syntax
#   2. test.sh     — pytest suite (skips if no tests/)
#   3. act -l      — list discovered workflows (optional, WARN if missing)
#
# Exit non-zero on any failure. Idempotent.

set -eo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

echo "=== validate ==="
if ! python3 scripts/validate.py; then
  echo "ci-local.sh: validate FAILED" >&2
  exit 1
fi
echo ""

echo "=== test ==="
if ! bash scripts/test.sh; then
  echo "ci-local.sh: test FAILED" >&2
  exit 1
fi
echo ""

if command -v act >/dev/null 2>&1; then
  echo "=== act (optional) ==="
  act -l 2>/dev/null || echo "act -l returned non-zero (this is informational only)"
else
  echo "act: not installed; skipping workflow listing."
  echo "  Install from https://nektos.act.dev for full GitHub Actions parity."
fi
echo ""

echo "ci-local.sh OK"
