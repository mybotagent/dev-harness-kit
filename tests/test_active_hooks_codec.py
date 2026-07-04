#!/usr/bin/env python3
"""
test_active_hooks_codec.py — RED-first tests for active_hooks_codec.py.

Tests cover:
- init_matrix writes default 7-stage matrix
- read_matrix idempotent
- is_hook_active per stage
- env override DEV_KIT_HOOK_OFF
- override.disabled_hooks
- set_stage individual cell update
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import active_hooks_codec  # noqa: E402


class TestActiveHooksCodec(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".dev-kit").mkdir(parents=True, exist_ok=True)
        # Clean env override
        self._orig_env = os.environ.get("DEV_KIT_HOOK_OFF")
        os.environ.pop("DEV_KIT_HOOK_OFF", None)

    def tearDown(self):
        if self._orig_env is not None:
            os.environ["DEV_KIT_HOOK_OFF"] = self._orig_env
        self.tmp.cleanup()

    def test_init_matrix_default_7_stages(self):
        data = active_hooks_codec.init_matrix(self.root)
        self.assertIn("bootstrap", data["matrix"])
        self.assertIn("plan", data["matrix"])
        self.assertIn("design", data["matrix"])
        self.assertIn("build", data["matrix"])
        self.assertIn("review", data["matrix"])
        self.assertIn("security", data["matrix"])
        self.assertIn("ship", data["matrix"])
        # 5 hooks per stage
        for stage in data["matrix"].values():
            self.assertEqual(len(stage), 5)

    def test_is_hook_active_default(self):
        active_hooks_codec.init_matrix(self.root)
        # build: all 5 hooks ON (or read-only)
        self.assertTrue(active_hooks_codec.is_hook_active(self.root, "build", "tdd-guard"))
        self.assertTrue(active_hooks_codec.is_hook_active(self.root, "build", "bash-guard"))
        self.assertTrue(active_hooks_codec.is_hook_active(self.root, "build", "secret-scan"))
        # plan: only stop-verify
        self.assertFalse(active_hooks_codec.is_hook_active(self.root, "plan", "tdd-guard"))
        self.assertTrue(active_hooks_codec.is_hook_active(self.root, "plan", "stop-verify"))

    def test_is_hook_active_bootstrap_readonly(self):
        active_hooks_codec.init_matrix(self.root)
        # bootstrap: secret-scan = "read-only" (truthy)
        self.assertTrue(active_hooks_codec.is_hook_active(self.root, "bootstrap", "secret-scan"))
        # others False
        self.assertFalse(active_hooks_codec.is_hook_active(self.root, "bootstrap", "tdd-guard"))

    def test_env_override_disables_hook(self):
        active_hooks_codec.init_matrix(self.root)
        with patch.dict(os.environ, {"DEV_KIT_HOOK_OFF": "tdd-guard,slop-detector"}):
            self.assertFalse(active_hooks_codec.is_hook_active(self.root, "build", "tdd-guard"))
            self.assertFalse(active_hooks_codec.is_hook_active(self.root, "build", "slop-detector"))
            self.assertTrue(active_hooks_codec.is_hook_active(self.root, "build", "bash-guard"))

    def test_disable_override(self):
        active_hooks_codec.init_matrix(self.root)
        active_hooks_codec.disable_override(self.root, "bash-guard")
        self.assertFalse(active_hooks_codec.is_hook_active(self.root, "build", "bash-guard"))
        # Other hooks unaffected
        self.assertTrue(active_hooks_codec.is_hook_active(self.root, "build", "tdd-guard"))

    def test_set_stage_cell(self):
        active_hooks_codec.init_matrix(self.root)
        active_hooks_codec.set_stage(self.root, "plan", "tdd-guard", True)
        self.assertTrue(active_hooks_codec.is_hook_active(self.root, "plan", "tdd-guard"))

    def test_read_matrix_idempotent(self):
        active_hooks_codec.init_matrix(self.root)
        d1 = active_hooks_codec.read_matrix(self.root)
        d2 = active_hooks_codec.read_matrix(self.root)
        self.assertEqual(d1["matrix"], d2["matrix"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
