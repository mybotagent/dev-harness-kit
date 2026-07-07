#!/usr/bin/env python3
"""validate.py — validates the CI installation in the target repo.

Extracted from dev-kit's own `.github/workflows/ci.yml` `validate` job (5 inline
`python3 -c "..."` blocks, originally lines 67-111). Repo-agnostic: gracefully
skips checks that don't apply to the target's structure.

Exit code 0 on success, 1 on any check failure. Output is line-oriented for
GitHub Actions log readability.

Checks performed (each prints `OK (...)` or `FAIL (...):`):
1. validate_installation_complete — all 8 required files present
2. validate_marker              — `.dev-kit/ci-config.json` shape + version
3. validate_bash_syntax         — `bash -n` on every installed .sh
4. validate_test_runner         — `scripts/test.sh` is bash-clean
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

# Phase partition mirrors lib/ci_setup.py:BOOTSTRAP_PATHS / BODY_PATHS.
# The marker phase field (bootstrap | body | all) drives which subset of
# required files this validator asserts. bootstrap-only installs do not
# have the body files yet -- checking them would fail spuriously.
BOOTSTRAP_REQUIRED = (
    ".github/workflows/ci.yml",
    ".github/workflows/auto-fix-pr.yml",
    ".github/workflows/review.yml",
    "scripts/validate.py",
    "scripts/test.sh",
    "scripts/branch-policy.sh",
    "scripts/ci-local.sh",
)
BODY_REQUIRED = (
    ".githooks/pre-push",
    "hooks/worktree-guard.sh",
    "hooks/task-detector.sh",
    "hooks/session-start-check.sh",
    "hooks/lib/worktree-detect.sh",
    "hooks/hooks.json",
    ".claude/rules/git-workflow.md",
    "tests/test_worktree_guard.py",
)
ALL_REQUIRED = BOOTSTRAP_REQUIRED + BODY_REQUIRED


def _ok(msg: str) -> None:
    print(f"  - {msg} OK")


def _fail(msg: str) -> None:
    print(f"  - {msg} FAIL")


def _skip(msg: str) -> None:
    print(f"  - {msg} SKIP")


def validate_installation_complete(repo_root: pathlib.Path, phase: str = "all") -> bool:
    """Assert file presence for the resolved install phase.

    Phase contract (mirrors lib/ci_setup.py):
      - bootstrap : only BOOTSTRAP_REQUIRED (workflows + scripts)
      - body      : every file in ALL_REQUIRED (body lands on top of merged bootstrap)
      - all       : every file in ALL_REQUIRED (legacy one-shot install)
      - missing   : no marker -> behave like "all" (legacy fallback)
    """
    if phase == "bootstrap":
        required = BOOTSTRAP_REQUIRED
    else:
        required = ALL_REQUIRED
    missing = [f for f in required if not (repo_root / f).exists()]
    if missing:
        _fail(f"installation (phase={phase}): missing {len(missing)} file(s): {missing}")
        return False
    _ok(f"installation complete (phase={phase}, {len(required)} files)")
    return True


def validate_marker(repo_root: pathlib.Path) -> bool:
    marker = repo_root / ".dev-kit" / "ci-config.json"
    if not marker.exists():
        _fail("ci-config marker: .dev-kit/ci-config.json missing")
        return False
    try:
        data = json.loads(marker.read_text())
        assert data.get("schema_version"), "missing schema_version"
        assert data.get("installed_by") == "dev-kit:ci-setup", \
            f"installed_by={data.get('installed_by')!r} (expected 'dev-kit:ci-setup')"
    except (AssertionError, json.JSONDecodeError) as e:
        _fail(f"ci-config marker: {e}")
        return False
    _ok(f"ci-config marker (schema={data['schema_version']})")
    return True


def validate_bash_syntax(repo_root: pathlib.Path) -> bool:
    """Run `bash -n` on every installed .sh and `.githooks/pre-push`.

    Covers `scripts/{test,branch-policy,ci-local}.sh` and the githook in one pass,
    so no separate `validate_test_runner` step is needed.
    """
    sh_files = list((repo_root / "scripts").glob("*.sh")) + [repo_root / ".githooks" / "pre-push"]
    failures = []
    for h in sh_files:
        if not h.exists():
            continue
        r = subprocess.run(["bash", "-n", str(h)], capture_output=True, text=True)
        if r.returncode != 0:
            failures.append((h.name, r.stderr.strip()))
    if failures:
        _fail(f"bash syntax: {len(failures)} file(s): {failures}")
        return False
    _ok(f"bash syntax ({len(sh_files)} scripts clean)")
    return True


def _read_marker_phase(repo_root: pathlib.Path) -> str:
    """Read the marker's phase field; "missing" when no marker, "all" when unreadable."""
    marker = repo_root / ".dev-kit" / "ci-config.json"
    if not marker.exists():
        return "missing"
    try:
        data = json.loads(marker.read_text())
    except (json.JSONDecodeError, OSError):
        return "missing"
    return str(data.get("phase", "all"))


def main(repo_root: pathlib.Path | None = None) -> int:
    repo_root = repo_root or pathlib.Path.cwd()
    print(f"validate.py — repo_root={repo_root}")
    phase = _read_marker_phase(repo_root)
    # Marker first so the phase signal is visible in logs regardless of which
    # subsequent check fails.
    checks = [
        validate_marker,
        lambda r: validate_installation_complete(r, phase=phase),
        validate_bash_syntax,
    ]
    results = [c(repo_root) for c in checks]
    if all(results):
        print("OK: CI installation valid")
        return 0
    failed = sum(1 for r in results if not r)
    print(f"FAIL: {failed}/{len(results)} check(s) failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
