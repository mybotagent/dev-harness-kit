#!/usr/bin/env python3
"""test_validate_min_skill_versions.py — unit tests for the new PR-build gate.

Imports `validate_min_skill_versions` + `_semver_lt` directly from the
consumer-shipped `templates/ci/scripts/validate.py` (the same file the
PR build runs on the target repo). No filesystem side effects beyond
the tempdir the test creates for the marker.

Cases (per plan §3 table):
1. Marker absent                     → SKIP + return True
2. Marker present, no min_skill_versions field → SKIP + return True
3. Marker present, empty min_skill_versions: {} → SKIP + return True
4. Marker present, floor + mirror, install >= floor → OK + return True
5. Marker present, install < floor → FAIL + return False, message contains skill
6. Marker present, invalid semver in floor → FAIL + return False
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


def _load_validate_module():
    spec = importlib.util.spec_from_file_location(
        "validate_under_test",
        Path(__file__).parent.parent / "templates" / "ci" / "scripts" / "validate.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestValidateMinSkillVersions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = _load_validate_module()

    def _write_marker(self, target: Path, **fields) -> None:
        target.mkdir(parents=True, exist_ok=True)
        (target / ".dev-kit").mkdir(parents=True, exist_ok=True)
        marker = {
            "schema_version": "1.0.0",
            "installed_by": "dev-kit:ci-setup",
            **fields,
        }
        (target / ".dev-kit" / "ci-config.json").write_text(json.dumps(marker))

    def test_01_marker_absent_skips(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            buf = io.StringIO()
            with redirect_stdout(buf):
                ok = self.v.validate_min_skill_versions(target)
            self.assertTrue(ok)
            self.assertIn("SKIP", buf.getvalue())
            self.assertIn("no .dev-kit/ci-config.json marker", buf.getvalue())

    def test_02_marker_no_floor_field_skips(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            self._write_marker(target, installed_skill_versions={"build": "0.1.0"})
            buf = io.StringIO()
            with redirect_stdout(buf):
                ok = self.v.validate_min_skill_versions(target)
            self.assertTrue(ok)
            self.assertIn("SKIP", buf.getvalue())
            self.assertIn("no floor declared", buf.getvalue())

    def test_03_marker_empty_floor_skips(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            self._write_marker(
                target,
                min_skill_versions={},
                installed_skill_versions={"build": "0.1.0"},
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                ok = self.v.validate_min_skill_versions(target)
            self.assertTrue(ok)
            self.assertIn("SKIP", buf.getvalue())

    def test_04_floor_satisfied_ok(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            self._write_marker(
                target,
                min_skill_versions={"build": "0.1.0"},
                installed_skill_versions={"build": "0.1.0"},
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                ok = self.v.validate_min_skill_versions(target)
            self.assertTrue(ok)
            self.assertIn("OK", buf.getvalue())
            self.assertIn("1 floor(s) satisfied", buf.getvalue())

    def test_05_floor_violated_fails(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            self._write_marker(
                target,
                min_skill_versions={"ci-setup": "0.5.0"},
                installed_skill_versions={"ci-setup": "0.1.0"},
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                ok = self.v.validate_min_skill_versions(target)
            self.assertFalse(ok)
            out = buf.getvalue()
            self.assertIn("FAIL", out)
            self.assertIn("ci-setup", out)
            self.assertIn("0.1.0", out)
            self.assertIn("0.5.0", out)
            self.assertIn("installed 0.1.0 < required 0.5.0", out)

    def test_06_floor_invalid_semver_fails(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            self._write_marker(
                target,
                min_skill_versions={"ci-setup": "not-a-version"},
                installed_skill_versions={"ci-setup": "0.1.0"},
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                ok = self.v.validate_min_skill_versions(target)
            self.assertFalse(ok)
            self.assertIn("not-a-version", buf.getvalue())

    def test_07_floor_unknown_skill_fails(self):
        """A floor that names a skill not present in the mirror → FAIL with
        a 'declared min X but skill not installed' message."""
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            self._write_marker(
                target,
                min_skill_versions={"ghost-skill": "0.5.0"},
                installed_skill_versions={"build": "0.1.0"},
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                ok = self.v.validate_min_skill_versions(target)
            self.assertFalse(ok)
            self.assertIn("ghost-skill", buf.getvalue())
            self.assertIn("but skill not installed", buf.getvalue())

    def test_08_floor_with_missing_mirror_fails(self):
        """Floor declared but installed_skill_versions absent → FAIL with
        data-integrity message."""
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            self._write_marker(
                target,
                min_skill_versions={"build": "0.5.0"},
            )
            buf = io.StringIO()
            with redirect_stdout(buf):
                ok = self.v.validate_min_skill_versions(target)
            self.assertFalse(ok)
            self.assertIn("missing installed_skill_versions mirror", buf.getvalue())


class TestSemverLt(unittest.TestCase):
    """Self-contained semver compare in validate.py (no packaging dep)."""

    @classmethod
    def setUpClass(cls):
        cls.v = _load_validate_module()

    def test_pre_release_sort(self):
        self.assertTrue(self.v._semver_lt("0.1.0-rc.1", "0.1.0"))
        self.assertFalse(self.v._semver_lt("0.1.0", "0.1.0-rc.1"))
        self.assertFalse(self.v._semver_lt("0.1.0", "0.1.0"))

    def test_build_metadata_ignored(self):
        self.assertFalse(self.v._semver_lt("0.1.0+build", "0.1.0"))
        self.assertFalse(self.v._semver_lt("0.1.0+build.7", "0.1.0"))

    def test_numeric_compare(self):
        self.assertTrue(self.v._semver_lt("0.1.0", "0.2.0"))
        self.assertTrue(self.v._semver_lt("0.1.0", "1.0.0"))
        self.assertFalse(self.v._semver_lt("1.0.0", "0.99.99"))

    def test_invalid_returns_false(self):
        """Invalid inputs: return False (caller treats as data-shape failure)."""
        self.assertFalse(self.v._semver_lt("not-a-version", "0.1.0"))
        self.assertFalse(self.v._semver_lt("0.1.0", "1.0"))
        self.assertFalse(self.v._semver_lt("v1.0.0", "1.0.0"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
