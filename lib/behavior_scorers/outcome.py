"""outcome.py — D1 Outcome Correctness.

Pure deterministic scorer. Reads:
- `tests/` invocation result via `pytest -q` if available (graceful
  skip if pytest missing or worktree has no tests)
- `.dev-kit/eval-report.md` parse for the existing eval verdict

Score mapping (proposal §01 D1):
- 5: pytest 100% pass AND lint 0 violations AND eval OK
- 4: 95-99% pass OR 1-2 lint violations, eval OK
- 3: pytest fail OR eval DRIFT_WARNING
- 1-2: pytest > 5% fail OR eval ROT
- 0: eval ESCALATED

L4 (slop-detector) violations are not run from inside the scorer —
they are emitted by the existing pre-commit hook. The scorer reads
`.dev-kit/slop-detector.log` if present (convention). Missing log =
"no slop run yet", treated as 0 violations (best case).
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Dict

from lib.behavior_scorers.types import Context, DimensionScore

# Match the verdict line in eval-report.md.
_EVAL_VERDICT_RE = re.compile(r"^verdict:\s*\*?\*?(\w+)\*?\*?\s*$", re.MULTILINE)


def _read_eval_verdict(worktree: Path) -> str:
    """Parse `.dev-kit/eval-report.md` and return the verdict token.

    Returns "UNKNOWN" if the file is missing or unparseable — the
    scorer then treats that as a soft fail (no eval run yet) rather
    than crashing.
    """
    report = worktree / ".dev-kit" / "eval-report.md"
    if not report.is_file():
        return "UNKNOWN"
    try:
        text = report.read_text()
    except OSError:
        return "UNKNOWN"
    m = _EVAL_VERDICT_RE.search(text)
    return m.group(1).upper() if m else "UNKNOWN"


def _run_tests(worktree: Path) -> Dict[str, Any]:
    """Run `pytest -q` from the worktree. Return counts.

    Returns a dict with one of three states:
    - `no_tests`: pytest was not run because the worktree has neither
      a `tests/` dir nor a `pyproject.toml`. Treated as vacuously
      passing in `score()` (no tests to fail).
    - `unverified`: pytest failed to execute (timeout, FileNotFound,
      nonzero returncode, or no parseable summary). NOT treated as
      passing — this is the fix for the previous behavior that gave
      D1=5 on collection errors.
    - `executed`: pytest ran cleanly with a parseable summary.

    Captured output is bounded at 256 KB to prevent unbounded reads.
    """
    if not (worktree / "tests").exists() and not (worktree / "pyproject.toml").exists():
        return {"passed": 0, "failed": 0, "state": "no_tests", "reason": "no tests dir"}
    try:
        proc = subprocess.run(
            ["python3", "-m", "pytest", "-q", "--no-header"],
            cwd=str(worktree),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError as exc:
        return {"passed": 0, "failed": 0, "state": "unverified",
                "reason": f"pytest not installed: {exc}"}
    except subprocess.TimeoutExpired as exc:
        return {"passed": 0, "failed": 0, "state": "unverified",
                "reason": f"pytest timeout: {exc}"}
    # Bound the captured output to keep memory + parse predictable.
    raw = (proc.stdout or "") + (proc.stderr or "")
    if len(raw) > 256_000:
        raw = raw[-256_000:]
    # pytest summary line: "5 passed, 2 failed in 0.42s"
    passed = sum(int(x) for x in re.findall(r"(\d+)\s+passed", raw))
    failed = sum(int(x) for x in re.findall(r"(\d+)\s+failed", raw))
    # pytest exit codes:
    #   0 = all tests passed (or none expected)
    #   1 = tests failed
    #   2 = test execution interrupted
    #   3 = internal pytest error
    #   4 = pytest cmdline error
    #   5 = no tests collected (file collection found zero tests)
    # Treat exit=5 as "no tests" (vacuously compliant) only when no
    # failures were reported; otherwise treat as unverified.
    if proc.returncode == 5 and failed == 0:
        return {"passed": 0, "failed": 0, "state": "no_tests",
                "reason": "no tests collected"}
    if proc.returncode != 0:
        return {
            "passed": passed, "failed": failed, "state": "unverified",
            "reason": f"pytest exit={proc.returncode}",
            "returncode": proc.returncode,
        }
    if passed + failed == 0:
        # No parseable summary — could be collection error or no tests.
        # If the worktree HAS tests/ but pytest returned nothing, treat
        # as unverified; the previous behavior gave pass_rate=1.0 which
        # silently awarded D1=5 on broken test suites.
        if (worktree / "tests").exists():
            return {"passed": 0, "failed": 0, "state": "unverified",
                    "reason": "no parseable pytest summary"}
        return {"passed": 0, "failed": 0, "state": "no_tests",
                "reason": "no tests dir"}
    return {"passed": passed, "failed": failed, "state": "executed"}


def _read_slop_count(worktree: Path) -> int:
    """Read `.dev-kit/slop-detector.log` and count `VIOLATION:` lines.

    Missing log = 0 (the scorer should not punish "log file not yet
    produced" — the run may simply not have hit the slop-detector
    hook yet).
    """
    log = worktree / ".dev-kit" / "slop-detector.log"
    if not log.is_file():
        return 0
    try:
        return sum(1 for line in log.read_text().splitlines() if "VIOLATION" in line)
    except OSError:
        return 0


def score(worktree: Path, ctx: Context) -> DimensionScore:
    """Score D1 from pytest + slop-detector + eval-report.

    Three-state scoring: no_tests (vacuously passing), executed
    (uses pass rate), unverified (cannot determine — does NOT score 5).
    """
    tests = _run_tests(worktree)
    slop = _read_slop_count(worktree)
    eval_verdict = _read_eval_verdict(worktree)
    test_state = tests.get("state", "executed")

    # Test pass rate — only meaningful for executed state.
    if test_state == "executed":
        total = tests["passed"] + tests["failed"]
        pass_rate = tests["passed"] / total if total else 0.0
        tests_evidence = f"passed={tests['passed']}, failed={tests['failed']}"
    elif test_state == "no_tests":
        pass_rate = 1.0  # vacuously true
        tests_evidence = "no_tests"
    else:  # unverified
        pass_rate = 0.0  # explicitly NOT a pass
        tests_evidence = f"unverified: {tests.get('reason', 'unknown')}"

    # Score mapping.
    if eval_verdict == "ESCALATED":
        value = 0
    elif eval_verdict == "ROT":
        value = 1 if pass_rate < 0.95 else 2
    elif test_state == "unverified":
        # Unverified: do NOT give D1=5. Cap at 3 (DRIFT).
        value = 3 if pass_rate >= 0.5 else 2
    elif eval_verdict == "DRIFT_WARNING" or tests["failed"] > 0:
        value = 3
    elif pass_rate >= 1.0 and slop == 0 and eval_verdict in ("OK", "UNKNOWN"):
        value = 5
    elif pass_rate >= 0.95 and slop <= 2 and eval_verdict in ("OK", "UNKNOWN"):
        value = 4
    else:
        value = 3

    return DimensionScore(
        dim="D1_outcome",
        value=value,
        evidence={
            "tests": tests_evidence,
            "test_state": test_state,
            "pass_rate": round(pass_rate, 4),
            "slop_violations": slop,
            "eval_verdict": eval_verdict,
        },
    )
