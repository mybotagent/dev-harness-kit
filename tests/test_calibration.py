import pytest

from lib.behavior_scorers.calibration import compute_confidence, is_calibrated


def test_compute_confidence_uses_composite_formula() -> None:
    assert compute_confidence(0.8, 0.1, 0.9) == pytest.approx(0.86)


def test_is_calibrated_at_boundary() -> None:
    assert is_calibrated(0.7)


def test_is_calibrated_below_boundary() -> None:
    assert not is_calibrated(0.6999)


def test_confidence_can_compare_relative_candidates() -> None:
    assert compute_confidence(0.9, 0.1, 0.9) > compute_confidence(0.7, 0.4, 0.7)
