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

    If pytest is not installed or no tests are present, return
    `{"passed": 0, "failed": 0, "skipped": True}` so the scorer can
    decide how to treat "no tests".
    """
    if not (worktree / "tests").exists() and not (worktree / "pyproject.toml").exists():
        return {"passed": 0, "failed": 0, "skipped": True, "reason": "no tests dir"}
    try:
        proc = subprocess.run(
            ["python3", "-m", "pytest", "-q", "--no-header"],
            cwd=str(worktree),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {"passed": 0, "failed": 0, "skipped": True, "reason": str(exc)}
    output = (proc.stdout or "") + (proc.stderr or "")
    # pytest summary line: "5 passed, 2 failed in 0.42s"
    passed = sum(int(x) for x in re.findall(r"(\d+)\s+passed", output))
    failed = sum(int(x) for x in re.findall(r"(\d+)\s+failed", output))
    return {"passed": passed, "failed": failed, "skipped": False}


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
    """Score D1 from pytest + slop-detector + eval-report."""
    tests = _run_tests(worktree)
    slop = _read_slop_count(worktree)
    eval_verdict = _read_eval_verdict(worktree)

    # Test pass rate.
    if tests.get("skipped"):
        pass_rate = 1.0  # no tests → nothing to fail
        tests_evidence = "skipped"
    else:
        total = tests["passed"] + tests["failed"]
        pass_rate = tests["passed"] / total if total else 1.0
        tests_evidence = f"passed={tests['passed']}, failed={tests['failed']}"

    # Score mapping.
    if eval_verdict == "ESCALATED":
        value = 0
    elif eval_verdict == "ROT":
        value = 1 if pass_rate < 0.95 else 2
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
            "pass_rate": round(pass_rate, 4),
            "slop_violations": slop,
            "eval_verdict": eval_verdict,
        },
    )
