"""test_robustness_scorer.py — Phase 1 D6 Robustness scenario runner.

Covers:
- ctx.no_scenarios short-circuits to a Phase 1 placeholder
- no scenarios dir returns value=3
- happy path: 5 fixtures, mean is computed + clamped
- signal routing: graceful_recovery=5, escalation_marker=3,
  silent_failure=1, no signal=3
- malformed YAML (missing required keys) → value=3 per scenario
- runner seam: ctx.scenario_runner swaps out subprocess
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Tuple

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from lib.behavior_scorers.robustness import (  # noqa: E402
    REQUIRED_KEYS,
    _parse_yaml,
    _score_signals,
    _validate_scenario,
    score,
)
from lib.behavior_scorers.types import Context  # noqa: E402

FIXTURES = Path(__file__).parent.parent / "eval" / "scenarios"


# ----- fixtures presence -----

def test_all_five_fixtures_present() -> None:
    """All 5 required scenario YAMLs must exist."""
    names = {"compile-error.yaml", "flaky-test.yaml", "missing-dep.yaml",
              "conflicting-instructions.yaml", "resource-exhaustion.yaml"}
    found = {p.name for p in FIXTURES.glob("*.yaml")}
    assert names <= found, f"missing: {names - found}"


# ----- no_scenarios flag -----

def test_no_scenarios_returns_placeholder(tmp_path: Path) -> None:
    """ctx.no_scenarios=True → value=3 with skipped=True."""
    wt = tmp_path / "wt"
    (wt / "eval" / "scenarios").mkdir(parents=True)
    (wt / "eval" / "scenarios" / "compile-error.yaml").write_text("scenario_id: x\n")
    ds = score(wt, Context(no_scenarios=True))
    assert ds.dim == "D6_robustness"
    assert ds.value == 3
    assert ds.evidence["phase"] == 1
    assert ds.evidence["skipped"] is True


# ----- no scenarios dir -----

def test_no_scenarios_dir_returns_three(tmp_path: Path) -> None:
    """Missing eval/scenarios/ → value=3, reason=no scenario fixtures."""
    wt = tmp_path / "wt"
    wt.mkdir()
    ds = score(wt, Context())
    assert ds.value == 3
    assert ds.evidence["reason"] == "no scenario fixtures"


# ----- signal routing -----

def _scenario(graceful: str = "", escalation: str = "", silent: str = "") -> dict:
    return {
        "scenario_id": "test",
        "description": "test",
        "setup": "",
        "agent_invocation": "echo",
        "scoring": {
            "graceful_recovery": graceful,
            "escalation_marker": escalation,
            "silent_failure": silent,
        },
    }


@pytest.mark.parametrize("output,expected", [
    ("the agent recovered gracefully today", 5),   # graceful wins
    ("an escalation marker fired here", 3),         # escalation only
    ("silent failure happened", 1),            # catastrophic
    ("no observable signals here", 3),         # unknown → 3
])
def test_signal_routing(output: str, expected: int) -> None:
    """_score_signals picks the right value for each signal combination."""
    scen = _scenario(
        graceful="recovered gracefully",
        escalation="escalation marker",
        silent="silent failure",
    )
    val, evidence = _score_signals(output, scen)
    assert val == expected
    # Always populate the three booleans in evidence.
    assert set(evidence) == {
        "graceful_recovery_observed",
        "escalation_marker_observed",
        "silent_failure_observed",
    }


def test_silent_failure_beats_graceful() -> None:
    """If both graceful and silent appear, silent wins (catastrophic)."""
    scen = _scenario(graceful="recovered", silent="silent failure")
    val, _ = _score_signals("recovered silently, silent failure logged", scen)
    assert val == 1


# ----- YAML parsing -----

def test_parse_yaml_round_trip(tmp_path: Path) -> None:
    """_parse_yaml extracts top-level scalars + nested scoring mapping."""
    p = tmp_path / "s.yaml"
    p.write_text(
        "scenario_id: foo\n"
        "description: hello\n"
        "setup: 'echo 1'\n"
        "agent_invocation: 'echo 2'\n"
        "scoring:\n"
        "  graceful_recovery: GR\n"
        "  escalation_marker: EM\n"
        "  silent_failure: SF\n",
        encoding="utf-8",
    )
    data = _parse_yaml(p)
    assert data["scenario_id"] == "foo"
    assert data["scoring"]["graceful_recovery"] == "GR"


def test_parse_yaml_handles_folded_scalar(tmp_path: Path) -> None:
    """`>-` (folded, strip) joins continuation lines with single spaces."""
    p = tmp_path / "s.yaml"
    p.write_text(
        "key: >-\n"
        "  line1\n"
        "  line2\n",
        encoding="utf-8",
    )
    data = _parse_yaml(p)
    assert data["key"] == "line1 line2"


def test_parse_yaml_handles_literal_scalar(tmp_path: Path) -> None:
    """`|` (literal) preserves newlines between continuation lines."""
    p = tmp_path / "s.yaml"
    p.write_text(
        "key: |\n"
        "  line1\n"
        "  line2\n",
        encoding="utf-8",
    )
    data = _parse_yaml(p)
    assert data["key"] == "line1\nline2"


def test_parse_yaml_handles_folded_scalar_with_paragraph_break(tmp_path: Path) -> None:
    """Blank lines inside a folded scalar become paragraph separators."""
    p = tmp_path / "s.yaml"
    p.write_text(
        "key: >-\n"
        "  para1 line1\n"
        "  para1 line2\n"
        "\n"
        "  para2 line1\n"
        "  para2 line2\n",
        encoding="utf-8",
    )
    data = _parse_yaml(p)
    assert data["key"] == "para1 line1 para1 line2\n\npara2 line1 para2 line2"


def test_parse_yaml_handles_literal_scalar_with_strip(tmp_path: Path) -> None:
    """`|-` (literal, strip) preserves internal newlines but trims trailing."""
    p = tmp_path / "s.yaml"
    p.write_text(
        "key: |-\n"
        "  line1\n"
        "  line2\n",
        encoding="utf-8",
    )
    data = _parse_yaml(p)
    assert data["key"] == "line1\nline2"
    assert not data["key"].endswith("\n")


def test_parse_yaml_multiline_marker_does_not_leak_into_next_key(tmp_path: Path) -> None:
    """A multiline block ends at the next top-level key (same indent)."""
    p = tmp_path / "s.yaml"
    p.write_text(
        "first: >-\n"
        "  alpha\n"
        "  beta\n"
        "second: gamma\n",
        encoding="utf-8",
    )
    data = _parse_yaml(p)
    assert data["first"] == "alpha beta"
    assert data["second"] == "gamma"


def test_parse_yaml_handles_multiline_scenario_fixture() -> None:
    """All 5 D6 fixtures: description/setup/agent_invocation must be real content."""
    expected = {
        "compile-error.yaml",
        "flaky-test.yaml",
        "missing-dep.yaml",
        "conflicting-instructions.yaml",
        "resource-exhaustion.yaml",
    }
    for name in expected:
        path = FIXTURES / name
        if not path.exists():
            pytest.skip(f"fixture not found: {path}")
        data = _parse_yaml(path)
        for key in ("description", "setup", "agent_invocation"):
            assert key in data, f"{name}: missing {key}"
            val = data[key]
            assert isinstance(val, str), f"{name}.{key} not str: {type(val).__name__}"
            # The bug returned the literal string ">-" for these fields.
            assert val != ">-", f"{name}.{key} still parsed as folded marker '>-'"
            assert val.strip(), f"{name}.{key} is empty after fix"


def test_validate_scenario_missing_keys() -> None:
    """Missing keys → (False, [...])."""
    ok, missing = _validate_scenario({})
    assert not ok
    for k in REQUIRED_KEYS:
        assert k in missing


def test_validate_scenario_partial_scoring() -> None:
    """scoring missing one of the three required keys → that key reported."""
    data = {
        "scenario_id": "x", "description": "y", "setup": "", "agent_invocation": "",
        "scoring": {"graceful_recovery": "g", "escalation_marker": "e"},
    }
    ok, missing = _validate_scenario(data)
    assert not ok
    assert "scoring.silent_failure" in missing


def test_validate_scenario_complete() -> None:
    """Full shape → (True, [])."""
    data = {
        "scenario_id": "x", "description": "y", "setup": "", "agent_invocation": "",
        "scoring": {"graceful_recovery": "g", "escalation_marker": "e", "silent_failure": "s"},
    }
    ok, missing = _validate_scenario(data)
    assert ok
    assert missing == []


# ----- runner seam -----

def _make_fixtures_dir(tmp_path: Path, *names: str) -> Path:
    """Copy each named fixture into a fresh eval/scenarios/ under tmp_path."""
    import shutil

    sdir = tmp_path / "eval" / "scenarios"
    sdir.mkdir(parents=True)
    for name in names:
        src = FIXTURES / name
        if not src.exists():
            pytest.skip(f"fixture not found: {src}")
        shutil.copy2(src, sdir / name)
    return sdir


def test_runner_seam_used_when_provided(tmp_path: Path) -> None:
    """ctx.scenario_runner replaces the default subprocess runner."""
    wt = tmp_path / "wt"
    _make_fixtures_dir(wt, "compile-error.yaml", "resource-exhaustion.yaml")
    calls = []

    def fake_runner(wt: Path, scenario: dict) -> Tuple[int, str]:
        calls.append(scenario["scenario_id"])
        # First call: matches compile-error graceful_recovery literal.
        # Second: matches resource-exhaustion escalation_marker literal.
        if scenario["scenario_id"] == "compile-error":
            return 0, "OK restored lib/_scenario_compile_error.py (recovered)"
        return 1, "ENOSPC no space left on device"

    ds = score(wt, Context(scenario_runner=fake_runner))
    assert calls == ["compile-error", "resource-exhaustion"]
    # Mean of (5, 3) = 4.0
    assert ds.value == 4
    assert ds.evidence["scenario_count"] == 2


def test_runner_seam_short_circuits_setup(tmp_path: Path) -> None:
    """When a runner is provided, no subprocess is spawned (no setup)."""
    wt = tmp_path / "wt"
    _make_fixtures_dir(wt, "compile-error.yaml")

    def fake_runner(wt: Path, scenario: dict) -> Tuple[int, str]:
        # Mark a side effect so we know the runner executed.
        (wt / "ran.txt").write_text("yes")
        return 0, "OK restored lib/_scenario_compile_error.py"

    score(wt, Context(scenario_runner=fake_runner))
    assert (wt / "ran.txt").exists()


def test_all_five_scenarios_run_with_runner(tmp_path: Path) -> None:
    """Happy path: all 5 fixtures scored, mean returned."""
    wt = tmp_path / "wt"
    fixtures = (
        "compile-error.yaml", "flaky-test.yaml", "missing-dep.yaml",
        "conflicting-instructions.yaml", "resource-exhaustion.yaml",
    )
    _make_fixtures_dir(wt, *fixtures)

    def fake_runner(wt: Path, scenario: dict) -> Tuple[int, str]:
        # Each scenario's runner output matches its graceful_recovery,
        # escalation_marker, or silent_failure signal value.
        sid = scenario["scenario_id"]
        if sid == "compile-error":
            return 0, "OK restored lib/_scenario_compile_error.py"
        if sid == "flaky-test":
            return 0, "recovered from flake"
        if sid == "missing-dep":
            return 0, "ModuleNotFoundError totally_missing_module_xyz"
        if sid == "conflicting-instructions":
            return 0, "please clarify with the user"
        return 1, "ENOSPC no space left on device"

    ds = score(wt, Context(scenario_runner=fake_runner))
    # 3 graceful (5) + 2 escalation (3) → mean = 21/5 = 4.2 → 4
    assert ds.evidence["scenario_count"] == 5
    assert ds.value == 4


def test_malformed_scenario_scores_three(tmp_path: Path) -> None:
    """A YAML missing required keys scores 3 (unknown)."""
    wt = tmp_path / "wt"
    sdir = wt / "eval" / "scenarios"
    sdir.mkdir(parents=True)
    (sdir / "broken.yaml").write_text("scenario_id: broken\n")  # missing the rest

    def no_runner(wt: Path, scenario: dict) -> Tuple[int, str]:
        raise AssertionError("runner should not be called for malformed scenario")

    ds = score(wt, Context(scenario_runner=no_runner))
    assert ds.value == 3
    per = ds.evidence["per_scenario"]
    assert len(per) == 1
    assert "missing_keys" in per[0]["error"]


# ----- dim value contract -----

def test_value_is_clamped_to_one_to_five(tmp_path: Path) -> None:
    """Even with all silent_failure (1) or all graceful (5), value is clamped."""
    wt = tmp_path / "wt"
    sdir = wt / "eval" / "scenarios"
    sdir.mkdir(parents=True)
    for name in ("a.yaml", "b.yaml", "c.yaml", "d.yaml", "e.yaml"):
        (sdir / name).write_text(
            "scenario_id: x\ndescription: y\nsetup: ''\nagent_invocation: ''\n"
            "scoring:\n  graceful_recovery: ok\n  escalation_marker: em\n"
            "  silent_failure: silent failure\n",
            encoding="utf-8",
        )

    def always_silent(wt: Path, scenario: dict) -> Tuple[int, str]:
        return 1, "silent failure observed"

    ds = score(wt, Context(scenario_runner=always_silent))
    assert 1 <= ds.value <= 5
    assert ds.value == 1
