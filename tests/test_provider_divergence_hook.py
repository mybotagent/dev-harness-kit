"""test_provider_divergence_hook.py -- regression for hooks/provider-divergence-check.sh.

Pins the SessionStart hook's contract:
  T1: missing .env + missing .env.example => silent (exit 0, no nudge)
  T2: .env CI_REVIEW_PROVIDER unset => silent (no nudge on every poll)
  T3: .env CI_REVIEW_PROVIDER off-list (e.g. openai) => nudge with
      off-list warning AND exit 0 (advisory).
  T4: .env CI_REVIEW_PROVIDER = "anthropic", .env.example default =
      "minimax" => nudge with divergence message.
  T5: .env CI_REVIEW_PROVIDER = "minimax", .env.example default =
      "minimax" => silent (aligned).
  T6: jq missing => exit 0, no nudge (fails open).
  T7: cwd is outside any git repo => silent.
  T8: empty payload => no crash, exit 0.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
HOOK = REPO_ROOT / "hooks" / "provider-divergence-check.sh"


def _run_hook(payload: dict, cwd: Path) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        cwd=str(cwd),
        env=env,
    )


def _session_payload(cwd: str = "") -> dict:
    p = {"hook_event_name": "SessionStart", "session_id": "test"}
    if cwd:
        p["cwd"] = cwd
    return p


def _bootstrap_git_repo(tmp: Path) -> Path:
    """Stand up a throwaway git repo inside tmp."""
    root = tmp
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "T"], check=True)
    (root / ".gitignore").write_text(".env\n")
    subprocess.run(["git", "-C", str(root), "add", ".gitignore"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "init"], check=True)
    return root


def _write_env_example(root: Path, value: str) -> None:
    (root / ".env.example").write_text(f"CI_REVIEW_PROVIDER={value}\n")


def _write_env(root: Path, value: str) -> None:
    (root / ".env").write_text(f"CI_REVIEW_PROVIDER={value}\n")


class TestProviderDivergenceHook(unittest.TestCase):
    def setUp(self) -> None:
        if not HOOK.exists():
            self.skipTest(f"hook missing: {HOOK}")
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = _bootstrap_git_repo(Path(self._tmp.name))

    # T1
    def test_missing_everything_is_silent(self) -> None:
        r = _run_hook(_session_payload(str(self.root)), self.root)
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("PROVIDER", r.stdout)

    # T2
    def test_missing_provider_in_env_is_silent(self) -> None:
        (self.root / ".env").write_text("OTHER=value\n")
        _write_env_example(self.root, "minimax")
        r = _run_hook(_session_payload(str(self.root)), self.root)
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("PROVIDER-OFFLIST", r.stdout)
        self.assertNotIn("PROVIDER-DIVERGENCE", r.stdout)

    # T3
    def test_offlist_value_emits_warning(self) -> None:
        _write_env(self.root, "openai")
        _write_env_example(self.root, "minimax")
        r = _run_hook(_session_payload(str(self.root)), self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        combined = r.stdout + r.stderr
        self.assertIn("PROVIDER-OFFLIST", combined)
        self.assertIn("openai", combined)
        self.assertIn("not in the allowlist", combined.lower())
        # Must not mutate files.
        self.assertEqual((self.root / ".env").read_text(), "CI_REVIEW_PROVIDER=openai\n")

    # T4
    def test_onlist_divergence_emits_divergence_nudge(self) -> None:
        _write_env(self.root, "anthropic")
        _write_env_example(self.root, "minimax")
        r = _run_hook(_session_payload(str(self.root)), self.root)
        self.assertEqual(r.returncode, 0)
        combined = r.stdout + r.stderr
        self.assertIn("PROVIDER-DIVERGENCE", combined)
        self.assertIn("anthropic", combined)
        self.assertIn("minimax", combined)
        self.assertNotIn("PROVIDER-OFFLIST", combined)
        # Must not mutate files.
        self.assertEqual((self.root / ".env").read_text(), "CI_REVIEW_PROVIDER=anthropic\n")
        self.assertEqual((self.root / ".env.example").read_text(), "CI_REVIEW_PROVIDER=minimax\n")

    # T5
    def test_aligned_values_silent(self) -> None:
        _write_env(self.root, "minimax")
        _write_env_example(self.root, "minimax")
        r = _run_hook(_session_payload(str(self.root)), self.root)
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("PROVIDER-OFFLIST", r.stdout)
        self.assertNotIn("PROVIDER-DIVERGENCE", r.stdout)

    # T6
    def test_missing_jq_is_silent(self) -> None:
        if shutil.which("jq") is None:
            self.skipTest("jq not present in this env")
        # Build a minimal PATH that does NOT contain jq but DOES contain
        # bash + python (the hook itself is /bin/bash so we use its
        # absolute path, leaving only jq absent from PATH).
        bash_abs = shutil.which("bash")
        self.assertIsNotNone(bash_abs, "bash not found")
        env_no_jq = {k: v for k, v in os.environ.items() if k not in ("PATH",)}
        # Strip trailing dirs from PATH then add only dirs that lack jq.
        keep_dirs = []
        for d in os.environ.get("PATH", "").split(":"):
            if d and shutil.which("jq", path=d) is None:
                keep_dirs.append(d)
            elif d and shutil.which("bash", path=d) == bash_abs:
                keep_dirs.append(d)
        env_no_jq["PATH"] = ":".join(keep_dirs)
        # Defensive: confirm jq still absent.
        self.assertIsNone(shutil.which("jq", path=env_no_jq["PATH"]),
                          "test leak: jq still on PATH")
        env_no_jq["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
        _write_env(self.root, "openai")
        r = subprocess.run(
            [bash_abs, str(HOOK)],
            input=json.dumps(_session_payload(str(self.root))),
            capture_output=True, text=True, timeout=10,
            cwd=str(self.root), env=env_no_jq,
        )
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("PROVIDER", r.stdout)
        self.assertNotIn("PROVIDER", r.stderr)

    # T7
    def test_outside_git_repo_is_silent(self) -> None:
        # An *orthogonal* tempdir that lives OUTSIDE self._tmp so it is
        # unambiguously outside any git repo.
        ortho = tempfile.TemporaryDirectory()
        self.addCleanup(ortho.cleanup)
        non_git = Path(ortho.name) / "no_git"
        non_git.mkdir()
        (non_git / ".env").write_text("CI_REVIEW_PROVIDER=openai\n")
        # Run the hook with cwd inside non_git so bash shares the
        # off-repo state.
        env = os.environ.copy()
        env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
        r = subprocess.run(
            ["bash", str(HOOK)],
            input=json.dumps(_session_payload(str(non_git))),
            capture_output=True, text=True, timeout=10,
            cwd=str(non_git), env=env,
        )
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("PROVIDER", r.stdout)
        self.assertNotIn("PROVIDER", r.stderr)

    # T8
    def test_empty_payload_is_safe(self) -> None:
        r = _run_hook({}, self.root)
        self.assertEqual(r.returncode, 0)


if __name__ == "__main__":
    unittest.main()
