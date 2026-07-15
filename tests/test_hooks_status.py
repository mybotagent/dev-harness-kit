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
        self.assertEqual(manifest["hooks"], "./hooks/hooks.json")

    def test_reports_shared_events_and_git_configuration(self):
        result = self.run_status(ROOT)
        self.assertTrue(result["claude"]["hooks_registered"])
        self.assertTrue(result["codex"]["hooks_registered"])
        self.assertTrue({"PreToolUse", "UserPromptSubmit", "SessionStart", "Stop"}.issubset(result["source_hooks"]["events"]))
        self.assertTrue(result["git"]["configured_hooks_path"])

    def test_reports_active_git_hook_when_configured(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".githooks").mkdir()
            (root / ".githooks" / "pre-push").write_text("#!/bin/sh\n")
            subprocess.run(["git", "init", str(root)], capture_output=True, check=True)
            subprocess.run(["git", "-C", str(root), "config", "core.hooksPath", ".githooks"], check=True)
            self.assertTrue(self.run_status(root)["git"]["pre_push_active"])


if __name__ == "__main__":
    unittest.main()
