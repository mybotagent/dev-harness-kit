"""test_d6_scenarios.py — validates all 5 D6 scenario YAML fixtures.

Pure schema check: every fixture must parse, must declare all
required keys (top-level + nested under scoring), and must have
non-empty signal values. Does NOT run the scenarios (the runner
test does that).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from lib.behavior_scorers.robustness import (  # noqa: E402
    REQUIRED_KEYS,
    _parse_yaml,
    _validate_scenario,
)

FIXTURES = Path(__file__).parent.parent / "eval" / "scenarios"

EXPECTED_IDS = {
    "compile-error": "compile-error.yaml",
    "flaky-test": "flaky-test.yaml",
    "missing-dep": "missing-dep.yaml",
    "conflicting-instructions": "conflicting-instructions.yaml",
    "resource-exhaustion": "resource-exhaustion.yaml",
}

SCORING_SIGNALS = ("graceful_recovery", "escalation_marker", "silent_failure")


@pytest.fixture(scope="module")
def parsed_fixtures() -> dict:
    """Parse all 5 fixture YAMLs once per test module."""
    out = {}
    for sid, fname in EXPECTED_IDS.items():
        path = FIXTURES / fname
        if not path.exists():
            pytest.skip(f"fixture not found: {path}")
        out[sid] = _parse_yaml(path)
    return out


def test_all_required_keys_present(parsed_fixtures: dict) -> None:
    """Every fixture has the full set of required top-level + scoring keys."""
    for sid, data in parsed_fixtures.items():
        ok, missing = _validate_scenario(data)
        assert ok, f"{sid}: missing keys {missing}"


def test_scenario_id_matches_filename(parsed_fixtures: dict) -> None:
    """scenario_id must equal the EXPECTED_IDS key."""
    for sid, data in parsed_fixtures.items():
        assert data["scenario_id"] == sid


def test_top_level_required_keys() -> None:
    """REQUIRED_KEYS exposes the canonical set (5 top-level + 3 scoring)."""
    assert "scenario_id" in REQUIRED_KEYS
    assert "description" in REQUIRED_KEYS
    assert "setup" in REQUIRED_KEYS
    assert "agent_invocation" in REQUIRED_KEYS
    assert "scoring" in REQUIRED_KEYS


def test_every_fixture_has_nonempty_signal_values(parsed_fixtures: dict) -> None:
    """All three scoring signals are non-empty strings."""
    for sid, data in parsed_fixtures.items():
        scoring = data.get("scoring") or {}
        for sig in SCORING_SIGNALS:
            assert sig in scoring, f"{sid}: missing scoring.{sig}"
            assert isinstance(scoring[sig], str), f"{sid}.scoring.{sig} not str"
            assert scoring[sig].strip(), f"{sid}.scoring.{sig} is empty"


def test_every_fixture_has_description(parsed_fixtures: dict) -> None:
    """Description is a non-empty string for every fixture."""
    for sid, data in parsed_fixtures.items():
        assert isinstance(data.get("description"), str)
        assert data["description"].strip()


def test_every_fixture_has_setup_and_invocation(parsed_fixtures: dict) -> None:
    """Setup + agent_invocation must both be present (strings; may be empty)."""
    for sid, data in parsed_fixtures.items():
        assert "setup" in data
        assert "agent_invocation" in data


def test_fixture_files_count() -> None:
    """The eval/scenarios/ dir has exactly 5 YAML fixtures."""
    if not FIXTURES.is_dir():
        pytest.skip(f"scenarios dir missing: {FIXTURES}")
    yamls = list(FIXTURES.glob("*.yaml"))
    assert len(yamls) == 5, f"expected 5 scenarios, got {len(yamls)}: {[p.name for p in yamls]}"


def test_fixture_files_are_distinct() -> None:
    """No duplicate scenario_id values across the 5 fixtures."""
    if not FIXTURES.is_dir():
        pytest.skip(f"scenarios dir missing: {FIXTURES}")
    seen = []
    for p in FIXTURES.glob("*.yaml"):
        data = _parse_yaml(p)
        seen.append(data.get("scenario_id", p.stem))
    assert len(seen) == len(set(seen)), f"duplicate scenario_ids: {seen}"
