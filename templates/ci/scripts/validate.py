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
3. validate_bash_syntax         — `bash -n` on every installed .sh + pre-push
4. validate_min_version         — `min_version` plugin floor (consumer-opt-in,
   empty/missing → SKIP)
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys

REQUIRED_FILES = [
    ".github/workflows/ci.yml",
    ".github/workflows/auto-fix-pr.yml",
    ".github/workflows/review.yml",
    ".githooks/pre-push",
    "scripts/validate.py",
    "scripts/test.sh",
    "scripts/branch-policy.sh",
    "scripts/ci-local.sh",
]

# Per-skill semver (matches lib/ci_setup.py:SEMVER_RE). Self-contained
# comparison (no `packaging` dep) so consumer repos don't need an extra
# requirement for this script to run. Supports `X.Y.Z` plus optional
# `-prerelease` / `+build` per semver 2.0.0; prerelease sorts BEFORE the
# release (e.g. `0.1.0-rc.1 < 0.1.0`); build metadata is ignored in
# ordering (per semver §10).
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def _ok(msg: str) -> None:
    print(f"  - {msg} OK")


def _fail(msg: str) -> None:
    print(f"  - {msg} FAIL")


def _skip(msg: str) -> None:
    print(f"  - {msg} SKIP")


def validate_installation_complete(repo_root: pathlib.Path) -> bool:
    missing = [f for f in REQUIRED_FILES if not (repo_root / f).exists()]
    if missing:
        _fail(f"installation: missing {len(missing)} file(s): {missing}")
        return False
    _ok(f"installation complete ({len(REQUIRED_FILES)} files)")
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


def _semver_lt(a: str, b: str) -> bool:
    """Return True iff semver string `a` is strictly less than `b`.

    Canonical implementation lives at `lib/ci_setup.py:semver_lt`. This
    shim prefers that import (when dev-kit is installed alongside the
    consumer's `scripts/` dir, the lib/ path is reachable) and falls
    back to a self-contained regex comparator when it isn't, so this
    file remains a single, dependency-free script that runs on any
    consumer runner (see audit-outdated review M2 — single source).
    """
    try:
        import importlib.util as _ilu
        import sys as _sys
        from pathlib import Path as _P
        _lib = _P(__file__).parent.parent.parent.parent / "lib" / "ci_setup.py"
        if _lib.exists():
            _spec = _ilu.spec_from_file_location("_ci_setup_for_validate", _lib)
            _mod = _ilu.module_from_spec(_spec)
            _sys.modules.setdefault("_ci_setup_for_validate", _mod)
            _spec.loader.exec_module(_mod)
            return _mod.semver_lt(a, b)
    except Exception:
        pass
    # Fallback: self-contained comparator (kept for environments where
    # lib/ci_setup.py is not present — e.g. a consumer who only copied
    # scripts/validate.py out of templates/ci/).
    if not (SEMVER_RE.match(a) and SEMVER_RE.match(b)):
        return False
    a_main, _, a_pre = a.partition("-")
    if "+" in a_pre:
        a_pre = a_pre.split("+", 1)[0]
    b_main, _, b_pre = b.partition("-")
    if "+" in b_pre:
        b_pre = b_pre.split("+", 1)[0]
    if "+" in a_main:
        a_main = a_main.split("+", 1)[0]
    if "+" in b_main:
        b_main = b_main.split("+", 1)[0]
    a_nums = tuple(int(x) for x in a_main.split("."))
    b_nums = tuple(int(x) for x in b_main.split("."))
    if a_nums != b_nums:
        return a_nums < b_nums
    if a_pre and not b_pre:
        return True
    if b_pre and not a_pre:
        return False
    if not a_pre and not b_pre:
        return False
    def _id_tuple(s: str) -> tuple:
        out = []
        for part in s.split("."):
            try:
                out.append((0, int(part)))
            except ValueError:
                out.append((1, part))
        return tuple(out)
    return _id_tuple(a_pre) < _id_tuple(b_pre)


def validate_min_version(repo_root: pathlib.Path) -> bool:
    """Fail the PR if the consumer's opt-in `min_version` floor is violated.

    Compares the marker's `ci_setup_version` (mirror of the canonical
    `.claude-plugin/plugin.json:version`) against the consumer's opt-in
    `min_version` field. Single plugin-level comparison — no per-skill
    bookkeeping required.

    Behavior matrix:
      - Marker absent                                 → SKIP
      - Marker present, `min_version` missing/empty   → SKIP (permissive)
      - Marker present, `min_version` not semver      → FAIL (data shape)
      - Marker present, ci_setup_version < min_version → FAIL (exit 1)
      - Marker present, ci_setup_version >= min_version → OK
    """
    marker = repo_root / ".dev-kit" / "ci-config.json"
    if not marker.exists():
        _skip("min_version: no .dev-kit/ci-config.json marker")
        return True
    try:
        data = json.loads(marker.read_text())
    except json.JSONDecodeError as e:
        _fail(f"min_version: marker unreadable: {e}")
        return False
    if not isinstance(data, dict):
        _skip("min_version: marker is not a JSON object")
        return True
    floor = data.get("min_version")
    if not isinstance(floor, str) or not floor.strip():
        _skip("min_version: no floor declared (permissive)")
        return True
    have = data.get("ci_setup_version")
    if not isinstance(have, str) or not SEMVER_RE.match(have):
        _fail(f"min_version: marker missing/invalid ci_setup_version {have!r}")
        return False
    if not SEMVER_RE.match(floor):
        _fail(f"min_version: required floor {floor!r} is not valid semver")
        return False
    if _semver_lt(have, floor):
        _fail(f"min_version: installed plugin {have} < required {floor}")
        return False
    _ok(f"min_version (installed {have} >= floor {floor})")
    return True


def main(repo_root: pathlib.Path | None = None) -> int:
    repo_root = repo_root or pathlib.Path.cwd()
    print(f"validate.py — repo_root={repo_root}")
    checks = [
        validate_installation_complete,
        validate_marker,
        validate_bash_syntax,
        validate_min_version,
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