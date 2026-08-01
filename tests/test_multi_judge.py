from lib.behavior_scorers.multi_judge import MultiJudge


def _judge(values):
    def call(prompt, axes, model):
        return {"scores": {axis: values[model] for axis in axes}}
    return call


def test_multi_judge_aggregates_three_model_scores() -> None:
    judge = MultiJudge(judge_fn=_judge({"Claude Opus 4.8": 4, "GPT-4o": 5, "Gemini 2.5 Pro": 3}))
    result = judge.judge("note", ("clarity", "specificity"))
    assert result["scores"] == {"clarity": 4.0, "specificity": 4.0}
    assert result["mean"] == 4.0
    assert result["std"] > 0


def test_multi_judge_high_confidence() -> None:
    result = MultiJudge(judge_fn=_judge({model: 4 for model in ("Claude Opus 4.8", "GPT-4o", "Gemini 2.5 Pro")})).judge("p", ("clarity",))
    assert result["confidence"] == "HIGH"
    assert result["std"] == 0.0


def test_multi_judge_medium_confidence() -> None:
    result = MultiJudge(judge_fn=_judge({"Claude Opus 4.8": 3, "GPT-4o": 4.0, "Gemini 2.5 Pro": 4.5})).judge("p", ("clarity",))
    assert result["confidence"] == "MEDIUM"
    assert 0.5 <= result["std"] < 1.0


def test_multi_judge_low_confidence() -> None:
    result = MultiJudge(judge_fn=_judge({"Claude Opus 4.8": 1, "GPT-4o": 5, "Gemini 2.5 Pro": 1})).judge("p", ("clarity",))
    assert result["confidence"] == "LOW"


def test_multi_judge_requires_three_models() -> None:
    try:
        MultiJudge(models=("one",))
    except ValueError as exc:
        assert "three" in str(exc)
    else:
        raise AssertionError("a consensus needs three judges")


def test_multi_judge_ignores_missing_axis_scores() -> None:
    def call(prompt, axes, model):
        return {"scores": {"clarity": 4}}
    result = MultiJudge(judge_fn=call).judge("p", ("clarity", "missing"))
    assert result["scores"] == {"clarity": 4.0}
    assert result["mean"] == 4.0


def test_multi_judge_supports_keyword_test_seam() -> None:
    def call(**kwargs):
        return {"scores": {axis: 3 for axis in kwargs["axes"]}}
    assert MultiJudge(judge_fn=call).judge("p", ("clarity",))["confidence"] == "HIGH"
