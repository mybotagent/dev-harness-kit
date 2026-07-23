#!/usr/bin/env python3
"""Regression tests for the model-use hook-doctor diagnostic."""
from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).parent.parent
SKILL = ROOT / "skills" / "hook-doctor" / "SKILL.md"
DOCTOR = ROOT / "skills" / "hook-doctor" / "scripts" / "doctor.sh"


class TestHookDoctor(unittest.TestCase):
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
        result = subprocess.run(
            ["bash", str(DOCTOR), "/tmp"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env={**os.environ, "DEV_KIT_PROVIDER": "codex"},
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RESULT BLOCKED", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
