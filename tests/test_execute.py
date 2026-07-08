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
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, call, ANY

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


class TestRunSequential(unittest.TestCase):
    """Issue #63: _run_sequential is a stub. Real impl must:
    - create a per-step git worktree (MUST-38)
    - spawn ONE `claude -p` sub-agent per pending step (MUST-36)
    - write step<N>-output.json with REAL subprocess output (no fake 'stub completed')
    - 2-commit protocol: feat(scope) + chore(scope)
    - push the per-step branch when --push is set
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "phases" / "0-mvp").mkdir(parents=True, exist_ok=True)
        (self.root / ".dev-kit").mkdir(parents=True, exist_ok=True)
        # step files for the happy-path fixture (no `blocked` so the runner completes)
        (self.root / "phases" / "0-mvp" / "step1.md").write_text("# Step 1\nTDD red.\n", encoding="utf-8")
        (self.root / "phases" / "0-mvp" / "step2.md").write_text("# Step 2\nTDD green.\n", encoding="utf-8")
        idx = {
            "project": "test-project",
            "phase": "0-mvp",
            "worktree": "feat/test-phase",
            "created_at": "2026-07-04T00:00:00+09:00",
            "steps": [
                {"step": 1, "name": "red",  "status": "pending"},
                {"step": 2, "name": "done", "status": "completed",
                 "started_at": "2026-07-04T00:00:00+09:00",
                 "completed_at": "2026-07-04T00:01:00+09:00",
                 "duration_seconds": 60.0},
                {"step": 3, "name": "stub", "status": "unimplemented"},
            ],
        }
        (self.root / "phases" / "0-mvp" / "index.json").write_text(json.dumps(idx), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _fake_proc(self, returncode=0, stdout="green", stderr=""):
        """Build a MagicMock that looks like a subprocess.CompletedProcess."""
        m = MagicMock()
        m.returncode = returncode
        m.stdout = stdout
        m.stderr = stderr
        return m

    def _make_blocked_root(self):
        """Alternate fixture: pending step + blocked step (bails with 2)."""
        root = self.root.parent / "blocked-fixture"
        if root.exists():
            import shutil as _sh
            _sh.rmtree(root)
        (root / "phases" / "0-mvp").mkdir(parents=True)
        (root / "phases" / "0-mvp" / "step1.md").write_text("# Step 1\n", encoding="utf-8")
        (root / "phases" / "0-mvp" / "index.json").write_text(json.dumps({
            "phase": "0-mvp",
            "worktree": "feat/x",
            "steps": [
                {"step": 1, "name": "ok", "status": "pending"},
                {"step": 2, "name": "no", "status": "blocked",
                 "blocked_at": "2026-07-04T00:00:00+09:00",
                 "blocked_reason": "user paused"},
            ],
        }), encoding="utf-8")
        return root

    def test_skippable_status_does_not_invoke_runner(self):
        with patch.object(execute.subprocess, "run") as mr:
            mr.return_value = self._fake_proc()
            rc = execute._run_sequential(self.root, "0-mvp", push=False)
            # 1 pending step → 1 worktree add + 1 claude + 2 commits. completed + unimplemented = skip.
            self.assertEqual(rc, 0)
            claude_calls = [c for c in mr.call_args_list if "claude" in c.args[0]]
            wt_add_calls = [c for c in mr.call_args_list if "worktree" in c.args[0]]
            self.assertEqual(len(claude_calls), 1, f"expected 1 claude call, got {mr.call_args_list}")
            self.assertEqual(len(wt_add_calls), 1, f"expected 1 worktree add, got {mr.call_args_list}")

    def test_blocked_status_returns_2(self):
        root = self._make_blocked_root()
        with patch.object(execute.subprocess, "run") as mr:
            mr.return_value = self._fake_proc()
            rc = execute._run_sequential(root, "0-mvp", push=False)
            self.assertEqual(rc, 2)
            # Step 1 ran (pending → resume) then step 2 blocked bails. Only 1 claude spawn total.
            claude_calls = [c for c in mr.call_args_list if "claude" in c.args[0]]
            self.assertEqual(len(claude_calls), 1, "only the pending step may run; blocked bails the rest")

    def test_pending_step_creates_worktree_and_invokes_claude(self):
        with patch.object(execute.subprocess, "run") as mr:
            mr.return_value = self._fake_proc(stdout="all green", stderr="")
            rc = execute._run_sequential(self.root, "0-mvp", push=False)
            self.assertEqual(rc, 0)
            # Inspect worktree add args (per-step branch derived from index.worktree)
            wt_add = next(c for c in mr.call_args_list if "worktree" in c.args[0])
            args = wt_add.args[0]
            self.assertIn("worktree", args)
            self.assertIn("add", args)
            self.assertIn("-B", args)
            self.assertIn("feat/test-phase-step1", args)  # branch = f"{worktree}-step{n}"
            self.assertEqual(args[-1], "origin/main")
            self.assertEqual(args[-2].endswith("0-mvp-step1"), True, f"worktree path wrong: {args[-2]}")
            # Inspect claude -p invocation
            claude = next(c for c in mr.call_args_list if c.args[0][0] == "claude")
            cmd = claude.args[0]
            self.assertEqual(cmd[0], "claude")
            self.assertEqual(cmd[1], "-p")
            workdir = claude.kwargs.get("cwd") or next((a for a in cmd if ".claude/worktrees" in a), None)
            self.assertIsNotNone(workdir, f"claude -p missing workdir; cmd={cmd}")
            # The preamble (from step1.md) is in the trailing prompt arg
            joined = " ".join(cmd)
            self.assertIn("TDD red", joined, f"preamble not in prompt: {cmd}")
            self.assertIn("3-cycle self-fix", joined, f"AC guard not appended: {cmd}")
            # step output file written with REAL contents (no 'stub completed')
            out = json.loads((self.root / "phases" / "0-mvp" / "step1-output.json").read_text())
            self.assertEqual(out["exit_code"], 0)
            self.assertEqual(out["stdout"], "all green")
            self.assertNotIn("stub completed", out["stdout"])
            # Status flipped to completed with real (non-fake) duration.
            idx = json.loads((self.root / "phases" / "0-mvp" / "index.json").read_text())
            step1 = next(s for s in idx["steps"] if s["step"] == 1)
            self.assertEqual(step1["status"], "completed")
            self.assertIn("duration_seconds", step1)
            self.assertGreaterEqual(step1["duration_seconds"], 0.0)

    def test_two_commit_protocol_per_step(self):
        with patch.object(execute.subprocess, "run") as mr:
            mr.return_value = self._fake_proc()
            rc = execute._run_sequential(self.root, "0-mvp", push=False)
            self.assertEqual(rc, 0)
            commits = [c for c in mr.call_args_list if c.args[0][:2] == ["git", "commit"]]
            self.assertEqual(len(commits), 2, f"expected 2 commits, got {len(commits)}: {commits}")
            joined_args = "\n".join(" ".join(c.args[0]) for c in commits)
            self.assertIn("feat(0-mvp): step 1", joined_args)
            self.assertIn("chore(0-mvp): step 1 output", joined_args)

    def test_no_commit_on_failure(self):
        with patch.object(execute.subprocess, "run") as mr:
            mr.return_value = self._fake_proc(returncode=1, stdout="", stderr="boom")
            rc = execute._run_sequential(self.root, "0-mvp", push=False)
            self.assertEqual(rc, 1)
            commits = [c for c in mr.call_args_list if c.args[0][:2] == ["git", "commit"]]
            self.assertEqual(commits, [], f"no commits expected on failure, got {commits}")
            idx = json.loads((self.root / "phases" / "0-mvp" / "index.json").read_text())
            step1 = next(s for s in idx["steps"] if s["step"] == 1)
            self.assertEqual(step1["status"], "error")
            self.assertIn("error_message", step1)

    def test_push_only_when_flag(self):
        with patch.object(execute.subprocess, "run") as mr:
            mr.return_value = self._fake_proc()
            execute._run_sequential(self.root, "0-mvp", push=False)
            pushes = [c for c in mr.call_args_list if c.args[0][:2] == ["git", "push"]]
            self.assertEqual(pushes, [], "no push expected when push=False")
        # Use a fresh tmp dir for the push=True case so step 1 is still pending.
        fresh_tmp = tempfile.TemporaryDirectory()
        fresh_root = Path(fresh_tmp.name)
        (fresh_root / "phases" / "0-mvp").mkdir(parents=True)
        (fresh_root / "phases" / "0-mvp" / "step1.md").write_text("# Step 1\n", encoding="utf-8")
        (fresh_root / "phases" / "0-mvp" / "index.json").write_text(json.dumps({
            "phase": "0-mvp",
            "worktree": "feat/test-phase",
            "steps": [{"step": 1, "name": "x", "status": "pending"}],
        }), encoding="utf-8")
        with patch.object(execute.subprocess, "run") as mr:
            mr.return_value = self._fake_proc()
            rc = execute._run_sequential(fresh_root, "0-mvp", push=True)
            self.assertEqual(rc, 0)
            pushes = [c for c in mr.call_args_list if c.args[0][:2] == ["git", "push"]]
            self.assertGreaterEqual(len(pushes), 1, "expected at least 1 push when push=True")
        fresh_tmp.cleanup()


class TestRunParallel(unittest.TestCase):
    """Issue #63: _run_parallel is a stub. Real impl spawns N subprocesses with worktree
    isolation. Slots run concurrently — wall clock bounded by slowest, not sum."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "phases" / "0-mvp").mkdir(parents=True, exist_ok=True)
        for n in range(1, 4):
            (self.root / "phases" / "0-mvp" / f"step{n}.md").write_text(f"# Step {n}\n", encoding="utf-8")
        (self.root / "phases" / "0-mvp" / "index.json").write_text(json.dumps({
            "project": "p",
            "phase": "0-mvp",
            "worktree": "feat/par",
            "steps": [
                {"step": 1, "name": "a", "status": "pending"},
                {"step": 2, "name": "b", "status": "pending"},
                {"step": 3, "name": "c", "status": "pending"},
            ],
        }), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _fake_proc(self, returncode=0, stdout="ok", stderr=""):
        m = MagicMock()
        m.returncode = returncode
        m.stdout = stdout
        m.stderr = stderr
        return m

    def test_parallel_runs_n_slots(self):
        with patch.object(execute.subprocess, "run") as mr_run, \
             patch.object(execute.subprocess, "Popen") as mr_popen:
            # worktree add subprocess.run: just succeeds silently.
            mr_run.return_value = self._fake_proc()
            # Each Popen returns a fake 'already finished' proc.
            proc_mock = MagicMock()
            proc_mock.poll.return_value = 0  # exited immediately
            proc_mock.returncode = 0
            proc_mock.communicate.return_value = ("ok", "")
            mr_popen.return_value = proc_mock
            rc = execute._run_parallel(self.root, "0-mvp", n=2, push=False)
            self.assertEqual(rc, 0)
            # wall-clock bounded by N (slot count) — each Popen call is a slot launch
            self.assertGreaterEqual(mr_popen.call_count, 1)
            self.assertLessEqual(mr_popen.call_count, 2)
            # Each spawn used `claude -p` (MUST-36 — single sub-agent per slot)
            for c in mr_popen.call_args_list:
                cmd = c.args[0]
                self.assertEqual(cmd[0], "claude", f"expected claude CLI spawn, got: {cmd}")
                self.assertEqual(cmd[1], "-p")
            # worktree add was called for each step that ran (1 per step)
            wt_add_calls = [c for c in mr_run.call_args_list
                            if "worktree" in c.args[0]]
            self.assertGreaterEqual(len(wt_add_calls), 1)

    def test_parallel_returns_nonzero_on_slot_failure(self):
        with patch.object(execute.subprocess, "run") as mr_run, \
             patch.object(execute.subprocess, "Popen") as mr_popen:
            mr_run.return_value = self._fake_proc()
            proc_mock = MagicMock()
            proc_mock.poll.return_value = 1
            proc_mock.returncode = 1
            proc_mock.communicate.return_value = ("", "boom")
            mr_popen.return_value = proc_mock
            rc = execute._run_parallel(self.root, "0-mvp", n=1, push=False)
            self.assertEqual(rc, 1, "non-zero exit from any slot must surface as rc=1")


if __name__ == "__main__":
    unittest.main(verbosity=2)