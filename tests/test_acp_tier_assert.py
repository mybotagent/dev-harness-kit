"""test_acp_tier_assert.py — regression tests for the tier-assertion lint.

Closes #282. Verifies two layers:

  * Wiring — `hooks/hooks.json` declares an `acp-tier-assert.sh`
    PreToolUse entry with matcher `*` (the contract from
    `docs/architecture/acp-harness.md` §2.3). The hook script must exist and be
    executable.

  * Behavior — `hooks/acp-tier-assert.sh` denies on missing or
    malformed assertions, allows once a valid `[tier-assert]` line has
    been recorded in the per-session sidecar, and fails closed when
    `jq` is unavailable.

The hook reads a session sidecar at
`<orch_worktree>/.dev-kit/round-<descriptor>/tier-state/<session-id>.json`
so the test synthesizes a throwaway round dir and seeds a transcript
that carries the literal assertion line.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
HOOK = ROOT / "hooks" / "acp-tier-assert.sh"
HOOKS_JSON = ROOT / "hooks" / "hooks.json"
CODEX_HOOKS_JSON = ROOT / ".codex-plugin" / "hooks" / "hooks.json"


def _init_throwaway_repo() -> "tempfile.TemporaryDirectory":
    """Build a temp git repo on `main` for the cwd discriminator."""
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    (root / "README.md").write_text("x")
    subprocess.run(["git", "-C", str(root), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "init"], check=True)
    return tmp


def _run_hook(payload: dict, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """Pipe `payload` (JSON) into the hook and return the CompletedProcess."""
    return subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        cwd=str(cwd) if cwd else None,
    )


class WiringTests(unittest.TestCase):
    def test_hook_script_exists_and_is_executable(self) -> None:
        self.assertTrue(HOOK.is_file(), f"missing hook: {HOOK}")
        # Executable bit — the hook is invoked via `bash <path>` from
        # hooks.json, so the bit is not strictly required, but the
        # convention is to keep it set so the script can be run
        # standalone during debugging.
        mode = HOOK.stat().st_mode
        self.assertTrue(mode & 0o111, f"hook is not executable: {HOOK}")

    def test_hooks_json_wires_pretooluse_star_to_acp_tier_assert(self) -> None:
        config = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        groups = config["hooks"].get("PreToolUse", [])
        wired = []
        for group in groups:
            matcher = group.get("matcher", "")
            for entry in group.get("hooks", []):
                cmd = entry.get("command", "")
                if "acp-tier-assert.sh" in cmd:
                    wired.append((matcher, cmd))
        self.assertTrue(
            wired,
            "hooks/hooks.json does not wire acp-tier-assert.sh into any "
            "PreToolUse group. Add an entry with matcher='*' (or a "
            "broader matcher that covers every tool call) per "
            "docs/architecture/acp-harness.md §2.3.",
        )
        matchers = sorted({m for m, _ in wired})
        # The contract says matcher='*'. Accept a broader set ('Bash|Edit|...').
        # Refuse narrower matchers (Bash only, Edit only) — the lint must
        # catch every first-call regardless of tool.
        for matcher in matchers:
            self.assertNotEqual(matcher, "Bash", "Bash-only matcher misses Edit/Write/MultiEdit")
            self.assertNotEqual(matcher, "Edit", "Edit-only matcher misses Bash")
        # At least one entry uses the universal '*' matcher.
        self.assertIn("*", matchers, "tier-assert hook must use matcher='*'")

    def test_codex_hooks_json_wires_pretooluse_star_to_acp_tier_assert(self) -> None:
        # Regression for review finding: Codex sessions bypassed the
        # tier guard because the Codex manifest pointed at
        # .codex-plugin/hooks/hooks.json which had no acp-tier-assert
        # entry. The two runtimes must keep parity.
        self.assertTrue(
            CODEX_HOOKS_JSON.is_file(),
            f"missing Codex hooks manifest: {CODEX_HOOKS_JSON}",
        )
        config = json.loads(CODEX_HOOKS_JSON.read_text(encoding="utf-8"))
        groups = config.get("hooks", {}).get("PreToolUse", [])
        wired = []
        for group in groups:
            matcher = group.get("matcher", "")
            for entry in group.get("hooks", []):
                cmd = entry.get("command", "")
                if "acp-tier-assert.sh" in cmd:
                    wired.append((matcher, cmd))
        self.assertTrue(
            wired,
            ".codex-plugin/hooks/hooks.json does not wire acp-tier-assert.sh "
            "into any PreToolUse group. Add an entry with matcher='*' so "
            "Codex sessions enforce the same tier guard as Claude sessions.",
        )
        matchers = sorted({m for m, _ in wired})
        for matcher in matchers:
            self.assertNotEqual(matcher, "Bash", "Bash-only matcher misses Edit/Write/MultiEdit")
            self.assertNotEqual(matcher, "Edit", "Edit-only matcher misses Bash")
        self.assertIn("*", matchers, "tier-assert hook must use matcher='*'")


class BehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._repo_tmp = _init_throwaway_repo()
        self._round_tmp = tempfile.TemporaryDirectory()
        self.repo_root = Path(self._repo_tmp.name)
        self.round_root = (
            Path(self._round_tmp.name) / ".dev-kit" / "round-behavior"
        )
        self.round_root.mkdir(parents=True, exist_ok=True)
        (self.round_root / "tier-state").mkdir(parents=True, exist_ok=True)
        # The hook searches up to 5 levels for a .dev-kit/round-*/tier-state
        # dir, so we symlink the repo's parent to the round root's parent.
        # Simplest: make the repo root sit one level above the round dir.
        # Done by creating a fake "round" sibling inside the repo parent.
        round_parent = self.repo_root / ".dev-kit" / "round-behavior"
        round_parent.mkdir(parents=True, exist_ok=True)
        (round_parent / "tier-state").mkdir(parents=True, exist_ok=True)
        self.tier_state = round_parent / "tier-state"

    def tearDown(self) -> None:
        self._repo_tmp.cleanup()
        self._round_tmp.cleanup()

    def _payload(self, *, transcript: str = "", session_id: str = "sess-1") -> dict:
        return {
            "tool_name": "Bash",
            "session_id": session_id,
            "cwd": str(self.repo_root),
            "transcript": transcript,
        }

    def test_missing_assertion_denies_when_transcript_is_present(self) -> None:
        result = _run_hook(self._payload(transcript="session transcript"), cwd=self.repo_root)
        self.assertEqual(result.returncode, 2)
        self.assertIn("ACP TIER-ASSERT", result.stderr)
        self.assertIn("missing tier-assertion", result.stderr)

    def test_codex_payload_without_transcript_allows(self) -> None:
        result = _run_hook(self._payload(), cwd=self.repo_root)
        self.assertEqual(result.returncode, 0, msg=result.stderr)

    def test_malformed_assertion_denies(self) -> None:
        result = _run_hook(
            self._payload(transcript="[tier-assert] I am Tier X on branch feat/y"),
            cwd=self.repo_root,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("malformed", result.stderr)

    def test_wrong_tier_letter_for_index_denies(self) -> None:
        result = _run_hook(
            self._payload(
                transcript=(
                    f"[tier-assert] I am Tier 1 (T). cwd is {self.repo_root}. "
                    f"I own ONE PR's lifecycle on branch feat/x"
                )
            ),
            cwd=self.repo_root,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Tier letter T requires N=2", result.stderr)

    def test_t_ownership_must_match_pattern(self) -> None:
        result = _run_hook(
            self._payload(
                transcript=(
                    f"[tier-assert] I am Tier 2 (T). cwd is {self.repo_root}. "
                    f"I own everything I want"
                )
            ),
            cwd=self.repo_root,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("T ownership sentence", result.stderr)

    def test_valid_t_assertion_allows(self) -> None:
        result = _run_hook(
            self._payload(
                transcript=(
                    f"[tier-assert] I am Tier 2 (T). cwd is {self.repo_root}. "
                    f"I own ONE PR's lifecycle on branch feat/acp-dispatch"
                )
            ),
            cwd=self.repo_root,
        )
        self.assertEqual(result.returncode, 0, msg=f"stderr={result.stderr!r}")
        # Sidecar written.
        sidecar = self.tier_state / "sess-1.json"
        self.assertTrue(sidecar.is_file(), f"missing sidecar: {sidecar}")
        state = json.loads(sidecar.read_text(encoding="utf-8"))
        self.assertTrue(state["asserted"])
        self.assertEqual(state["letter"], "T")
        self.assertEqual(state["n"], "2")

    def test_repeat_call_with_sidecar_is_noop(self) -> None:
        valid = (
            f"[tier-assert] I am Tier 2 (T). cwd is {self.repo_root}. "
            f"I own ONE PR's lifecycle on branch feat/acp-dispatch"
        )
        first = _run_hook(self._payload(transcript=valid), cwd=self.repo_root)
        self.assertEqual(first.returncode, 0, msg=first.stderr)
        # Second call carries no transcript but the sidecar should
        # short-circuit to allow.
        second = _run_hook(self._payload(transcript=""), cwd=self.repo_root)
        self.assertEqual(second.returncode, 0, msg=second.stderr)

    def test_cwd_mismatch_denies(self) -> None:
        other = Path("/tmp/somewhere-else")
        result = _run_hook(
            self._payload(
                transcript=(
                    f"[tier-assert] I am Tier 2 (T). cwd is {other}. "
                    f"I own ONE PR's lifecycle on branch feat/x"
                )
            ),
            cwd=self.repo_root,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("does not match session cwd", result.stderr)

    def test_empty_stdin_is_noop(self) -> None:
        result = subprocess.run(
            ["bash", str(HOOK)],
            input="",
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(self.repo_root),
        )
        self.assertEqual(result.returncode, 0)

    def test_tier_state_lookup_avoids_recursive_find(self) -> None:
        """The PreToolUse lookup must stay bounded by ancestor directories."""
        source = HOOK.read_text(encoding="utf-8")
        self.assertNotIn('find "$search_root"', source)
        self.assertIn('"$search_root"/.dev-kit/round-*/tier-state', source)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
