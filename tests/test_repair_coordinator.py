import json
from pathlib import Path

import pytest
from repair_coordinator import (
    MAX_REPAIR_ATTEMPTS,
    RepairState,
    append_event,
    failure_signature,
    has_progress,
    next_state,
    repair_key,
)


def _state(attempt=0):
    return RepairState(1, 1, attempt, "same-failure", "run-1", "abc123")


def test_failure_signature_is_stable_for_unordered_inputs():
    first = failure_signature(category="ci", checks=["b", "a"], findings=["F2", "F1"])
    second = failure_signature(category="ci", checks=["a", "b"], findings=["F1", "F2"])
    assert first == second


def test_progress_detects_fewer_findings_or_more_successes():
    previous = {"failure_signature": "same", "finding_ids": ["F1", "F2"], "successful_checks": 1}
    assert has_progress(previous, {"failure_signature": "same", "finding_ids": ["F1"], "successful_checks": 1})
    assert has_progress(previous, {"failure_signature": "same", "finding_ids": ["F1", "F2"], "successful_checks": 2})
    assert not has_progress(previous, {"failure_signature": "same", "finding_ids": ["F1", "F2"], "successful_checks": 1})


def test_no_progress_creates_repair_attempts_one_and_two():
    first = next_state(_state(), current_observation={"failure_signature": "same-failure"}, new_pr=2, new_commit_sha="def456")
    second = next_state(first, current_observation={"failure_signature": "same-failure"}, new_pr=3, new_commit_sha="ghi789")
    assert (first.attempt, first.current_pr) == (1, 2)
    assert (second.attempt, second.current_pr) == (2, 3)


def test_missing_observation_signature_is_treated_as_unchanged():
    state = next_state(
        _state(),
        current_observation={"finding_ids": ["same-failure"]},
        new_pr=2,
        new_commit_sha="def456",
    )
    assert state.status == "repair_pr_required"
    assert state.attempt == 1


def test_empty_observation_signature_is_rejected():
    with pytest.raises(ValueError, match="failure_signature"):
        next_state(_state(), current_observation={"failure_signature": ""})


def test_third_no_progress_becomes_human_exception():
    terminal = next_state(_state(MAX_REPAIR_ATTEMPTS), current_observation={"failure_signature": "same-failure"})
    assert terminal.status == "human_exception"
    assert terminal.attempt == MAX_REPAIR_ATTEMPTS


def test_repair_key_deduplicates_same_parent_attempt_and_failure():
    assert repair_key(_state()) == "1:0:same-failure"


def test_append_event_writes_compact_jsonl(tmp_path: Path):
    path = append_event(tmp_path, "repair_pr_created", _state(), failure_reason="no_progress")
    record = json.loads(path.read_text().splitlines()[0])
    assert record["event"] == "repair_pr_created"
    assert record["schema_version"] == "1.0.0"
    assert record["parent_pr"] == 1
    assert record["failure_reason"] == "no_progress"


def test_append_event_rejects_empty_event(tmp_path: Path):
    with pytest.raises(ValueError, match="event is required"):
        append_event(tmp_path, "", _state())


def test_invalid_attempt_is_rejected():
    with pytest.raises(ValueError):
        _state(MAX_REPAIR_ATTEMPTS + 1).validate()
