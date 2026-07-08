#!/usr/bin/env python3
"""
execute.py — harness-runner engine (per step executor).

Adapted from harness_framework/scripts/execute.py (sh-ai-x/harness_framework) — plan §5.
Adds:
- 2-commit protocol (feat + chore)
- atomic step<N>-output.json
- status state-machine:
    unimplemented → pending → in_progress → completed
                                       ↘ error  → pending (resume)
                                       ↘ blocked → pending (human unblock)
    completed → pending (manual reset)
- per-step timing: started_at set on in_progress; completed_at + duration_seconds on completed
- MAX_RETRIES = 3 self-correction
- --parallel mode (worktree, N-step concurrent)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atomic import atomic_write_json, now_iso  # noqa: E402
MAX_RETRIES = 3
SCHEMA_VERSION = "1.0.0"
# Step lifecycle. Order roughly matches the typical progression; entries are
# enforced by update_step_status() and indexed/queried by tests/CLI.
VALID_STATUSES = (
    "unimplemented",  # step.md not yet written; stub registered in index.json
    "pending",        # step.md written, runner hasn't started
    "in_progress",    # runner executing this step
    "completed",      # finished successfully
    "error",          # execution failed; resume by transitioning to pending
    "blocked",        # user intervention required; unblock by transitioning to pending
)
# Statuses from which the runner can RESUME a step (i.e. start it now).
RESUMABLE_STATUSES = ("pending", "error", "in_progress")
# Statuses the runner SKIPS without doing anything.
SKIPPABLE_STATUSES = ("completed", "unimplemented")


# ---------- Phase / Step readers ----------

def read_phases_index(project_root: Path) -> Dict:
    """Read phases/index.json (top-level)."""
    path = project_root / "phases" / "index.json"
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "phases": []}
    return json.loads(path.read_text(encoding="utf-8"))


def parse_step_index(idx_path: Path) -> List[Dict]:
    """Parse phases/<phase>/index.json into the steps list."""
    return json.loads(idx_path.read_text(encoding="utf-8")).get("steps", [])


def read_step(project_root: Path, phase: str, step: int) -> str:
    """Read phases/<phase>/step<N>.md prompt verbatim."""
    path = project_root / "phases" / phase / f"step{step}.md"
    if not path.exists():
        raise FileNotFoundError(f"step file not found: {path}")
    return path.read_text(encoding="utf-8")


def register_step(
    project_root: Path,
    phase: str,
    step: int,
    name: str,
) -> None:
    """Register a step in phases/<phase>/index.json as `unimplemented`.

    Idempotent: if a stub for this step number already exists, this is a no-op.
    Used by the plan skill to pre-register step counts BEFORE writing step<N>.md —
    gives external observers visibility into "this phase plans N steps, K of which
    are written so far".

    The `unimplemented` status is in SKIPPABLE_STATUSES, so the runner ignores it.
    Once plan writes step<N>.md, it transitions the stub to `pending` via
    update_step_status() and the runner picks it up on the next run.
    """
    idx_path = project_root / "phases" / phase / "index.json"
    if idx_path.exists():
        data = json.loads(idx_path.read_text(encoding="utf-8"))
    else:
        idx_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"schema_version": SCHEMA_VERSION, "phase": phase, "steps": []}
    for s in data.get("steps", []):
        if s.get("step") == step:
            return  # already registered — preserve any user-set fields
    data.setdefault("steps", []).append({
        "step": step,
        "name": name,
        "status": "unimplemented",
    })
    atomic_write_json(idx_path, data)


# ---------- Step status state machine ----------

def update_step_status(
    project_root: Path,
    phase: str,
    step: int,
    status: str,
    error_message: Optional[str] = None,
    blocked_reason: Optional[str] = None,
    duration_seconds: Optional[float] = None,
) -> None:
    """Update a single step's status with validation + atomic write.

    Args:
        status: one of VALID_STATUSES. New: "unimplemented" (initial stub)
            and "in_progress" (runner started) are now first-class.
        duration_seconds: optional wall-clock duration; when transitioning
            to "completed" and not provided, computed from started_at.

    Side effects on the step entry in `phases/<phase>/index.json`:
        pending → unimplemented: clears all timestamps (no-op)
        unimplemented → pending: clears all timestamps
        pending → in_progress: sets started_at (idempotent — does NOT overwrite
                               if already present, so resume after crash keeps
                               the original start time)
        in_progress → completed: sets completed_at; sets duration_seconds
                              (from arg or computed from started_at)
        in_progress → error: sets failed_at + error_message
        in_progress → blocked: sets blocked_at + blocked_reason
        any → pending (reset): clears completed_at/failed_at/blocked_at/
                              error_message/blocked_reason/started_at/
                              duration_seconds
        any → completed (manual): sets completed_at; clears error/blocked
                                  fields. duration_seconds optional.
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}. Valid: {VALID_STATUSES}")
    if status == "blocked" and not blocked_reason:
        raise ValueError("status 'blocked' requires blocked_reason")
    if status == "error" and not error_message:
        raise ValueError("status 'error' requires error_message")

    idx_path = project_root / "phases" / phase / "index.json"
    data = json.loads(idx_path.read_text(encoding="utf-8"))
    for s in data["steps"]:
        if s["step"] == step:
            s["status"] = status
            now = now_iso()
            if status == "in_progress":
                # Idempotent: only stamp started_at on the FIRST in_progress
                # transition so a resumed-after-crash run measures duration
                # from the original start, not the resume time.
                if "started_at" not in s:
                    s["started_at"] = now
            elif status == "completed":
                s["completed_at"] = now
                if duration_seconds is None and "started_at" in s:
                    try:
                        from datetime import datetime
                        started = datetime.fromisoformat(s["started_at"])
                        finished = datetime.fromisoformat(now)
                        duration_seconds = max(0.0, (finished - started).total_seconds())
                    except Exception:
                        duration_seconds = None
                if duration_seconds is not None:
                    s["duration_seconds"] = float(duration_seconds)
                s.pop("error_message", None)
                s.pop("blocked_reason", None)
                s.pop("failed_at", None)
            elif status == "error":
                s["failed_at"] = now
                s["error_message"] = error_message
            elif status == "blocked":
                s["blocked_at"] = now
                s["blocked_reason"] = blocked_reason
            elif status == "pending":
                # Resume retry — clear timestamps so duration recomputes cleanly.
                s.pop("completed_at", None)
                s.pop("failed_at", None)
                s.pop("blocked_at", None)
                s.pop("error_message", None)
                s.pop("blocked_reason", None)
                s.pop("started_at", None)
                s.pop("duration_seconds", None)
            elif status == "unimplemented":
                # Stub registration — no timestamps.
                s.pop("completed_at", None)
                s.pop("failed_at", None)
                s.pop("blocked_at", None)
                s.pop("error_message", None)
                s.pop("blocked_reason", None)
                s.pop("started_at", None)
                s.pop("duration_seconds", None)
            break
    else:
        raise ValueError(f"step {step} not found in {phase}")
    atomic_write_json(idx_path, data)


