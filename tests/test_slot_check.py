"""test_slot_check.py — regression for inspect 2026-08-03 finding #2.

`hooks/git-guard.sh:_verify_slot` previously inlined a slot-freshness
predicate whose mixed `||` and `&&` parsed as `(A || B) && C` because
bash gives the two operators equal precedence and evaluates left-to-
right. That parse let a stale Claude manifest slip through whenever
the Codex manifest was missing or already matched expected. The
predicate is now in `hooks/lib/slot-check.sh::slot_should_deny` and
this test pins its truth table directly.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SLOT_CHECK = REPO_ROOT / "hooks" / "lib" / "slot-check.sh"


def _bash() -> str:
    p = shutil.which("bash")
    if not p:
        raise RuntimeError("bash not on PATH")
    return p


def _call_slot(claude: str, codex: str, expected: str) -> int:
    """Source slot-check.sh and invoke slot_should_deny, return its exit code."""
    harness = (
        f'source "{SLOT_CHECK}"\n'
        f'slot_should_deny "{claude}" "{codex}" "{expected}"\n'
        'echo "rc=$?"'
    )
    r = subprocess.run(
        [_bash(), "-c", harness],
        capture_output=True, text=True, timeout=10, env=os.environ.copy(),
    )
    assert r.returncode == 0, f"helper crashed: {r.stderr}"
    # Last line of stdout is `rc=N`.
    last = r.stdout.strip().splitlines()[-1]
    assert last.startswith("rc="), f"unexpected stdout: {r.stdout!r}"
    return int(last.split("=", 1)[1])


class TestSlotCheck(unittest.TestCase):
    """All 4 stale cases must deny; the 2 fresh-or-missing cases allow."""

    def test_both_fresh_allows(self):
        self.assertEqual(_call_slot("0.3.193", "0.3.193", "0.3.193"), 1)

    def test_codex_missing_allows(self):
        # Empty codex value (file unreadable / missing) does not by itself
        # trigger deny; matches the original guard's intent.
        self.assertEqual(_call_slot("0.3.193", "", "0.3.193"), 1)

    def test_codex_stale_denies(self):
        # Codex drifted to an older slot while Claude is fresh — the
        # original inline predicate let this through because of the
        # precedence bug. Must now deny.
        self.assertEqual(_call_slot("0.3.193", "0.3.190", "0.3.193"), 0)

    def test_claude_stale_denies(self):
        self.assertEqual(_call_slot("0.3.190", "0.3.193", "0.3.193"), 0)

    def test_both_stale_denies(self):
        self.assertEqual(_call_slot("0.3.190", "0.3.190", "0.3.193"), 0)

    def test_claude_stale_codex_missing_denies(self):
        # Even with codex missing, a stale Claude alone must deny.
        self.assertEqual(_call_slot("0.3.190", "", "0.3.193"), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
