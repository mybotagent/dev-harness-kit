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
- --parallel mode (worktree, N-step concurrent)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from atomic import atomic_write_json, now_iso  # noqa: E402
SCHEMA_VERSION = "1.0.0"
# Sub-agent stdout marker. If the per-step `claude -p` emits this line, the
# runner transitions the step to `blocked` (with reason) instead of `completed`
# so the human gets unblocked instead of a silent zero-file PR (issue #221).
BLOCKED_MARKER = "<!-- status: blocked -->"
# Tools the per-step sub-agent needs to do anything useful. Required so a
# restrictive parent Claude Code sandbox (issue #221 RC1: consumer project
# does not pre-allow .workspace/**) does not silently block all writes.
SUBAGENT_ALLOWED_TOOLS = "Write,Edit,Bash"
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
        pending → unimplemented: clears all timestamps
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
                _clear_step_timestamps(s)
            elif status == "unimplemented":
                # Stub registration — no timestamps.
                _clear_step_timestamps(s)
            break
    else:
        raise ValueError(f"step {step} not found in {phase}")
    atomic_write_json(idx_path, data)


# ---------- Step output writer ----------

def _clear_step_timestamps(step: dict) -> None:
    """Pop all per-step timestamp + error/blocked fields.

    Shared between the `pending` (resume retry) and `unimplemented`
    (stub registration) branches of `update_step_status` so adding a new
    timestamp field lands in one place instead of two.
    """
    for key in (
        "completed_at", "failed_at", "blocked_at",
        "error_message", "blocked_reason",
        "started_at", "duration_seconds",
    ):
        step.pop(key, None)


def write_step_output(
    project_root: Path,
    phase: str,
    step: int,
    exit_code: int,
    stdout: str,
    stderr: str,
    duration_seconds: float = 0.0,
    blocked: bool = False,
    blocked_reason: Optional[str] = None,
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
    if blocked:
        # Issue #221 RC3: surface the sub-agent's blocked verdict in the
        # output JSON so audits can see WHY a step was held back instead of
        # silently advancing to `completed` on exit_code==0.
        data["blocked"] = True
        data["blocked_reason"] = blocked_reason or ""
    atomic_write_json(path, data)
    return path


def _extract_blocked_reason(stdout: str) -> Optional[str]:
    """If BLOCKED_MARKER is in stdout, return the human-readable reason.

    The convention is: the line(s) immediately BEFORE the marker are the
    human-readable request (e.g. "i need an API key — cannot proceed"). After
    the marker is meaningless chatter. We strip the marker itself and any
    trailing content so the reason recorded in index.json is concise.
    """
    if BLOCKED_MARKER not in stdout:
        return None
    head, _, _ = stdout.partition(BLOCKED_MARKER)
    reason = head.strip().rstrip(",").strip()
    return reason or "sub-agent emitted <!-- status: blocked --> with no preceding reason"


def _commit_step(wt: Path, msg: str) -> bool:
    """Stage ALL writes in the per-step worktree, then commit only if dirty.

    Issue #221 RC2: the previous `git commit --allow-empty` masked a chain of
    failure modes — sub-agent writes blocked by sandbox, empty WorkTree, etc.
    The new contract is: stage first (`git add -A`), then ask git whether there
    is anything to commit (`git diff --cached --quiet`). If no diff, skip the
    commit entirely and return False. Caller branches on the bool to set the
    correct status (committed → continue; no-diff → block-on-marker-only is
    enough; or surface as a step-level "no files written" anomaly).
    """
    subprocess.run(
        ["git", "add", "-A"],
        cwd=str(wt), check=True, capture_output=True, text=True,
    )
    diff_check = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=str(wt), capture_output=True, text=True,
    )
    if diff_check.returncode == 0:
        # Nothing staged → nothing to commit. Do NOT make an empty commit.
        return False
    subprocess.run(
        ["git", "commit", "-m", msg],
        cwd=str(wt), check=True, capture_output=True, text=True,
    )
    return True


