#!/usr/bin/env python3
"""
test_state_codec.py — RED-first tests for state_codec.py.

Tests cover:
- read_state default fallback (empty .dev-kit/)
- write_state atomic (POSIX rename)
- transition_stage updates hand_off_chain
- append_hand_off idempotent (no overwrite)
- schema_version constant
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# Add lib to path so we can import state_codec
sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import state_codec  # noqa: E402


class TestStateCodec(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / ".dev-kit").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_state_default_when_missing(self):
        # Fresh project — no .dev-kit/state.json yet
        empty_root = Path(tempfile.mkdtemp())
        try:
            state = state_codec.read_state(empty_root)
            self.assertEqual(state["schema_version"], state_codec.SCHEMA_VERSION)
            self.assertEqual(state["current_stage"], "bootstrap")
            self.assertEqual(state["current_step"], 1)
            self.assertEqual(state["hand_off_chain"], [])
            self.assertIsNone(state["shortcut_used"])
            self.assertIn("loop_log_path", state)
        finally:
            import shutil
            shutil.rmtree(empty_root)

    def test_write_state_atomic(self):
        state = state_codec.read_state(self.root)
        state["current_stage"] = "plan"
        state["current_step"] = 3
        state_codec.write_state(self.root, state)
        reread = state_codec.read_state(self.root)
        self.assertEqual(reread["current_stage"], "plan")
        self.assertEqual(reread["current_step"], 3)
        # Verify no .tmp leftover
        leftover = list(self.root.glob(".state.*.tmp"))
        self.assertEqual(leftover, [], f"tmp files leaked: {leftover}")

    def test_transition_stage_appends_chain(self):
        state_codec.transition_stage(self.root, "plan", step=2)
        state_codec.transition_stage(self.root, "design", step=1, shortcut="tdd-fast")
        reread = state_codec.read_state(self.root)
        self.assertEqual(reread["current_stage"], "design")
        self.assertEqual(reread["current_step"], 1)
        self.assertEqual(reread["shortcut_used"], "tdd-fast")
        self.assertEqual(len(reread["hand_off_chain"]), 2)
        self.assertEqual(reread["hand_off_chain"][0]["from"], "bootstrap")
        self.assertEqual(reread["hand_off_chain"][0]["to"], "plan")
        self.assertEqual(reread["hand_off_chain"][1]["from"], "plan")
        self.assertEqual(reread["hand_off_chain"][1]["to"], "design")

    def test_append_hand_off_idempotent(self):
        p1 = state_codec.append_hand_off(self.root, "bootstrap", "plan", "Goal: 5-repo 통합")
        # Re-running with same args must NOT overwrite
        self.assertTrue(p1.exists())
        original_content = p1.read_text()
        state_codec.append_hand_off(self.root, "bootstrap", "plan", "DIFFERENT goal")
        reread_content = p1.read_text()
        self.assertEqual(original_content, reread_content, "hand-off file was overwritten (should be idempotent)")

    def test_hand_off_filename_uses_arrow(self):
        path = state_codec.append_hand_off(self.root, "build", "review", "5 step completed")
        self.assertEqual(path.name, "build→review.md")
        self.assertTrue(path.exists())

    def test_schema_version_constant(self):
        self.assertEqual(state_codec.SCHEMA_VERSION, "1.0.0")


if __name__ == "__main__":
    unittest.main(verbosity=2)
