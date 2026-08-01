"""Cross-model consensus for relative behavior comparisons."""
from __future__ import annotations

import math
import os
from statistics import fmean, pstdev
from typing import Any, Callable, Dict, Iterable, Tuple

from lib.llm_judge import call_judge

DEFAULT_MODELS: Tuple[str, ...] = (
    "Claude Opus 4.8",
    "GPT-4o",
    "Gemini 2.5 Pro",
)
DEFAULT_AXES: Tuple[str, ...] = (
    "clarity",
    "completeness",
    "specificity",
    "actionability",
    "handoff_safety",
)


class MultiJudge:
    """Call three independent judges and report their relative consensus.

    ``judge_fn`` is an optional test seam (and useful for callers that already
    own provider routing). It receives ``(prompt, axes, model)`` and returns a
    mapping containing ``scores`` or an axis-score mapping directly.
    """

    def __init__(
        self,
        judge_fn: Callable[..., Dict[str, Any]] | None = None,
        models: Iterable[str] = DEFAULT_MODELS,
    ) -> None:
        self.judge_fn = judge_fn
        self.models = tuple(models)
        if len(self.models) != 3:
            raise ValueError("MultiJudge requires exactly three judge models")

    def _call_model(self, prompt: str, axes: Tuple[str, ...], model: str) -> Dict[str, Any]:
        if self.judge_fn is not None:
            try:
                return self.judge_fn(prompt, axes, model)
            except TypeError:
                return self.judge_fn(prompt=prompt, axes=axes, model=model)
        provider = os.environ.get("JUDGE_PROVIDER", "minimax")
        key_var = "MINIMAX_API_KEY" if provider == "minimax" else "ANTHROPIC_API_KEY"
        return call_judge(
            provider=provider,
            api_key=os.environ.get(key_var, ""),
            model=model,
            prompt=prompt,
            axes=axes,
            base_url=os.environ.get("JUDGE_BASE_URL", "https://api.minimax.io/anthropic"),
        )

    @staticmethod
    def _scores(result: Dict[str, Any], axes: Tuple[str, ...]) -> Dict[str, float]:
        values = result.get("scores", result) if isinstance(result, dict) else {}
        out: Dict[str, float] = {}
        for axis in axes:
            try:
                value = float(values[axis])
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(value):
                out[axis] = value
        return out

    def judge(self, prompt: str, axes: tuple[str, ...] = DEFAULT_AXES) -> dict:
        """Return per-axis means, consensus standard deviation, and confidence."""
        per_judge = [self._scores(self._call_model(prompt, axes, model), axes) for model in self.models]
        axis_means = {
            axis: fmean(values)
            for axis in axes
            if (values := [scores[axis] for scores in per_judge if axis in scores])
        }
        judge_means = [fmean(list(scores.values())) for scores in per_judge if scores]
        cross_std = pstdev(judge_means) if len(judge_means) > 1 else 0.0
        mean = fmean(list(axis_means.values())) if axis_means else 0.0
        if cross_std < 0.5:
            confidence = "HIGH"
        elif cross_std < 1.0:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"
        return {
            "scores": axis_means,
            "mean": mean,
            "std": cross_std,
            "confidence": confidence,
        }


__all__ = ["DEFAULT_AXES", "DEFAULT_MODELS", "MultiJudge"]