# ---------- CLI ----------

_PARALLEL_BUILD_WARN = (
    "ERROR: --parallel N > 1 is rarely correct for /dev-kit:build.\n"
    "\n"
    "Two concurrent `claude -p` steps WILL collide on shared files\n"
    "(config, imports, types, schema). The collision is invisible during\n"
    "the run — both commits land cleanly in their own per-step worktrees.\n"
    "The damage surfaces only when both branches are merged into main.\n"
    "\n"
    "Use parallel build only when each step's declared writes are disjoint\n"
    "AND no step consumes another step's output. To override this gate,\n"
    "re-run with --allow-parallel-build.\n"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="dev-harness-kit harness-runner")
    parser.add_argument("phase", help="phase alias (e.g., 0-mvp)")
    parser.add_argument("--project-root", default=".", help="project root directory")
    parser.add_argument("--push", action="store_true", help="git push after each step")
    parser.add_argument("--parallel", type=int, default=0, metavar="N", help="run N steps in parallel worktrees")
    parser.add_argument("--allow-parallel-build", action="store_true",
                        help="Required when --parallel > 1; confirms understanding that "
                             "parallel builds collide on shared files and the conflict "
                             "surfaces at merge time. Without this flag, --parallel > 1 is refused.")
    parser.add_argument("--skip-blocked", action="store_true",
                        help="continue past steps with status='blocked' instead of bailing; "
                             "skipped steps are listed in .dev-kit/hand-off/build→review.md")
    args = parser.parse_args()
    # Gate: --parallel > 1 must require explicit acknowledgment (issue #175).
    # Two concurrent writers WILL collide on shared files; conflict surfaces
    # only at merge time, so a silent acceptance is an active damage vector.
    if args.parallel > 1 and not args.allow_parallel_build:
        print(_PARALLEL_BUILD_WARN, file=sys.stderr)
        return 2
    root = Path(args.project_root).resolve()
    if args.parallel > 0:
        return _run_parallel(root, args.phase, args.parallel, args.push, args.skip_blocked)
    return _run_sequential(root, args.phase, args.push, args.skip_blocked)


def _run_sequential(root: Path, phase: str, push: bool, skip_blocked: bool = False) -> int:
    """Per-step: read → preamble → invoke claude CLI → write output → commit (feat + chore).

    Honors MUST-36 (one sub-agent per step), MUST-37 (3-cycle self-fix, declared in preamble),
    MUST-38 (per-step worktree). The step branch derives from `index.json["worktree"]`; if
    absent, falls back to `feat/<phase>`.

    Returns 0 on success, 2 on `blocked` (unless `skip_blocked=True`), or the subprocess
    returncode on failure.
    """
    idx_path = root / "phases" / phase / "index.json"
    data = json.loads(idx_path.read_text(encoding="utf-8"))
    worktree_branch = data.get("worktree") or f"feat/{phase}"
    steps = data.get("steps", [])
    for step_meta in steps:
        n = step_meta["step"]
        cur_status = step_meta.get("status")
        # Skip already-done or not-yet-written steps.
        if cur_status in SKIPPABLE_STATUSES:
            continue
        # Blocked → either skip (--skip-blocked) or bail with exit 2 (no implicit resume).
        if cur_status == "blocked":
            reason = step_meta.get("blocked_reason") or "(no reason recorded)"
            print(f"step {n} blocked: {reason}", file=sys.stderr)
            if skip_blocked:
                _record_skipped_blocked(root, phase, n, reason)
                continue
            return 2
        # From any RESUMABLE state, mark in_progress then run.
        if cur_status not in RESUMABLE_STATUSES:
            print(f"step {n}: unexpected status {cur_status!r}, skipping", file=sys.stderr)
            continue
        rc = _run_one_step(root, phase, n, worktree_branch, step_meta.get("name", ""), push)
        if rc != 0:
            return rc
    return 0


