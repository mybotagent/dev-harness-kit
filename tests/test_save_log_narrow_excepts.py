#!/usr/bin/env python3
"""test_save_log_narrow_excepts.py — slice 315 of #310.

The bare ``except Exception:`` in ``tools/save_log.py:336`` (around
``json.load(sys.stdin)``) was narrowed to
``(json.JSONDecodeError, ValueError)``. This file pins the propagation
contract — KeyboardInterrupt and SystemExit must still escape so the
caller can Ctrl-C the hook and so the interpreter can exit cleanly when
stdin EOF / read errors occur.
"""
from __future__ import annotations

import io
import sys
import unittest
from unittest.mock import patch

import pytest

PROJECT_ROOT = "/Users/sanghee/dev/dev-harness-kit/.claude/worktrees/agent-ae4a5f9a244d44d7d"
sys.path.insert(0, PROJECT_ROOT + "/tools")

import save_log  # noqa: E402  (sys.path mutated above)


class TestSaveLogMainNarrowing(unittest.TestCase):
    """main() — stdin json.load try block must not catch BaseException."""

    def _argv(self, tool: str = "claude-code") -> list[str]:
        return ["save_log.py", "--tool", tool]

    def test_invalid_json_returns_zero(self):
        """Invalid JSON is JSONDecodeError → swallowed → exit 0 + stderr."""
        with patch.object(sys, "stdin", io.StringIO("not-json")), \
             patch.object(sys, "argv", self._argv()), \
             patch.object(sys, "stderr", io.StringIO()) as fake_stderr:
            rc = save_log.main()
        self.assertEqual(rc, 0)
        self.assertIn("failed to parse stdin JSON", fake_stderr.getvalue())

    def test_keyboard_interrupt_propagates(self):
        with patch.object(sys, "stdin", io.StringIO("")), \
             patch.object(sys, "argv", self._argv()), \
             patch("save_log.json.load", side_effect=KeyboardInterrupt("ctrl-c")):
            with pytest.raises(KeyboardInterrupt):
                save_log.main()

    def test_system_exit_propagates(self):
        with patch.object(sys, "stdin", io.StringIO("")), \
             patch.object(sys, "argv", self._argv()), \
             patch("save_log.json.load", side_effect=SystemExit(0)):
            with pytest.raises(SystemExit):
                save_log.main()


if __name__ == "__main__":
    unittest.main()
