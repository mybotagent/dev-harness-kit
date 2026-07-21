#!/usr/bin/env python3
"""test_read_env_key.py — RED-first tests for ci_setup.read_env_key.

Promotes `ci_setup._read_env_key` (private) to `ci_setup.read_env_key`
(public) and pins its public contract. Same behavior as before — the
promotion is for cross-module reach (ci_doctor imports it; cost_gate
shadowed it; the private `_` prefix was a misleading signal).

Issue #310 (inspect-report overarch finding): cross-module coupling on a
private symbol. Fix = expose the public API; consumers update.
"""
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))


def _load_ci_setup():
    name = "ci_setup"
    spec = importlib.util.spec_from_file_location(
        name, PROJECT_ROOT / "lib" / "ci_setup.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class TestReadEnvKeyPublicAPI(unittest.TestCase):
    """`ci_setup.read_env_key` exists and is the canonical implementation."""

    @classmethod
    def setUpClass(cls):
        cls.cs = _load_ci_setup()

    def test_public_alias_exists(self):
        self.assertTrue(
            hasattr(self.cs, "read_env_key"),
            "ci_setup must expose `read_env_key` as a public function "
            "(issue #310 overarch)",
        )

    def test_public_alias_is_callable(self):
        self.assertTrue(callable(self.cs.read_env_key))

    def test_private_still_works_for_back_compat(self):
        """The old `_read_env_key` private alias must still work so existing
        call sites don't break on the same commit. Removal is a separate
        follow-up — this slice only adds the public API.
        """
        self.assertTrue(
            hasattr(self.cs, "_read_env_key"),
            "_read_env_key was removed; back-compat alias required",
        )
        self.assertIs(
            self.cs._read_env_key, self.cs.read_env_key,
            "_read_env_key must be the same function object as read_env_key",
        )


class TestReadEnvKeyBehavior(unittest.TestCase):
    """Behavioral coverage for `read_env_key`. Same expectations as the
    private helper had, just exercised via the public name.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.read_env_key = _load_ci_setup().read_env_key

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_file_returns_empty(self):
        self.assertEqual(self.read_env_key(self.root / "missing.env", "KEY"), "")

    def test_blank_lines_ignored(self):
        p = self.root / "x.env"
        p.write_text("\n\n\n", encoding="utf-8")
        self.assertEqual(self.read_env_key(p, "FOO"), "")

    def test_comment_lines_ignored(self):
        p = self.root / "x.env"
        p.write_text("# FOO=bar\n", encoding="utf-8")
        self.assertEqual(self.read_env_key(p, "FOO"), "")

    def test_simple_value(self):
        p = self.root / "x.env"
        p.write_text("FOO=hello\n", encoding="utf-8")
        self.assertEqual(self.read_env_key(p, "FOO"), "hello")

    def test_double_quoted_stripped(self):
        p = self.root / "x.env"
        p.write_text('FOO="hello"\n', encoding="utf-8")
        self.assertEqual(self.read_env_key(p, "FOO"), "hello")

    def test_single_quoted_stripped(self):
        p = self.root / "x.env"
        p.write_text("FOO='hello'\n", encoding="utf-8")
        self.assertEqual(self.read_env_key(p, "FOO"), "hello")

    def test_last_value_wins_on_repeat(self):
        # The helper reads "last `KEY=...` value" — repeated keys collapse
        # to the latest one. This matches the historical behavior pinned
        # by test_set_provider.py::test_upsert_collapses_duplicates.
        p = self.root / "x.env"
        p.write_text("FOO=first\nFOO=second\nFOO=third\n", encoding="utf-8")
        self.assertEqual(self.read_env_key(p, "FOO"), "third")

    def test_unrelated_keys_ignored(self):
        p = self.root / "x.env"
        p.write_text("OTHER=val\nFOO=match\n", encoding="utf-8")
        self.assertEqual(self.read_env_key(p, "FOO"), "match")
        self.assertEqual(self.read_env_key(p, "OTHER"), "val")
        self.assertEqual(self.read_env_key(p, "MISSING"), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
