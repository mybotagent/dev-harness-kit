"""tests/test_linear_trigger_hooks_wiring.py — Regression test for
`hooks/hooks.json` wiring of the four Linear auto-trigger hooks.

If a maintainer rewires any of these hooks to a different event
matcher, this test fails loud. Each hook is required to fire on
exactly one event:

  - linear-autosync         → PreToolUse  Write|Edit|MultiEdit
  - linear-session-start    → SessionStart
  - linear-worktree-create  → PostToolUse  Bash
  - linear-task-change      → UserPromptSubmit
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
HOOKS_JSON = ROOT / "hooks" / "hooks.json"

EXPECTED = {
    "linear-autosync":         ("PreToolUse",     "Write|Edit|MultiEdit"),
    "linear-session-start":    ("SessionStart",   None),
    "linear-worktree-create":  ("PostToolUse",    "Bash"),
    "linear-task-change":      ("UserPromptSubmit", None),
}


class TestLinearTriggerHooksWiring(unittest.TestCase):
    def setUp(self):
        if not HOOKS_JSON.exists():
            self.skipTest("hooks.json missing")
        self.cfg = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        self.hooks_cfg = self.cfg.get("hooks", {})

    def _find(self, hook_name: str):
        """Return (event, matcher) where the hook is wired, or None."""
        for event, entries in self.hooks_cfg.items():
            for entry in entries:
                matcher = entry.get("matcher")
                for h in entry.get("hooks", []):
                    if hook_name in h.get("command", ""):
                        return (event, matcher)
        return None

    def test_all_four_hooks_are_wired(self):
        for hook in EXPECTED:
            with self.subTest(hook=hook):
                found = self._find(hook)
                self.assertIsNotNone(
                    found,
                    f"{hook} is not wired in hooks/hooks.json",
                )
                event, _ = found
                expected_event, _ = EXPECTED[hook]
                self.assertEqual(
                    event, expected_event,
                    f"{hook} is wired under {event!r}, expected {expected_event!r}",
                )

    def test_all_hooks_use_their_expected_matcher(self):
        for hook, (event, matcher) in EXPECTED.items():
            with self.subTest(hook=hook, matcher=matcher):
                if matcher is None:
                    continue  # SessionStart / UserPromptSubmit have no matcher
                found = self._find(hook)
                self.assertIsNotNone(found)
                _, actual_matcher = found
                self.assertEqual(
                    actual_matcher, matcher,
                    f"{hook} matcher is {actual_matcher!r}, expected {matcher!r}",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
