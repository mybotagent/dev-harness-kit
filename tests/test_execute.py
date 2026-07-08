#!/usr/bin/env python3
"""
test_execute.py — RED-first tests for execute.py (harness-runner engine).

Tests cover:
- read_step prompt text from phases/<phase>/step<N>.md
- parse_step_index step status transitions
- write_step_output atomic
- issue #18: state machine with unimplemented + in_progress + started_at + duration_seconds
- issue #18: register_step() helper for unimplemented stubs
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

    # === New statuses (issue #18): unimplemented + in_progress ===

    def test_in_progress_sets_started_at(self):
        idx_path = self.root / "phases" / "0-mvp" / "index.json"
        execute.update_step_status(self.root, "0-mvp", step=0, status="in_progress")
        parsed = execute.parse_step_index(idx_path)
        self.assertEqual(parsed[0]["status"], "in_progress")
        self.assertIn("started_at", parsed[0])

    def test_in_progress_to_completed_records_duration_from_started_at(self):
        idx_path = self.root / "phases" / "0-mvp" / "index.json"
        execute.update_step_status(self.root, "0-mvp", step=0, status="in_progress")
        # Back-date started_at so duration is non-zero + deterministic.
        data = json.loads(idx_path.read_text())
        for s in data["steps"]:
            if s["step"] == 0:
                s["started_at"] = "2026-07-04T00:00:00+09:00"
        idx_path.write_text(json.dumps(data), encoding="utf-8")
        execute.update_step_status(self.root, "0-mvp", step=0, status="completed")
        parsed = execute.parse_step_index(idx_path)
        self.assertEqual(parsed[0]["status"], "completed")
        self.assertIn("completed_at", parsed[0])
        self.assertIn("duration_seconds", parsed[0])
        self.assertGreater(parsed[0]["duration_seconds"], 0.0)

    def test_in_progress_to_completed_accepts_explicit_duration(self):
        idx_path = self.root / "phases" / "0-mvp" / "index.json"
        execute.update_step_status(self.root, "0-mvp", step=0, status="in_progress")
        execute.update_step_status(self.root, "0-mvp", step=0, status="completed", duration_seconds=4.2)
        parsed = execute.parse_step_index(idx_path)
        self.assertEqual(parsed[0]["duration_seconds"], 4.2)

    def test_in_progress_does_not_overwrite_started_at_on_resume(self):
        """If a crashed run left in_progress with started_at, resuming → in_progress
        must keep the ORIGINAL started_at (so duration measures total elapsed time,
        not just the post-resume chunk)."""
        idx_path = self.root / "phases" / "0-mvp" / "index.json"
        original_started = "2026-07-04T00:00:00+09:00"
        data = json.loads(idx_path.read_text())
        for s in data["steps"]:
            if s["step"] == 0:
                s["started_at"] = original_started
                s["status"] = "in_progress"
        idx_path.write_text(json.dumps(data), encoding="utf-8")
        # Resume — should NOT overwrite started_at.
        execute.update_step_status(self.root, "0-mvp", step=0, status="in_progress")
        parsed = execute.parse_step_index(idx_path)
        self.assertEqual(parsed[0]["started_at"], original_started,
                         "started_at was overwritten on re-in_progress")

    def test_unimplemented_status_is_valid(self):
        idx_path = self.root / "phases" / "0-mvp" / "index.json"
        execute.update_step_status(self.root, "0-mvp", step=0, status="unimplemented")
        parsed = execute.parse_step_index(idx_path)
        self.assertEqual(parsed[0]["status"], "unimplemented")
        self.assertNotIn("started_at", parsed[0])
        self.assertNotIn("completed_at", parsed[0])

    def test_full_cycle_pending_in_progress_completed(self):
        idx_path = self.root / "phases" / "0-mvp" / "index.json"
        execute.update_step_status(self.root, "0-mvp", step=0, status="in_progress")
        execute.update_step_status(self.root, "0-mvp", step=0, status="completed")
        parsed = execute.parse_step_index(idx_path)
        self.assertEqual(parsed[0]["status"], "completed")
        self.assertIn("started_at", parsed[0])
        self.assertIn("completed_at", parsed[0])

    def test_pending_reset_clears_started_at_and_duration(self):
        """Transitioning any state → pending must clear started_at and duration
        so a fresh execution measures cleanly from zero."""
        idx_path = self.root / "phases" / "0-mvp" / "index.json"
        execute.update_step_status(self.root, "0-mvp", step=0, status="in_progress")
        execute.update_step_status(self.root, "0-mvp", step=0, status="completed", duration_seconds=9.9)
        execute.update_step_status(self.root, "0-mvp", step=0, status="pending")
        parsed = execute.parse_step_index(idx_path)
        self.assertEqual(parsed[0]["status"], "pending")
        self.assertNotIn("started_at", parsed[0])
        self.assertNotIn("duration_seconds", parsed[0])


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


class TestUnimplementedStubRegistration(unittest.TestCase):
    """register_step() creates an `unimplemented` stub in index.json so the plan
    skill can mark 'this phase will have N steps' BEFORE any step<N>.md is written.
    Then the runner SKIPS these entries (see SKIPPABLE_STATUSES)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "phases" / "0-mvp").mkdir(parents=True, exist_ok=True)
        # Empty phase — no index.json yet.
        self.assertFalse((self.root / "phases" / "0-mvp" / "index.json").exists())

    def tearDown(self):
        self.tmp.cleanup()

    def test_register_step_creates_index_and_stub(self):
        execute.register_step(self.root, "0-mvp", step=2, name="future-step")
        idx_path = self.root / "phases" / "0-mvp" / "index.json"
        self.assertTrue(idx_path.exists())
        data = json.loads(idx_path.read_text())
        self.assertEqual(len(data["steps"]), 1)
        self.assertEqual(data["steps"][0]["step"], 2)
        self.assertEqual(data["steps"][0]["name"], "future-step")
        self.assertEqual(data["steps"][0]["status"], "unimplemented")

    def test_register_step_is_idempotent(self):
        execute.register_step(self.root, "0-mvp", step=2, name="future-step")
        execute.register_step(self.root, "0-mvp", step=2, name="future-step")
        data = json.loads((self.root / "phases" / "0-mvp" / "index.json").read_text())
        self.assertEqual(len(data["steps"]), 1, "register_step must not duplicate entries")

    def test_register_step_appends_to_existing_index(self):
        # Pre-existing pending step 0.
        idx_path = self.root / "phases" / "0-mvp" / "index.json"
        idx_path.write_text(json.dumps({
            "schema_version": execute.SCHEMA_VERSION,
            "phase": "0-mvp",
            "steps": [{"step": 0, "name": "setup", "status": "pending"}],
        }), encoding="utf-8")
        execute.register_step(self.root, "0-mvp", step=2, name="future-step")
        data = json.loads(idx_path.read_text())
        self.assertEqual(len(data["steps"]), 2)
        self.assertEqual(data["steps"][0]["status"], "pending")  # existing step untouched
        self.assertEqual(data["steps"][1]["status"], "unimplemented")

    def test_register_step_does_not_overwrite_existing_unimplemented(self):
        """If a stub already exists for this step number, preserve any user-set fields."""
        execute.register_step(self.root, "0-mvp", step=2, name="future-step")
        # Re-register with different name — should keep the FIRST name (idempotent).
        execute.register_step(self.root, "0-mvp", step=2, name="renamed")
        data = json.loads((self.root / "phases" / "0-mvp" / "index.json").read_text())
        self.assertEqual(data["steps"][0]["name"], "future-step")


if __name__ == "__main__":
    unittest.main(verbosity=2)