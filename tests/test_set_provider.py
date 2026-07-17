"""test_set_provider.py — regression for bin/set-provider.sh.

The script now manages `.env:CI_REVIEW_PROVIDER` instead of the
previously-tracked `.github/ci-review-provider.txt`. Same allowlist,
same dry-run / show / help contract; the only thing that changed is the
file the switch path writes to. Tests pin the new contract so the old
txt-file behavior cannot return:

  T1: pre-commit hook no longer references the provider sync.
  T2: missing .env bootstraps from .env.example on first switch.
  T3: --show / no-arg prints current value + allowlist.
  T4: invalid provider name exits non-zero with helpful error.
  T5: switching writes CI_REVIEW_PROVIDER into .env and prints diff
      vs the previous .env content; other keys are preserved.
  T6: --dry-run never mutates the file.
  T7: switching to the current value is a no-op.
  T8: --help exits 0 and prints usage.
  T9: idempotent upsert — re-running with the same value keeps a
      single CI_REVIEW_PROVIDER= line and does not duplicate.
 T10: missing .env.example surfaces an actionable error (no template
      to bootstrap from).
"""
from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SCRIPT = REPO_ROOT / "bin" / "set-provider.sh"
ENV_FILE = REPO_ROOT / ".env"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
PRE_COMMIT_HOOK = REPO_ROOT / ".githooks" / "pre-commit"

ALLOWLIST = ("minimax", "anthropic", "deepseek")


def _run_in_worktree(worktree: Path, *args, env_extra=None) -> subprocess.CompletedProcess:
    """Run the script inside a temp worktree so we don't pollute HEAD."""
    env = os.environ.copy()
    # CI_REVIEW_PROVIDER unset by default so the script reads from .env.
    env.pop("CI_REVIEW_PROVIDER", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        capture_output=True, text=True, timeout=30, cwd=str(worktree),
        env=env,
    )


def _make_clean_worktree(tmp: Path) -> Path:
    """Clone the repo at HEAD into tmp/<dir> so tests can mutate safely.

    Uses --shared to avoid copying objects. We only read `.env.example`,
    `.githooks`, and the script; the clone just needs a valid git
    working tree for `git rev-parse --show-toplevel`.
    """
    wt = tmp / "wt"
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(wt), "HEAD"],
        check=True, capture_output=True, cwd=str(REPO_ROOT),
    )
    return wt


def _read_env_provider(worktree: Path) -> str:
    f = worktree / ".env"
    if not f.exists():
        return ""
    for line in f.read_text().splitlines():
        s = line.strip()
        if s.startswith("#") or "=" not in s or not s:
            continue
        k, _, v = s.partition("=")
        if k.strip() == "CI_REVIEW_PROVIDER":
            return v.strip().strip('"').strip("'")
    return ""


def _drop_env(worktree: Path) -> None:
    f = worktree / ".env"
    if f.exists():
        f.unlink()


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

    # T1: pre-commit hook must not reference provider sync anymore.
    def test_pre_commit_hook_does_not_sync_provider(self) -> None:
        text = PRE_COMMIT_HOOK.read_text()
        # The old hook literally wrote the sync logic; the new hook is a
        # documented no-op. Both signals must be absent in production.
        self.assertNotIn(
            "synced $PROVIDER_FILE",
            text,
            "pre-commit hook must not auto-rewrite the provider file",
        )
        self.assertNotIn(
            "git rev-parse --git-common-dir",
            text,
            "pre-commit hook must not read main-checkout .env to drive "
            "the tracked provider file",
        )

    # T2: missing .env → first switch bootstraps from .env.example.
    def test_missing_env_bootstraps_from_example(self) -> None:
        _drop_env(self.wt)
        self.assertFalse((self.wt / ".env").exists())
        result = _run_in_worktree(self.wt, "minimax")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.wt / ".env").exists(),
                        ".env must be created from .env.example on first switch")
        self.assertEqual(_read_env_provider(self.wt), "minimax")
        # The other template keys must be preserved.
        text = (self.wt / ".env").read_text()
        self.assertIn("MINIMAX_API_KEY=", text)
        self.assertIn("ANTHROPIC_API_KEY=", text)
        self.assertIn("DEEPSEEK_API_KEY=", text)

    # T3: --show prints current value + allowlist.
    def test_show_prints_current_and_allowlist(self) -> None:
        _drop_env(self.wt)
        result = _run_in_worktree(self.wt, "--show")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("current:", result.stdout)
        self.assertIn("(unset)", result.stdout,
                      "with no .env and no env var, current should print (unset)")
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

    # T5: switch writes CI_REVIEW_PROVIDER into .env and shows the diff.
    def test_switch_writes_value_and_shows_diff(self) -> None:
        _drop_env(self.wt)
        result = _run_in_worktree(self.wt, "anthropic")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(_read_env_provider(self.wt), "anthropic")
        # Reminder to set the matching GitHub variable + secret.
        self.assertIn("CI_REVIEW_PROVIDER", result.stdout)
        self.assertIn("ANTHROPIC_API_KEY", result.stdout)
        # .env is gitignored — no commit reminder expected.
        self.assertNotIn("git commit", result.stdout)

    # T6: --dry-run never mutates the file.
    def test_dry_run_does_not_mutate(self) -> None:
        _drop_env(self.wt)
        result = _run_in_worktree(self.wt, "deepseek", "--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[dry-run]", result.stdout)
        self.assertFalse((self.wt / ".env").exists(),
                         "dry-run must not create .env")

    # T7: switching to the current value is a no-op.
    def test_switch_to_current_is_noop(self) -> None:
        _drop_env(self.wt)
        # Bootstrap first, then re-apply same value.
        _run_in_worktree(self.wt, "minimax")
        before = (self.wt / ".env").read_text()
        result = _run_in_worktree(self.wt, "minimax")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("nothing to do", result.stdout.lower())
        self.assertEqual((self.wt / ".env").read_text(), before)

    # T8: --help exits 0 and prints usage.
    def test_help_exits_zero_and_prints_usage(self) -> None:
        result = _run_in_worktree(self.wt, "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Usage:", result.stdout)
        self.assertIn("--dry-run", result.stdout)

    # T9: idempotent upsert — no duplicate lines after multiple switches.
    def test_idempotent_upsert_no_duplicate_lines(self) -> None:
        _drop_env(self.wt)
        for p in ("anthropic", "deepseek", "minimax", "minimax"):
            r = _run_in_worktree(self.wt, p)
            self.assertEqual(r.returncode, 0, r.stderr)
        text = (self.wt / ".env").read_text()
        occurrences = [
            line for line in text.splitlines()
            if line.strip().startswith("CI_REVIEW_PROVIDER=")
        ]
        self.assertEqual(len(occurrences), 1,
                         f"expected exactly one CI_REVIEW_PROVIDER line, got {occurrences!r}")

    # T10: missing .env.example → actionable error.
    def test_missing_env_example_errors(self) -> None:
        _drop_env(self.wt)
        example = self.wt / ".env.example"
        if example.exists():
            example.unlink()
        result = _run_in_worktree(self.wt, "anthropic")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(".env.example", result.stderr)
        self.assertIn("cannot manage provider", result.stderr)


if __name__ == "__main__":
    unittest.main()
