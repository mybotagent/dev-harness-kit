from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCRIPT = ROOT / "bin" / "dev-kit-hooks-status.py"


class TestHooksStatus(unittest.TestCase):
    def run_status(self, root: Path) -> dict:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--root", str(root), "--json"],
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(result.stdout)

    def test_codex_manifest_registers_shared_hook_definition(self):
        manifest = json.loads((ROOT / ".codex-plugin" / "plugin.json").read_text())
        self.assertEqual(manifest["hooks"], "./.codex-plugin/hooks/hooks.json")
        codex_hooks = ROOT / manifest["hooks"]
        self.assertTrue(codex_hooks.is_file(), f"missing Codex plugin hooks: {codex_hooks}")
        claude_text = (ROOT / "hooks" / "hooks.json").read_text()
        codex_text = codex_hooks.read_text()
        codex_config = json.loads(codex_text)
        claude_config = json.loads(claude_text)

        # Codex parses plugin hook definitions with its own narrow schema.
        # Claude settings metadata such as `$schema` and `_comment` must not
        # leak into the bundled Codex definition.
        self.assertEqual(
            set(codex_config),
            {"description", "hooks"},
            "Codex hook definitions must contain only Codex schema fields",
        )
        self.assertIsInstance(codex_config["description"], str)
        self.assertIn("${PLUGIN_ROOT}", codex_text)
        self.assertNotIn("${CLAUDE_PLUGIN_ROOT}", codex_text)
        self.assertIn("${CLAUDE_PLUGIN_ROOT}", claude_text)
        self.assertNotIn("${PLUGIN_ROOT}", claude_text)
        self.assertEqual(
            codex_config["hooks"].keys(),
            claude_config["hooks"].keys(),
            "Codex and Claude hook events must stay synchronized",
        )

    def test_shared_definition_keeps_the_complete_claude_hook_inventory(self):
        config = json.loads((ROOT / "hooks" / "hooks.json").read_text())
        expected = {
            "PreToolUse": {
                "tdd-guard.sh", "worktree-guard.sh", "bash-guard.sh",
                "git-guard.sh",
            },
            "UserPromptSubmit": {"task-detector.sh", "worktree-auto-cut.sh"},
            "SessionStart": {
                "session-start-check.sh", "log-on-session-start.sh",
            },
            "PostToolUse": {
                "secret-scan.sh", "slop-detector.sh",
                "worktree-log-auto-install.sh",
            },
            "Stop": {"stop-verify.sh"},
        }
        actual = {
            event: {
                command.rsplit("/", 1)[-1]
                for group in config["hooks"].get(event, [])
                for hook in group.get("hooks", [])
                for command in [hook.get("command", "")]
            }
            for event in expected
        }
        for event, scripts in expected.items():
            for script in scripts:
                self.assertIn(script, actual[event], f"Claude hook removed from {event}: {script}")

    def test_reports_shared_events_and_git_configuration(self):
        result = self.run_status(ROOT)
        self.assertTrue(result["claude"]["hooks_registered"])
        self.assertTrue(result["codex"]["hooks_registered"])
        self.assertTrue({"PreToolUse", "UserPromptSubmit", "SessionStart", "PostToolUse", "Stop"}.issubset(result["source_hooks"]["events"]))
        self.assertIn("configured_hooks_path", result["git"])

    def test_reports_active_git_hook_when_configured(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".githooks").mkdir()
            pre_push = root / ".githooks" / "pre-push"
            pre_push.write_text("#!/bin/sh\n")
            pre_push.chmod(0o755)
            subprocess.run(["git", "init", str(root)], capture_output=True, check=True)
            subprocess.run(["git", "-C", str(root), "config", "core.hooksPath", ".githooks"], check=True)
            self.assertTrue(self.run_status(root)["git"]["pre_push_active"])


if __name__ == "__main__":
    unittest.main()
