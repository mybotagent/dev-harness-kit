#!/usr/bin/env python3
"""test_semver_lt.py — unit tests for lib/ci_setup.py:semver_lt.

Loads `lib/ci_setup.py` via importlib so the test does not depend on the
plugin being on PYTHONPATH. Imports `semver_lt` (public) + `SEMVER_RE`.

Coverage mirrors what `tests/test_validate_min_skill_versions.py` already
exercises at the `_semver_lt` shim level — but here we test the
canonical implementation directly so the single source of truth is
regression-tested on every CI run.
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


def _load_ci_setup():
    spec = importlib.util.spec_from_file_location(
        "_ci_setup_under_test", Path(__file__).parent.parent / "lib" / "ci_setup.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_ci_setup_under_test"] = mod  # @dataclass needs sys.modules (Py3.14)
    spec.loader.exec_module(mod)
    return mod


class TestSemverLt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_ci_setup()

    def test_pre_release_sort(self):
        self.assertTrue(self.mod.semver_lt("0.1.0-rc.1", "0.1.0"))
        self.assertFalse(self.mod.semver_lt("0.1.0", "0.1.0-rc.1"))
        self.assertFalse(self.mod.semver_lt("0.1.0", "0.1.0"))

    def test_build_metadata_ignored(self):
        self.assertFalse(self.mod.semver_lt("0.1.0+build", "0.1.0"))
        self.assertFalse(self.mod.semver_lt("0.1.0+build.7", "0.1.0"))
        self.assertTrue(self.mod.semver_lt("0.1.0+build", "0.1.1"))

    def test_numeric_compare(self):
        self.assertTrue(self.mod.semver_lt("0.1.0", "0.2.0"))
        self.assertTrue(self.mod.semver_lt("0.1.0", "1.0.0"))
        self.assertTrue(self.mod.semver_lt("1.0.0", "1.0.1"))
        self.assertFalse(self.mod.semver_lt("1.0.0", "0.99.99"))

    def test_prerelease_identifier_compare(self):
        self.assertTrue(self.mod.semver_lt("0.1.0-rc.1", "0.1.0-rc.2"))
        self.assertFalse(self.mod.semver_lt("0.1.0-rc.2", "0.1.0-rc.1"))
        self.assertFalse(self.mod.semver_lt("0.1.0-rc.1", "0.1.0-rc.1"))
        # Numeric identifiers compare as integers; alphanumeric as strings.
        self.assertTrue(self.mod.semver_lt("0.1.0-alpha.1", "0.1.0-alpha.beta"))
        self.assertFalse(self.mod.semver_lt("0.1.0-alpha.beta", "0.1.0-alpha.1"))
        # Numeric < alphanumeric (per semver §11).
        self.assertTrue(self.mod.semver_lt("1.0.0-0.3.7", "1.0.0-rc.1"))

    def test_invalid_returns_false(self):
        """Invalid inputs: return False (caller treats as data-shape failure)."""
        self.assertFalse(self.mod.semver_lt("not-a-version", "0.1.0"))
        self.assertFalse(self.mod.semver_lt("0.1.0", "1.0"))
        self.assertFalse(self.mod.semver_lt("v1.0.0", "1.0.0"))
        self.assertFalse(self.mod.semver_lt("1.0.0.0", "1.0.0"))


class TestSemverReExposed(unittest.TestCase):
    """SEMVER_RE is part of the canonical semver API; ensure it accepts and rejects as documented."""

    @classmethod
    def setUpClass(cls):
        cls.mod = _load_ci_setup()

    def test_valid(self):
        for v in ("0.1.0", "1.10.0", "0.1.0-rc.1", "0.1.0+build.7", "1.0.0-alpha.1"):
            self.assertRegex(v, self.mod.SEMVER_RE, f"{v} should match SEMVER_RE")

    def test_invalid(self):
        for v in ("1.0", "v1.0.0", "1.0.0.0", "", "1.0.0 ", " 1.0.0"):
            self.assertNotRegex(v, self.mod.SEMVER_RE, f"{v!r} should NOT match SEMVER_RE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
