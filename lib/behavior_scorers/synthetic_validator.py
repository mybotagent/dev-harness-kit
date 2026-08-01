"""Synthetic mutation checks for judge ordering reliability."""
from __future__ import annotations

import math
from typing import Any, Iterable

from lib.behavior_scorers.multi_judge import DEFAULT_AXES, MultiJudge


class SyntheticValidator:
    """Validate that a judge ranks controlled degradations below the original."""

    def __init__(self, multi_judge: MultiJudge | None = None) -> None:
        self.multi_judge = multi_judge or MultiJudge()

    @staticmethod
    def generate_mutations(note: str) -> list[dict[str, Any]]:
        paragraphs = [part.strip() for part in note.split("\n\n") if part.strip()]
        first = paragraphs[0] if paragraphs else note
        vague = [
            {"kind": "vague", "text": "Updated the requested files. It should work now."},
            {"kind": "vague", "text": "Made the changes and checked things."},
            {"kind": "vague", "text": "Fixed the issue. Please review."},
            {"kind": "vague", "text": "The implementation is complete and probably fine."},
            {"kind": "vague", "text": "Handled the work as discussed."},
        ]
        incomplete = [
            {"kind": "incomplete", "text": first},
            {"kind": "incomplete", "text": "Verification: tests passed."},
            {"kind": "incomplete", "text": "Implemented the requested change."},
            {"kind": "incomplete", "text": first + "\n\nThe remaining follow-up is documented."},
            {"kind": "incomplete", "text": "Files changed: implementation and tests."},
        ]
        verbose = [
            {"kind": "verbose", "text": note + "\n\n" + ("As a general note, this was carefully considered. " * 4)},
            {"kind": "verbose", "text": ("For context, the work was approached methodically. " * 5) + note},
            {"kind": "verbose", "text": note + "\n\n" + ("No additional action is implied by this sentence. " * 5)},
            {"kind": "verbose", "text": (note + "\n\n") + ("This sentence adds no actionable information. " * 6)},
            {"kind": "verbose", "text": ("It is worth noting that this note contains details. " * 4) + note},
        ]
        original = [{"kind": "original", "text": note} for _ in range(5)]
        return vague + incomplete + verbose + original

    @staticmethod
    def pearson_r(actual: Iterable[float], expected: Iterable[float]) -> float:
        x, y = list(actual), list(expected)
        if len(x) != len(y) or len(x) < 2:
            return 0.0
        x_mean, y_mean = sum(x) / len(x), sum(y) / len(y)
        numerator = sum((a - x_mean) * (b - y_mean) for a, b in zip(x, y))
        denominator = math.sqrt(
            sum((a - x_mean) ** 2 for a in x) * sum((b - y_mean) ** 2 for b in y)
        )
        return numerator / denominator if denominator else 0.0

    def validate(self, note: str, axes: tuple[str, ...] = DEFAULT_AXES) -> dict[str, Any]:
        mutations = self.generate_mutations(note)
        expected = {"vague": 1.0, "incomplete": 2.0, "verbose": 3.0, "original": 4.0}
        scores = [self.multi_judge.judge(item["text"], axes).get("mean", 0.0) for item in mutations]
        ranking = [expected[item["kind"]] for item in mutations]
        correlation = self.pearson_r(scores, ranking)
        return {
            "pearson_r": correlation,
            "samples_tested": len(mutations),
            "pass": correlation >= 0.6,
        }

    # Friendly alias for callers using the operation name as the entry point.
    run = validate


__all__ = ["SyntheticValidator"]
