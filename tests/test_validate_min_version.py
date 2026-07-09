#!/usr/bin/env python3
"""test_validate_min_version.py — unit tests for the new PR-build plugin-version gate.

Imports `validate_min_version` from the consumer-shipped
`templates/ci/scripts/validate.py` (the same file the PR build runs on
the target repo). No filesystem side effects beyond the tempdir the test
creates for the marker.

Cases (per the behavior matrix in `validate_min_version`'s docstring):
1. Marker absent                            → SKIP + return True
2. Marker present, no `min_version` field   → SKIP + return True (permissive)
3. Marker present, `min_version` is empty   → SKIP + return True
4. Marker present, floor satisfied          → OK + return True
5. Marker present, floor violated           → FAIL + return False, message contains version
6. Marker present, invalid semver           → FAIL + return False
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


class TestValidateMinVersion(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v = _load_validate_module()

    def _write_marker(self, target: Path, **fields) -> None:
        target.mkdir(parents=True, exist_ok=True)
        (target / ".dev-kit").mkdir(parents=True, exist_ok=True)
        marker = {
            "schema_version": "1.0.0",
            "ci_setup_version": "0.2.0",
            "installed_by": "dev-kit:ci-setup",
            **fields,
        }
        (target / ".dev-kit" / "ci-config.json").write_text(json.dumps(marker))

    def test_01_marker_absent_skips(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            buf = io.StringIO()
            with redirect_stdout(buf):
                ok = self.v.validate_min_version(target)
            self.assertTrue(ok)
            self.assertIn("SKIP", buf.getvalue())
            self.assertIn("no .dev-kit/ci-config.json marker", buf.getvalue())

    def test_02_marker_no_min_version_field_skips(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            self._write_marker(target)  # no min_version
            buf = io.StringIO()
            with redirect_stdout(buf):
                ok = self.v.validate_min_version(target)
            self.assertTrue(ok)
            self.assertIn("SKIP", buf.getvalue())
            self.assertIn("no floor declared", buf.getvalue())

    def test_03_marker_empty_min_version_skips(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            self._write_marker(target, min_version="")
            buf = io.StringIO()
            with redirect_stdout(buf):
                ok = self.v.validate_min_version(target)
            self.assertTrue(ok)
            self.assertIn("SKIP", buf.getvalue())

    def test_04_floor_satisfied_ok(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            self._write_marker(target, min_version="0.2.0")
            buf = io.StringIO()
            with redirect_stdout(buf):
                ok = self.v.validate_min_version(target)
            self.assertTrue(ok)
            self.assertIn("OK", buf.getvalue())
            self.assertIn("installed 0.2.0 >= floor 0.2.0", buf.getvalue())

    def test_05_floor_lower_than_install_ok(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            self._write_marker(target, min_version="0.1.0")
            buf = io.StringIO()
            with redirect_stdout(buf):
                ok = self.v.validate_min_version(target)
            self.assertTrue(ok)
            self.assertIn("installed 0.2.0 >= floor 0.1.0", buf.getvalue())

    def test_06_floor_violated_fails(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            self._write_marker(target, min_version="0.5.0")
            buf = io.StringIO()
            with redirect_stdout(buf):
                ok = self.v.validate_min_version(target)
            self.assertFalse(ok)
            out = buf.getvalue()
            self.assertIn("FAIL", out)
            self.assertIn("installed plugin 0.2.0 < required 0.5.0", out)

    def test_07_floor_invalid_semver_fails(self):
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            self._write_marker(target, min_version="not-a-version")
            buf = io.StringIO()
            with redirect_stdout(buf):
                ok = self.v.validate_min_version(target)
            self.assertFalse(ok)
            self.assertIn("not-a-version", buf.getvalue())

    def test_08_installed_invalid_semver_fails(self):
        """If ci_setup_version on disk isn't valid semver (data-shape failure), hard FAIL."""
        with tempfile.TemporaryDirectory() as td:
            target = Path(td)
            self._write_marker(target, ci_setup_version="garbage", min_version="0.1.0")
            buf = io.StringIO()
            with redirect_stdout(buf):
                ok = self.v.validate_min_version(target)
            self.assertFalse(ok)
            self.assertIn("garbage", buf.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