def _run_one_step(
    root: Path,
    phase: str,
    step_num: int,
    worktree_branch: str,
    step_name: str,
    push: bool,
) -> int:
    """Execute ONE step end-to-end. Returns 0 on success, non-zero on failure.

    Order:
      1. Create per-step worktree from origin/main (MUST-38).
      2. Read step<N>.md as preamble; append AC + self-fix guard.
      3. Mark step `in_progress` (sets started_at).
      4. Spawn ONE `claude -p` sub-agent in worktree (MUST-36).
      5. Capture stdout/stderr/returncode → write step<N>-output.json (real result).
      6. On non-zero exit → mark `error`, return.
      7. 2-commit protocol: feat(scope) + chore(scope) on the per-step branch.
      8. Push per-step branch when `push=True`.
      9. Mark `completed` with measured duration.
    """
    wt = root / ".workspace" / f"{phase}-step{step_num}"
    branch = f"{worktree_branch}-step{step_num}"

    # 1. per-step worktree (MUST-38)
    subprocess.run(
        ["git", "worktree", "add", "-B", branch, str(wt), "origin/main"],
        cwd=str(root), check=True, capture_output=True, text=True,
    )

    # 2. preamble = step.md body + AC guard + 3-cycle self-fix (MUST-37)
    preamble_path = root / "phases" / phase / f"step{step_num}.md"
    preamble = preamble_path.read_text(encoding="utf-8") if preamble_path.exists() else ""
    full_prompt = preamble + "\n\n---\nAC: see step file. 3-cycle self-fix max."

    # 3. in_progress
    update_step_status(root, phase, step_num, status="in_progress")
    started_at_iso = now_iso()

    # 4. spawn one sub-agent (MUST-36)
    #    Issue #221 RC1: --add-dir <wt> + --allowedTools so the sub-agent can
    #    write into the per-step worktree even when the consumer's parent
    #    Claude Code sandbox blocks ".workspace/**" by default.
    proc = subprocess.run(
        ["claude", "-p",
         "--add-dir", str(wt),
         "--allowedTools", SUBAGENT_ALLOWED_TOOLS,
         "--workdir", str(wt),
         full_prompt],
        cwd=str(root), capture_output=True, text=True,
    )

    # 5. write step<N>-output.json with REAL contents
    try:
        started = datetime.fromisoformat(started_at_iso)
        duration = max(0.0, (datetime.fromisoformat(now_iso()) - started).total_seconds())
    except Exception:
        duration = 0.0

    # Issue #221 RC3: parse `<!-- status: blocked -->` BEFORE marking completed.
    # stdout==0 + marker present → register as blocked (with reason) and bail rc=2.
    blocked_reason = _extract_blocked_reason(proc.stdout or "")
    write_step_output(
        root, phase, step_num,
        exit_code=proc.returncode,
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        duration_seconds=duration,
        blocked=bool(blocked_reason),
        blocked_reason=blocked_reason,
    )

    # 5b. blocked marker wins — even on a clean exit_code==0, refuse to advance.
    if blocked_reason is not None:
        update_step_status(
            root, phase, step_num,
            status="blocked",
            blocked_reason=blocked_reason,
        )
        return 2  # sentinel mirrored by _run_sequential("blocked" pre-existing) → bails the loop

    # 6. on failure → error status, return
    if proc.returncode != 0:
        update_step_status(
            root, phase, step_num,
            status="error",
            error_message=f"claude exited {proc.returncode}",
        )
        return proc.returncode

    # 7. 2-commit protocol (feat + chore) on the per-step branch.
    #    Issue #221 RC2: replace `git commit --allow-empty` with add-A +
    #    conditional commit via _commit_step. If the sub-agent wrote nothing
    #    (still a valid "the step has nothing to commit" outcome), the per-step
    #    branch simply gets one fewer commit — NOT an empty commit with a fake
    #    "feat:" stamp.
    feat_msg = f"feat({phase}): step {step_num}" + (f" — {step_name}" if step_name else "")
    _commit_step(wt, feat_msg)
    chore_msg = f"chore({phase}): step {step_num} output"
    _commit_step(wt, chore_msg)

    # 8. push
    if push:
        subprocess.run(
            ["git", "push", "-u", "origin", branch],
            cwd=str(wt), check=False, capture_output=True, text=True,
        )

    # 9. mark completed (status transition also stamps duration_seconds from started_at)
    update_step_status(root, phase, step_num, status="completed")
    return 0



