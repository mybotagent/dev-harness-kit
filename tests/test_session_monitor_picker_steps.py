#!/usr/bin/env python3
"""test_session_monitor_picker_steps.py — minimal unpacking regression test.

Covers the tuple-length bug where ``_step_normal`` / ``_step_editing`` used
``_move() + (buffer, mode, None, False)`` (7 items) and the call site in
``pick_session`` expects a 6-tuple ``(rows, cursor, buffer, mode, returned,
should_exit)``. The move branches used to raise
``ValueError: too many values to unpack (expected 6)`` on the arrow / j / k
keys — this test pins the post-fix shape.
"""
from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

import session_monitor as sm  # noqa: E402

NOW = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)


def _agg(**kw):
    base = {
        "session_id": "s", "source": "claude-code", "worktree": "(main)",
        "branch": "main", "model": "m", "last_ts": NOW,
        "tool_counts": {}, "log_path": "",
    }
    base.update(kw)
    return base


class TestStepNormalMoveKeys(unittest.TestCase):
    """``_step_normal`` / ``_step_editing`` must return a 6-tuple for arrow / j / k keys."""

    def _model(self):
        return [
            sm.WorktreeInfo(
                "alpha", "live", None,
                [sm.Session(agg=_agg(session_id="a1"),
                            worktree_state="live", status=sm.Status.IDLE),
                 sm.Session(agg=_agg(session_id="a2"),
                            worktree_state="live", status=sm.Status.IDLE)],
            ),
        ]

    def _rows_cursor(self, original_model):
        rows = sm.build_rows(original_model, now=NOW)
        sel = sm._selectable_indices(rows)
        self.assertTrue(sel, "fixture must produce at least one selectable row")
        return rows, sel[0]

    def test_arrow_up_unpacks_and_keeps_normal_mode(self):
        original_model = self._model()
        rows, cursor = self._rows_cursor(original_model)
        result = sm._step_normal(b"\x1b[A", rows, cursor, "", list(original_model))
        self.assertEqual(len(result), 6,
                         f"_step_normal must return 6 items, got {len(result)}")
        new_rows, new_cursor, new_buffer, new_mode, returned, should_exit = result
        self.assertIs(returned, None)
        self.assertFalse(should_exit)
        self.assertEqual(new_mode, "NORMAL")

    def test_k_key_in_editing_unpacks_and_keeps_editing_mode(self):
        original_model = self._model()
        rows, cursor = self._rows_cursor(original_model)
        result = sm._step_editing(b"k", rows, cursor, "ab", list(original_model))
        self.assertEqual(len(result), 6,
                         f"_step_editing must return 6 items, got {len(result)}")
        new_rows, new_cursor, new_buffer, new_mode, returned, should_exit = result
        self.assertIs(returned, None)
        self.assertFalse(should_exit)
        self.assertEqual(new_mode, "EDITING")


if __name__ == "__main__":
    unittest.main()