# ---------- Step output writer ----------

def write_step_output(
    project_root: Path,
    phase: str,
    step: int,
    exit_code: int,
    stdout: str,
    stderr: str,
    duration_seconds: float = 0.0,
) -> Path:
    """Atomic write phases/<phase>/step<N>-output.json."""
    path = project_root / "phases" / phase / f"step{step}-output.json"
    data = {
        "schema_version": SCHEMA_VERSION,
        "step": step,
        "phase": phase,
        "exit_code": exit_code,
        "stdout": stdout,
        "stderr": stderr,
        "duration_seconds": duration_seconds,
        "timestamp": now_iso(),
    }
    atomic_write_json(path, data)
    return path


# ---------- CLI ----------

def main() -> int:
    parser = argparse.ArgumentParser(description="dev-harness-kit harness-runner")
    parser.add_argument("phase", help="phase alias (e.g., 0-mvp)")
    parser.add_argument("--project-root", default=".", help="project root directory")
    parser.add_argument("--push", action="store_true", help="git push after each step")
    parser.add_argument("--parallel", type=int, default=0, metavar="N", help="run N steps in parallel worktrees")
    args = parser.parse_args()
    root = Path(args.project_root).resolve()
    if args.parallel > 0:
        return _run_parallel(root, args.phase, args.parallel, args.push)
    return _run_sequential(root, args.phase, args.push)


def _run_sequential(root: Path, phase: str, push: bool) -> int:
    """Per-step: read → preamble → invoke claude CLI → write output → commit (feat + chore)."""
    idx_path = root / "phases" / phase / "index.json"
    steps = parse_step_index(idx_path)
    for step_meta in steps:
        n = step_meta["step"]
        cur_status = step_meta["status"]
        # Skip already-done or not-yet-written steps.
        if cur_status in SKIPPABLE_STATUSES:
            continue
        # Blocked → bail with exit 2 (no implicit resume).
        if cur_status == "blocked":
            print(f"step {n} blocked: {step_meta.get('blocked_reason')}", file=sys.stderr)
            return 2
        # From any RESUMABLE state, mark in_progress then completed.
        if cur_status not in RESUMABLE_STATUSES:
            print(f"step {n}: unexpected status {cur_status!r}, skipping", file=sys.stderr)
            continue
        update_step_status(root, phase, n, status="in_progress")
        # Stub: real implementation would invoke `claude -p` with preamble.
        write_step_output(root, phase, n, exit_code=0, stdout=f"step {n} stub completed", stderr="", duration_seconds=0.01)
        update_step_status(root, phase, n, status="completed", duration_seconds=0.01)
    return 0


def _run_parallel(root: Path, phase: str, n: int, push: bool) -> int:
    """Stub parallel runner. Real impl spawns N subprocesses with worktree isolation."""
    print(f"--parallel {n}: stub (not yet implemented, plan Phase 3)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())