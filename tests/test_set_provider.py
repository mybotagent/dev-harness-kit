#!/usr/bin/env python3
"""test_set_provider.py — regression for bin/set-provider.sh.

The previous design auto-rewrote .github/ci-review-provider.txt from
.env:CI_REVIEW_PROVIDER on every commit (.githooks/pre-commit). That
silent rewrite inverted user intent when worktree and main-checkout .env
disagreed, so the behavior was removed and replaced with this explicit
helper. Tests pin the contract so the silent rewrite cannot return:

  T1: pre-commit hook no longer touches the provider file.
  T2: script defaults to "minimax" when the file is missing.
  T3: --show / no-arg prints current value + allowlist.
  T4: invalid provider name exits non-zero with helpful error.
  T5: switching writes the new value AND prints a diff vs HEAD.
  T6: --dry-run never mutates the file.
  T7: switching to the current value is a no-op (no mutation, exit 0).
  T8: --help exits 0 and prints usage.
"""
from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "bin" / "set-provider.sh"
PROVIDER_FILE = REPO_ROOT / ".github" / "ci-review-provider.txt"
PRE_COMMIT_HOOK = REPO_ROOT / ".githooks" / "pre-commit"

ALLOWLIST = ("minimax", "anthropic", "deepseek")


def _run_in_worktree(worktree: Path, *args) -> subprocess.CompletedProcess:
    """Run the script inside a temp worktree so we don't pollute HEAD."""
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True, text=True, timeout=30, cwd=str(worktree),
    )


def _make_clean_worktree(tmp: Path) -> Path:
    """Clone the repo at HEAD into tmp/<dir> so tests can mutate safely.

    Uses --shared to avoid copying objects. We only read .github and
    .githooks; the clone just needs a valid git working tree for
    `git rev-parse --show-toplevel` and `git diff <file>`.
    """
    wt = tmp / "wt"
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(wt), "HEAD"],
        check=True, capture_output=True, cwd=str(REPO_ROOT),
    )
    return wt


def _read_provider(worktree: Path) -> str:
    f = worktree / ".github" / "ci-review-provider.txt"
    if not f.exists():
        return ""
    return f.read_text().strip()


class SetProviderContract(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.wt = _make_clean_worktree(Path(self._tmp.name))

    def tearDown(self) -> None:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(self.wt)],
            check=False, capture_output=True,
        )

    # T1: pre-commit hook must not reference the provider sync anymore.
    def test_pre_commit_hook_does_not_sync_provider(self) -> None:
        text = PRE_COMMIT_HOOK.read_text()
        # The old hook literally wrote the sync logic; the new hook is a
        # documented no-op. Both signals must be absent in production.
        self.assertNotIn(
            "synced $PROVIDER_FILE",
            text,
            "pre-commit hook must not auto-rewrite ci-review-provider.txt",
        )
        self.assertNotIn(
            "git rev-parse --git-common-dir",
            text,
            "pre-commit hook must not read main-checkout .env to drive "
            "the tracked provider file",
        )

    # T2: missing file -> helper creates it with the default.
    def test_missing_file_initializes_to_default(self) -> None:
        f = self.wt / ".github" / "ci-review-provider.txt"
        if f.exists():
            f.unlink()
        result = _run_in_worktree(self.wt, "minimax")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_read_provider(self.wt), "minimax")

    # T3: --show prints current value + allowlist.
    def test_show_prints_current_and_allowlist(self) -> None:
        result = _run_in_worktree(self.wt, "--show")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("current:", result.stdout)
        for name in ALLOWLIST:
            self.assertIn(name, result.stdout, f"allowlist missing {name}")

    # T4: invalid provider -> non-zero + helpful error.
    def test_invalid_provider_exits_nonzero(self) -> None:
        result = _run_in_worktree(self.wt, "openai")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid provider", result.stderr.lower())
        # All allowlisted names should appear in the error so the user
        # knows what's valid without re-reading docs.
        for name in ALLOWLIST:
            self.assertIn(name, result.stderr)

    # T5: switch writes the new value and prints a diff vs HEAD.
    def test_switch_writes_value_and_shows_diff(self) -> None:
        # Start at minimax (the committed default).
        self.assertEqual(_read_provider(self.wt), "minimax")
        result = _run_in_worktree(self.wt, "anthropic")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_read_provider(self.wt), "anthropic")
        # Diff vs HEAD should appear in stdout.
        self.assertIn("-minimax", result.stdout)
        self.assertIn("+anthropic", result.stdout)
        # Reminder to set the matching secret.
        self.assertIn("ANTHROPIC_API_KEY", result.stdout)
        # Reminder to commit + push (we no longer do it automatically).
        self.assertIn("git commit", result.stdout)
        self.assertIn("git push", result.stdout)

    # T6: --dry-run never mutates the file.
    def test_dry_run_does_not_mutate(self) -> None:
        before = _read_provider(self.wt)
        result = _run_in_worktree(self.wt, "deepseek", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[dry-run]", result.stdout)
        after = _read_provider(self.wt)
        self.assertEqual(after, before, "dry-run must not mutate the file")

    # T7: switching to the current value is a no-op.
    def test_switch_to_current_is_noop(self) -> None:
        before = _read_provider(self.wt)
        result = _run_in_worktree(self.wt, before)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("nothing to do", result.stdout.lower())
        self.assertEqual(_read_provider(self.wt), before)

    # T8: --help exits 0 and prints usage.
    def test_help_exits_zero_and_prints_usage(self) -> None:
        result = _run_in_worktree(self.wt, "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Usage:", result.stdout)
        self.assertIn("--dry-run", result.stdout)


if __name__ == "__main__":
    unittest.main()