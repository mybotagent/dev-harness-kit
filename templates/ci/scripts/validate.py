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
4. validate_min_skill_versions  — min_skill_versions floor (consumer-opt-in,
   empty {} → SKIP)
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

    Per semver 2.0.0: numeric (major, minor, patch) compare first; a
    version with a pre-release identifier has LOWER precedence than the
    same version without one (so `0.1.0-rc.1 < 0.1.0`); build metadata is
    ignored in precedence. Returns False when either input fails
    SEMVER_RE (the caller should treat that as a data-shape failure, not
    a comparison outcome).
    """
    if not (SEMVER_RE.match(a) and SEMVER_RE.match(b)):
        return False
    a_main, _, a_pre = a.partition("-")
    if "+" in a_pre:
        a_pre = a_pre.split("+", 1)[0]
    b_main, _, b_pre = b.partition("-")
    if "+" in b_pre:
        b_pre = b_pre.split("+", 1)[0]
    # Build metadata may also appear without a pre-release; strip it from
    # the main part so X.Y.Z+build parses as just X.Y.Z.
    if "+" in a_main:
        a_main = a_main.split("+", 1)[0]
    if "+" in b_main:
        b_main = b_main.split("+", 1)[0]
    a_nums = tuple(int(x) for x in a_main.split("."))
    b_nums = tuple(int(x) for x in b_main.split("."))
    if a_nums != b_nums:
        return a_nums < b_nums
    # Numeric parts equal. Pre-release precedence per semver §11:
    # a version WITHOUT pre-release has HIGHER precedence than one with.
    if a_pre and not b_pre:
        return True   # 0.1.0-rc.1 < 0.1.0
    if b_pre and not a_pre:
        return False  # 0.1.0 > 0.1.0-rc.1
    if not a_pre and not b_pre:
        return False
    # Both have pre-release: compare identifier tuple (lexicographic on
    # dot-separated components, numeric when both sides parse as int).
    def _id_tuple(s: str) -> tuple:
        out = []
        for part in s.split("."):
            try:
                out.append((0, int(part)))
            except ValueError:
                out.append((1, part))
        return tuple(out)
    return _id_tuple(a_pre) < _id_tuple(b_pre)


def validate_min_skill_versions(repo_root: pathlib.Path) -> bool:
    """Fail the PR if the consumer's opt-in `min_skill_versions` floor is violated.

    Behavior matrix (see plan §3 in `.claude/plans/luminous-spinning-pascal.md`):
      - Marker absent                     → SKIP (bootstrap not run)
      - Marker present, no floor declared → SKIP (permissive default)
      - Marker present, empty floor {}    → SKIP (no constraint)
      - Marker present, floor declared,
        no installed_skill_versions       → FAIL (data integrity)
      - Marker present, install >= floor  → OK
      - Marker present, install < floor   → FAIL (exit 1)
    """
    marker = repo_root / ".dev-kit" / "ci-config.json"
    if not marker.exists():
        _skip("min_skill_versions: no .dev-kit/ci-config.json marker")
        return True
    try:
        data = json.loads(marker.read_text())
    except json.JSONDecodeError as e:
        _fail(f"min_skill_versions: marker unreadable: {e}")
        return False
    if not isinstance(data, dict):
        _skip("min_skill_versions: marker is not a JSON object")
        return True
    floor = data.get("min_skill_versions")
    if not isinstance(floor, dict) or not floor:
        _skip("min_skill_versions: no floor declared (permissive)")
        return True
    installed = data.get("installed_skill_versions")
    if not isinstance(installed, dict) or not installed:
        _fail("min_skill_versions: marker missing installed_skill_versions mirror")
        return False
    bad: list = []
    for skill, want in floor.items():
        have = installed.get(skill)
        if have is None:
            bad.append(f"      {skill}: declared min {want!r} but skill not installed")
            continue
        if not isinstance(have, str) or not SEMVER_RE.match(have):
            bad.append(f"      {skill}: installed version {have!r} is not valid semver")
            continue
        if not isinstance(want, str) or not SEMVER_RE.match(want):
            bad.append(f"      {skill}: required version {want!r} is not valid semver")
            continue
        if _semver_lt(have, want):
            bad.append(f"      {skill}: installed {have} < required {want}")
    if bad:
        _fail(f"min_skill_versions: {len(bad)} below floor")
        for line in bad:
            print(line)
        return False
    _ok(f"min_skill_versions ({len(floor)} floor(s) satisfied)")
    return True


def main(repo_root: pathlib.Path | None = None) -> int:
    repo_root = repo_root or pathlib.Path.cwd()
    print(f"validate.py — repo_root={repo_root}")
    checks = [
        validate_installation_complete,
        validate_marker,
        validate_bash_syntax,
        validate_min_skill_versions,
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