#!/usr/bin/env python3
"""
execute.py — harness-runner engine (per step executor).

Adapted from harness_framework/scripts/execute.py (sh-ai-x/harness_framework) — plan §5.
Adds:
- 2-commit protocol (feat + chore)
- atomic step<N>-output.json
- status state-machine: pending → completed | error → pending (resume) | blocked (user intervention)
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

from atomic import atomic_write_json, now_iso  # noqa: E402
MAX_RETRIES = 3
SCHEMA_VERSION = "1.0.0"
VALID_STATUSES = ("pending", "completed", "error", "blocked")


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


# ---------- Step status state machine ----------

def update_step_status(
    project_root: Path,
    phase: str,
    step: int,
    status: str,
    error_message: Optional[str] = None,
    blocked_reason: Optional[str] = None,
) -> None:
    """Update a single step's status with validation + atomic write."""
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
            if status == "completed":
                s["completed_at"] = now
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
                # Resume retry — clear timestamps
                s.pop("completed_at", None)
                s.pop("failed_at", None)
                s.pop("blocked_at", None)
                s.pop("error_message", None)
                s.pop("blocked_reason", None)
            break
    else:
        raise ValueError(f"step {step} not found in {phase}")
    atomic_write_json(idx_path, data)


# ---------- Step output writer ----------


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
        if step_meta["status"] == "completed":
            continue
        n = step_meta["step"]
        if step_meta["status"] not in ("pending", "error"):
            if step_meta["status"] == "blocked":
                print(f"step {n} blocked: {step_meta.get('blocked_reason')}", file=sys.stderr)
                return 2
        update_step_status(root, phase, n, status="completed")
        # Stub: real implementation would invoke `claude -p` with preamble.
        write_step_output(root, phase, n, exit_code=0, stdout=f"step {n} stub completed", stderr="", duration_seconds=0.01)
    return 0


def _run_parallel(root: Path, phase: str, n: int, push: bool) -> int:
    """Stub parallel runner. Real impl spawns N subprocesses with worktree isolation."""
    print(f"--parallel {n}: stub (not yet implemented, plan Phase 3)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
