"""test_loop_detect.py — doom-loop detector regression.

Pins the truth table for `hooks/lib/loop-detect.sh::loop_detected`.
Each test runs the helper in a fresh bash subprocess so the side-effect
(appending to the per-session log) does not leak between cases.

Cases:
    1. Three identical calls → 1 (loop detected).
    2. Two identical calls  → 0 (no loop yet).
    3. Three different calls → 0 (no loop; same tool, different input).
    4. Threshold env var override (default 3, override 5).
    5. Missing log file → 0 (no false positive on first call).
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import pytest

REPO_ROOT = Path(__file__).parent.parent
LIB = REPO_ROOT / "hooks" / "lib" / "loop-detect.sh"


def _bash() -> str:
    p = shutil.which("bash")
    if not p:
        pytest.skip("bash not on PATH")
    return p


def _loop_detected_rc(
    log_dir: Path,
    session_id: str,
    calls: list[tuple[str, str]],
    env_overrides: Optional[dict[str, str]] = None,
) -> list[int]:
    """Source loop-detect.sh, run a sequence of loop_detected calls,
    return the rc of each call as a list (length == len(calls))."""
    env: dict[str, str] = {
        **os.environ,
        "LOOP_DETECT_LOG_DIR": str(log_dir),
        "LOOP_DETECT_SESSION_ID": session_id,
    }
    if env_overrides:
        env.update(env_overrides)

    # Build a bash script: source the lib, then invoke loop_detected for
    # each (tool, input) pair capturing its rc into rc_N. Each rc is
    # echoed on its own line for simple parsing.
    # Using shlex.quote() keeps arbitrary inputs (quotes, backslashes)
    # safe inside bash single-quotes.
    lines = [f'source "{LIB}"']
    for idx, (tool, input_) in enumerate(calls):
        lines.append(f"loop_detected {shlex.quote(tool)} {shlex.quote(input_)}")
        lines.append(f"rc_{idx}=$?")
        lines.append(f"echo rc_{idx}=$rc_{idx}")
    snippet = "\n".join(lines)

    r = subprocess.run(
        [_bash(), "-c", snippet],
        capture_output=True, text=True, timeout=10, env=env,
    )
    assert r.returncode == 0, (
        f"subprocess crashed: rc={r.returncode} stderr={r.stderr!r}"
        f" stdout={r.stdout!r}"
    )
    rcs: list[int] = []
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line.startswith("rc_"):
            continue
        # line format: rc_<N>=<int>
        _, _, payload = line.partition("=")
        rcs.append(int(payload))
    assert len(rcs) == len(calls), (
        f"expected {len(calls)} rc lines, got {len(rcs)} from {r.stdout!r}"
    )
    return rcs


def test_three_identical_calls_returns_1(tmp_path: Path) -> None:
    """3 consecutive identical Bash calls → 3rd call returns 1."""
    rcs = _loop_detected_rc(
        log_dir=tmp_path,
        session_id="session-A",
        calls=[
            ("Bash", "echo hello"),
            ("Bash", "echo hello"),
            ("Bash", "echo hello"),
        ],
    )
    # The 1st call makes the file; on call 2 we have prior_matches=1
    # (1+1=2 < threshold 3 → 0); on call 3 prior_matches=2 (2+1=3 >= 3 → 1).
    assert rcs == [0, 0, 1], (
        f"3 identical calls: expect [0, 0, 1] (loop fires on the 3rd)."
        f" Got {rcs}."
    )


def test_two_identical_calls_returns_0(tmp_path: Path) -> None:
    """2 consecutive identical Bash calls → 0 (under threshold)."""
    rcs = _loop_detected_rc(
        log_dir=tmp_path,
        session_id="session-B",
        calls=[
            ("Bash", "ls -la"),
            ("Bash", "ls -la"),
        ],
    )
    assert rcs == [0, 0], (
        f"2 identical calls (under default threshold=3) must NOT flag."
        f" Got {rcs}."
    )


def test_three_different_inputs_returns_0(tmp_path: Path) -> None:
    """Same tool, 3 different inputs (e.g. legitimate retries that
    vary a flag) → must NOT flag a loop."""
    rcs = _loop_detected_rc(
        log_dir=tmp_path,
        session_id="session-C",
        calls=[
            ("Bash", "pytest tests/a.py"),
            ("Bash", "pytest tests/a.py -x"),
            ("Bash", "pytest tests/a.py -x --tb=short"),
        ],
    )
    assert rcs == [0, 0, 0], (
        f"3 calls with monotonically varied inputs (likely retries with"
        f" growing flags) must NOT flag. Got {rcs}."
    )


def test_threshold_override_via_env(tmp_path: Path) -> None:
    """LOOP_DETECT_THRESHOLD=5 → 4 identical calls stay 0; 5th flips 1."""
    rcs_four = _loop_detected_rc(
        log_dir=tmp_path,
        session_id="session-D",
        calls=[("Bash", "tail /var/log/foo")] * 4,
        env_overrides={"LOOP_DETECT_THRESHOLD": "5"},
    )
    assert rcs_four == [0, 0, 0, 0], (
        f"With threshold=5, 4 identical calls must remain [0,0,0,0]."
        f" Got {rcs_four}."
    )

    # Fresh session to avoid the prior log leakage (each session_id
    # owns its own log file inside log_dir).
    rcs_five = _loop_detected_rc(
        log_dir=tmp_path,
        session_id="session-D2",
        calls=[("Bash", "tail /var/log/bar")] * 5,
        env_overrides={"LOOP_DETECT_THRESHOLD": "5"},
    )
    # With threshold=5, prior_matches+1 >= 5 only when prior_matches = 4
    # i.e. on the 5th call.
    assert rcs_five == [0, 0, 0, 0, 1], (
        f"With threshold=5, 5 identical calls should fire on the 5th."
        f" Got {rcs_five}."
    )


def test_missing_log_file_returns_0(tmp_path: Path) -> None:
    """First call ever (no log file on disk) → must NOT flag a loop."""
    log_file = tmp_path / "session-E.log"
    assert not log_file.exists(), (
        "test fixture requires a fresh tmp_path with no prior log"
    )
    rcs = _loop_detected_rc(
        log_dir=tmp_path,
        session_id="session-E",
        calls=[("Bash", "ls /tmp")],
    )
    assert rcs == [0], f"missing log must not flag. Got {rcs}"
    # The helper also appends the new entry for future calls — sanity
    # check that it wrote to disk (next-call comparison needs it).
    assert log_file.exists(), (
        "helper must create the log file on the first call so the next"
        " call can compare"
    )
    first_line = log_file.read_text().splitlines()[0]
    assert first_line.startswith("Bash\t"), (
        f"first log line must be 'Bash\\t<input_prefix>'. Got: {first_line!r}"
    )


def test_long_inputs_differing_after_prefix_collision(tmp_path: Path) -> None:
    """Documents the spec trade-off flagged in the codex review.

    The proposal fixes the fingerprint at the first
    ${LOOP_DETECT_PREFIX_LEN:-80} chars. Two Bash calls that share the
    first 80 chars but diverge after are treated as identical, so a
    legitimate "retry with appended flag" (the common
    `pytest -x` -> `pytest -x --tb=short` shape) collides on the
    doom-loop check once the prefix saturates.

    This test pins that behavior so any spec change is intentional.
    To make the detector more permissive, bump LOOP_DETECT_PREFIX_LEN
    or hash the full input.
    """
    common = "x" * 80  # saturates the 80-char prefix
    # Three calls that all match in the first 80 chars but diverge at
    # the tail. Under the spec, fingerprint equality holds and the
    # 3rd call trips the doom-loop. Use this assertion to spot any
    # future "ignore input past the prefix window" change.
    rcs = _loop_detected_rc(
        log_dir=tmp_path,
        session_id="long-sid",
        calls=[
            ("Bash", common + "_first"),
            ("Bash", common + "_second"),
            ("Bash", common + "_third"),
        ],
    )
    assert rcs == [0, 0, 1], (
        f"Spec: first 80 chars drive the fingerprint. Long inputs that"
        f" share the prefix are flagged on the 3rd repeat. Got {rcs};"
        f" if you wanted differentiation past the prefix window, raise"
        f" LOOP_DETECT_PREFIX_LEN."
    )


def test_helper_returns_one_only_for_loop(tmp_path: Path) -> None:
    """Wrapper contract guard: the wire-up in hooks/loop-detect.sh
    treats only rc=1 as a positive. Asserts the helper's rc vocabulary
    stays in {0, 1} across the threshold spectrum so a future helper
    refactor cannot accidentally push a non-{0,1} rc back to the
    wrapper (which now suppresses it via an explicit inequality check;
    see codex review)."""
    rcs = _loop_detected_rc(
        log_dir=tmp_path,
        session_id="contract-sid",
        calls=[("Bash", "rm -rf /tmp/foo")] * 3,
    )
    assert rcs == [0, 0, 1]
    # Pin the rc vocabulary to {0, 1}.
    for n in rcs:
        assert n in (0, 1), f"helper rc must be 0 or 1, got {n}"

