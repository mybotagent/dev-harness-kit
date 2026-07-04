#!/usr/bin/env python3
"""test_methodology.py — RED-first tests for methodology/tdd.py + selector."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from methodology import tdd, get_methodology, list_methodologies  # noqa: E402


class TestTddMethodology(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_tdd_name(self):
        self.assertEqual(tdd.INSTANCE.name, "tdd")

    def test_tdd_cycle(self):
        self.assertEqual(tdd.INSTANCE.cycle_steps(), ["red", "green", "refactor"])

    def test_pre_check_returns_failing_test_path(self):
        step = {"name": "auth_login"}
        result = tdd.INSTANCE.pre_check(self.root, step)
        self.assertEqual(result["artifact_path"], "tests/test_auth_login.py")
        self.assertIn("RED", result["expected_content"])
        self.assertIn("pytest", result["verification_cmd"])

    def test_verification_command_includes_pytest(self):
        step = {"name": "feature"}
        cmds = tdd.INSTANCE.verification_command(self.root, step)
        self.assertEqual(len(cmds), 3)
        self.assertTrue(any("pytest" in c for c in cmds))
        self.assertTrue(any("ruff" in c for c in cmds))

    def test_report_status_pass(self):
        status = tdd.INSTANCE.report_status(self.root, {})
        self.assertEqual(status["status"], "pass")


class TestSelector(unittest.TestCase):
    def test_get_tdd(self):
        m = get_methodology("tdd")
        self.assertEqual(m.name, "tdd")

    def test_get_unknown_raises(self):
        with self.assertRaises(KeyError):
            get_methodology("nonexistent")

    def test_list(self):
        names = list_methodologies()
        self.assertIn("tdd", names)


class TestMethodologyJson(unittest.TestCase):
    def test_methodology_json_valid(self):
        path = Path(__file__).parent.parent / "lib" / "methodology.json"
        data = json.loads(path.read_text())
        self.assertEqual(data["active"], "tdd")
        self.assertIn("tdd", data["available"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
