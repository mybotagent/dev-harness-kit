#!/usr/bin/env python3
"""Regression tests for the model-use hook-doctor diagnostic."""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
SKILL = ROOT / "skills" / "hook-doctor" / "SKILL.md"
DOCTOR = ROOT / "skills" / "hook-doctor" / "scripts" / "doctor.sh"


class TestHookDoctor(unittest.TestCase):
    def _run(self, root: Path, provider: str = "auto") -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(DOCTOR), str(root)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env={**os.environ, "DEV_KIT_PROVIDER": provider, "PLUGIN_ROOT": str(root)},
            check=False,
        )

    def test_skill_is_model_use_and_enforcement_alpha(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("alpha: enforcement", text)
        self.assertIn("user-invocable: false", text)
        self.assertIn("hook exited with code", text)

    def test_doctor_reports_provider_manifests(self):
        result = subprocess.run(
            ["bash", str(DOCTOR)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("manifest:", result.stdout)
        self.assertIn("RESULT PASS", result.stdout)

    def test_missing_manifest_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(Path(directory), "codex")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RESULT BLOCKED", result.stdout)

    def test_auto_mode_does_not_fall_back_to_repository_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self._run(Path(directory))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no active provider hook manifest", result.stdout)

    def test_malformed_manifest_is_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / ".codex-plugin" / "hooks"
            manifest.mkdir(parents=True)
            (root / ".codex-plugin" / "plugin.json").write_text(
                '{"version":"0.3.123"}', encoding="utf-8"
            )
            (manifest / "hooks.json").write_text("{broken", encoding="utf-8")
            result = self._run(root, "codex")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not valid JSON", result.stdout)

    def test_cache_directory_version_must_match_plugin_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "plugins" / "cache" / "dev-kit" / "0.3.122"
            manifest = root / ".codex-plugin" / "hooks"
            manifest.mkdir(parents=True)
            (root / ".codex-plugin" / "plugin.json").write_text(
                '{"version":"0.3.123"}', encoding="utf-8"
            )
            (manifest / "hooks.json").write_text(
                '{"hooks":{"SessionStart":[{"hooks":[{"command":"bash ${PLUGIN_ROOT}/hooks/session-start-check.sh"}]}]}}',
                encoding="utf-8",
            )
            (root / "hooks").mkdir()
            (root / "hooks" / "session-start-check.sh").touch()
            result = self._run(root, "codex")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("differs from plugin version", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