def _record_skipped_blocked(root: Path, phase: str, step: int, reason: str) -> None:
    """Append a paragraph to .dev-kit/hand-off/build→review.md naming the skipped blocked step.

    Uses the same atomic-write helper as the rest of the engine so concurrent slot
    appends do not race. The hand-off file is created with a header on first write.
    """
    from atomic import atomic_write_text  # local import to avoid module-load churn
    handoff = root / ".dev-kit" / "hand-off" / "build→review.md"
    handoff.parent.mkdir(parents=True, exist_ok=True)
    header = ""
    if not handoff.exists():
        header = (
            "# build → review hand-off\n\n"
            "> Auto-generated by `lib/execute.py` when `--skip-blocked` is set.\n\n"
        )
    line = f"- step {step} skipped (status=blocked): {reason}\n"
    existing = handoff.read_text(encoding="utf-8") if handoff.exists() else header
    atomic_write_text(handoff, existing + line)


def _run_parallel(root: Path, phase: str, n: int, push: bool, skip_blocked: bool = False) -> int:
    """Run N steps concurrently with per-step worktree isolation.

    Wall-clock bounded by slowest slot, not sum. Each slot gets its own worktree.
    Returns 0 on success, non-zero if any slot failed. Combined pre-flight uses
    the same SKIPPABLE_STATUSES / blocked rules as sequential. When
    `skip_blocked=True`, blocked steps are skipped (with hand-off note) instead
    of bailing the whole run.
    """
    idx_path = root / "phases" / phase / "index.json"
    data = json.loads(idx_path.read_text(encoding="utf-8"))
    worktree_branch = data.get("worktree") or f"feat/{phase}"
    steps = data.get("steps", [])
    # Collect only steps that are RESUMABLE. Blocked bails the whole run.
    eligible = []
    for step_meta in steps:
        cur_status = step_meta.get("status")
        if cur_status in SKIPPABLE_STATUSES:
            continue
        if cur_status == "blocked":
            reason = step_meta.get("blocked_reason") or "(no reason recorded)"
            print(f"step {step_meta['step']} blocked: {reason}", file=sys.stderr)
            if skip_blocked:
                _record_skipped_blocked(root, phase, step_meta["step"], reason)
                continue
            return 2
        if cur_status not in RESUMABLE_STATUSES:
            print(f"step {step_meta['step']}: unexpected status {cur_status!r}, skipping",
                  file=sys.stderr)
            continue
        eligible.append(step_meta)
        if len(eligible) >= n:
            break

    slots = [_SlotRunner(root, phase, worktree_branch, push) for _ in range(min(n, len(eligible)))]
    if not slots:
        return 0

    # First pass: launch. Each slot pulls the next eligible step when free.
    for slot in slots:
        slot.next_step = eligible.pop(0) if eligible else None
    while any(s.next_step is not None or s.proc is not None for s in slots):
        for slot in slots:
            if slot.proc is None and slot.next_step is not None:
                slot.launch()
                if eligible:
                    slot.next_step = eligible.pop(0)
                else:
                    slot.next_step = None
            if slot.proc is not None and slot.proc.poll() is not None:
                slot.collect()
    return 0 if all(slot.exit_code == 0 for slot in slots) else 1


