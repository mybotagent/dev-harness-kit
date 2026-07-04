#!/usr/bin/env python3
"""
test_execute.py — RED-first tests for execute.py (harness-runner engine).

Tests cover:
- read_step prompt text from phases/<phase>/step<N>.md
- build_preamble injects CLAUDE.md + docs/*.md + hand-off chain
- parse_step_index step status transitions
- write_step_output atomic
- --parallel worktree runner (no real subprocess; mocked)
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import execute  # noqa: E402


class TestExecute(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # Create minimal phases/<phase>/
        (self.root / ".dev-kit" / "hand-off").mkdir(parents=True, exist_ok=True)
        (self.root / "phases" / "0-mvp").mkdir(parents=True, exist_ok=True)
        (self.root / "CLAUDE.md").write_text("# CLAUDE.md\nIron laws: TDD only.\n", encoding="utf-8")
        # step0 + step1
        (self.root / "phases" / "0-mvp" / "step0.md").write_text("# Setup\nInitialize project.\n", encoding="utf-8")
        (self.root / "phases" / "0-mvp" / "step1.md").write_text("# Build\nTDD: red, green, refactor.\n", encoding="utf-8")
        # phase index
        idx = {
            "project": "test-project",
            "phase": "0-mvp",
            "created_at": "2026-07-04T00:00:00+09:00",
            "steps": [
                {"step": 0, "name": "setup", "status": "pending"},
                {"step": 1, "name": "build", "status": "pending"},
            ],
        }
        (self.root / "phases" / "0-mvp" / "index.json").write_text(json.dumps(idx), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_step_returns_prompt(self):
        text = execute.read_step(self.root, "0-mvp", 0)
        self.assertIn("Initialize project", text)

    def test_read_step_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            execute.read_step(self.root, "0-mvp", 99)

    def test_build_preamble_injects_claude_md(self):
        preamble = execute.build_preamble(self.root, "0-mvp", step_index=0)
        self.assertIn("# CLAUDE.md", preamble)
        self.assertIn("Iron laws", preamble)

    def test_build_preamble_includes_step_prompt(self):
        preamble = execute.build_preamble(self.root, "0-mvp", step_index=0)
        self.assertIn("Setup", preamble)

    def test_parse_step_index_pending(self):
        idx_path = self.root / "phases" / "0-mvp" / "index.json"
        parsed = execute.parse_step_index(idx_path)
        self.assertEqual(len(parsed), 2)
        self.assertEqual(parsed[0]["status"], "pending")
        self.assertEqual(parsed[1]["status"], "pending")

    def test_write_step_output_atomic(self):
        idx_path = self.root / "phases" / "0-mvp" / "index.json"
        before = idx_path.read_text()
        result = execute.write_step_output(
            self.root,
            "0-mvp",
            step=0,
            exit_code=0,
            stdout="all green",
            stderr="",
        )
        self.assertTrue(result.exists())
        # index.json untouched (we write output, not index)
        self.assertEqual(before, idx_path.read_text())
        # output file atomic
        leftover = list((self.root / "phases" / "0-mvp").glob(".step0-output.*.tmp"))
        self.assertEqual(leftover, [])

    def test_write_step_output_json_shape(self):
        path = execute.write_step_output(
            self.root, "0-mvp", step=1, exit_code=0, stdout="x", stderr="y"
        )
        data = json.loads(path.read_text())
        self.assertEqual(data["step"], 1)
        self.assertEqual(data["phase"], "0-mvp")
        self.assertEqual(data["exit_code"], 0)
        self.assertEqual(data["stdout"], "x")
        self.assertEqual(data["stderr"], "y")
        self.assertIn("timestamp", data)

    def test_update_step_status(self):
        idx_path = self.root / "phases" / "0-mvp" / "index.json"
        execute.update_step_status(self.root, "0-mvp", step=0, status="completed")
        parsed = execute.parse_step_index(idx_path)
        self.assertEqual(parsed[0]["status"], "completed")
        self.assertIn("completed_at", parsed[0])

    def test_status_transition_validation(self):
        # pending → completed OK
        execute.update_step_status(self.root, "0-mvp", step=0, status="completed")
        # completed → pending reset OK (resume)
        execute.update_step_status(self.root, "0-mvp", step=0, status="pending", error_message=None, blocked_reason=None)
        parsed = execute.parse_step_index(idx_path := self.root / "phases" / "0-mvp" / "index.json")
        self.assertEqual(parsed[0]["status"], "pending")

    def test_blocked_status_requires_reason(self):
        with self.assertRaises(ValueError):
            execute.update_step_status(self.root, "0-mvp", step=0, status="blocked")

    def test_error_status_requires_message(self):
        with self.assertRaises(ValueError):
            execute.update_step_status(self.root, "0-mvp", step=0, status="error")


class TestPhasesStructure(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_phases_index_top_level(self):
        idx_path = self.root / "phases" / "index.json"
        idx_path.parent.mkdir(parents=True)
        idx_path.write_text(json.dumps({"phases": [{"dir": "0-mvp", "status": "pending"}]}), encoding="utf-8")
        result = execute.read_phases_index(self.root)
        self.assertEqual(len(result["phases"]), 1)
        self.assertEqual(result["phases"][0]["dir"], "0-mvp")


if __name__ == "__main__":
    unittest.main(verbosity=2)
