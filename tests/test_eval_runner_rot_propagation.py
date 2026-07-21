#!/usr/bin/env python3
"""test_eval_runner_rot_propagation.py — KeyboardInterrupt/SystemExit propagate.

Slice 315 of issue #310: the bare ``except Exception:`` catches in
``lib/eval_runner.py`` were narrowed to documented subsets. This file
pins the propagation contract — KeyboardInterrupt and SystemExit must
still escape the per-case try blocks so users can Ctrl-C out of a stuck
eval and so the runtime can exit cleanly.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import eval_runner  # noqa: E402


def _case(dim: str = "review", case_id: str = "rt-1") -> dict:
    return {
        "case_id": case_id,
        "dim": dim,
        "category": "test",
        "expected": {},
        "schema_version": "2.0.0",
    }


class _FakeTranscript:
    def get(self, key, default=None):
        if key == "agent_output":
            return {"text": "ok"}
        return default


class TestRunRealJudgesPropagation(unittest.TestCase):
    """_run_real_judges — narrow except must NOT swallow BaseException-derived."""

    def _patched_load_transcript(self):
        return patch.object(
            eval_runner, "load_transcript",
            return_value=_FakeTranscript(),
        )

    def test_keyboard_interrupt_propagates(self):
        with self._patched_load_transcript(), \
             patch.object(eval_runner, "_judge_case",
                          side_effect=KeyboardInterrupt("user-cancelled")):
            with pytest.raises(KeyboardInterrupt):
                eval_runner._run_real_judges(
                    Path(tempfile.mkdtemp()), [_case()], {"provider": "x"},
                )

    def test_system_exit_propagates(self):
        with self._patched_load_transcript(), \
             patch.object(eval_runner, "_judge_case",
                          side_effect=SystemExit(0)):
            with pytest.raises(SystemExit):
                eval_runner._run_real_judges(
                    Path(tempfile.mkdtemp()), [_case()], {"provider": "x"},
                )

    def test_runtime_error_propagates(self):
        """An exception outside the documented subset must escape too."""
        with self._patched_load_transcript(), \
             patch.object(eval_runner, "_judge_case",
                          side_effect=RuntimeError("boom")):
            with pytest.raises(RuntimeError):
                eval_runner._run_real_judges(
                    Path(tempfile.mkdtemp()), [_case()], {"provider": "x"},
                )

    def test_oserror_becomes_rot(self):
        """OSError (network/file) IS in the narrowed set — must become ROT."""
        results = []
        with self._patched_load_transcript(), \
             patch.object(eval_runner, "_judge_case",
                          side_effect=OSError("net-down")):
            results = eval_runner._run_real_judges(
                Path(tempfile.mkdtemp()), [_case()], {"provider": "x"},
            )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].verdict, "ROT")

    def test_json_decode_error_becomes_rot(self):
        results = []
        with self._patched_load_transcript(), \
             patch.object(eval_runner, "_judge_case",
                          side_effect=json.JSONDecodeError("bad", "x", 0)):
            results = eval_runner._run_real_judges(
                Path(tempfile.mkdtemp()), [_case()], {"provider": "x"},
            )
        self.assertEqual(results[0].verdict, "ROT")


if __name__ == "__main__":
    unittest.main()