class _SlotRunner:
    """One concurrent slot in _run_parallel. Owns worktree, proc, and step status."""

    def __init__(self, root: Path, phase: str, worktree_branch: str, push: bool) -> None:
        self.root = root
        self.phase = phase
        self.worktree_branch = worktree_branch
        self.push = push
        self.next_step: Optional[Dict] = None
        self.current_step: Optional[Dict] = None
        self.proc: Optional[subprocess.Popen] = None
        self.exit_code: int = 0
        self.started_at_iso: Optional[str] = None
        self.wt: Optional[Path] = None
        self.branch: Optional[str] = None

    def launch(self) -> None:
        step = self.next_step
        if step is None:
            return
        n = step["step"]
        self.current_step = step
        self.wt = self.root / ".workspace" / f"{self.phase}-step{n}"
        self.branch = f"{self.worktree_branch}-step{n}"
        subprocess.run(
            ["git", "worktree", "add", "-B", self.branch, str(self.wt), "origin/main"],
            cwd=str(self.root), check=True, capture_output=True, text=True,
        )
        preamble_path = self.root / "phases" / self.phase / f"step{n}.md"
        preamble = preamble_path.read_text(encoding="utf-8") if preamble_path.exists() else ""
        full_prompt = preamble + "\n\n---\nAC: see step file. 3-cycle self-fix max."
        update_step_status(self.root, self.phase, n, status="in_progress")
        self.started_at_iso = now_iso()
        # Issue #221 RC1: same --add-dir + --allowedTools fix as sequential.
        self.proc = subprocess.Popen(
            ["claude", "-p",
             "--add-dir", str(self.wt),
             "--allowedTools", SUBAGENT_ALLOWED_TOOLS,
             "--workdir", str(self.wt),
             full_prompt],
            cwd=str(self.root), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

    def collect(self) -> None:
        assert self.proc is not None
        stdout, stderr = self.proc.communicate()
        self.exit_code = self.proc.returncode or 0
        step = self.current_step
        assert step is not None
        n = step["step"]
        try:
            started = datetime.fromisoformat(self.started_at_iso) if self.started_at_iso else None
            duration = max(
                0.0,
                (datetime.fromisoformat(now_iso()) - started).total_seconds(),
            ) if started else 0.0
        except Exception:
            duration = 0.0
        # Issue #221 RC3: parse the blocked marker first so a clean exit_code
        # cannot silently advance a step the sub-agent explicitly held back.
        blocked_reason = _extract_blocked_reason(stdout or "")
        write_step_output(
            self.root, self.phase, n,
            exit_code=self.exit_code,
            stdout=stdout or "",
            stderr=stderr or "",
            duration_seconds=duration,
            blocked=bool(blocked_reason),
            blocked_reason=blocked_reason,
        )
        if blocked_reason is not None:
            update_step_status(
                self.root, self.phase, n,
                status="blocked",
                blocked_reason=blocked_reason,
            )
            self.exit_code = 2  # bail the whole parallel run on a blocked step
        elif self.exit_code != 0:
            update_step_status(
                self.root, self.phase, n,
                status="error",
                error_message=f"claude exited {self.exit_code}",
            )
        else:
            # Issue #221 RC2: --allow-empty is GONE. add-A + conditional commit.
            feat_msg = f"feat({self.phase}): step {n}" + (
                f" — {step.get('name', '')}" if step.get("name") else ""
            )
            _commit_step(self.wt, feat_msg)
            _commit_step(
                self.wt, f"chore({self.phase}): step {n} output"
            )
            if self.push and self.branch:
                subprocess.run(
                    ["git", "push", "-u", "origin", self.branch],
                    cwd=str(self.wt), check=False, capture_output=True, text=True,
                )
            update_step_status(self.root, self.phase, n, status="completed")
        self.proc = None
        self.current_step = None


if __name__ == "__main__":
    sys.exit(main())
