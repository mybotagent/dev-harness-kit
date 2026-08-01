"""Relative-only calibration confidence calculation."""
from __future__ import annotations


def compute_confidence(anchor_match: float, cross_std: float, synthetic_r: float) -> float:
    """Combine relative anchor agreement, consensus, and synthetic ordering."""
    return 0.4 * anchor_match + 0.3 * (1 - cross_std) + 0.3 * synthetic_r


def is_calibrated(confidence: float) -> bool:
    """Return whether the composite meets the calibration contract."""
    return confidence >= 0.7


__all__ = ["compute_confidence", "is_calibrated"]
