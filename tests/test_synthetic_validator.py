from lib.behavior_scorers.synthetic_validator import SyntheticValidator


class FakeJudge:
    def judge(self, prompt, axes):
        if "requested files" in prompt or "changes" in prompt or "issue" in prompt or "discussed" in prompt or "probably" in prompt:
            value = 1
        elif prompt == "original note":
            value = 4
        elif "adds no" in prompt or "methodically" in prompt or "general note" in prompt or "worth noting" in prompt:
            value = 3
        else:
            value = 2
        return {"mean": value}


def test_mutation_generation_has_four_equal_categories() -> None:
    mutations = SyntheticValidator.generate_mutations("original note\n\nVerification: tests passed.")
    assert len(mutations) == 20
    assert {kind: sum(item["kind"] == kind for item in mutations) for kind in {item["kind"] for item in mutations}} == {
        "vague": 5, "incomplete": 5, "verbose": 5, "original": 5,
    }


def test_mutations_preserve_original_samples() -> None:
    mutations = SyntheticValidator.generate_mutations("original note")
    assert all(item["text"] == "original note" for item in mutations[-5:])


def test_pearson_r_perfect_positive() -> None:
    assert SyntheticValidator.pearson_r([1, 2, 3], [2, 4, 6]) == 1.0


def test_pearson_r_constant_series_is_zero() -> None:
    assert SyntheticValidator.pearson_r([1, 1, 1], [1, 2, 3]) == 0.0


def test_validate_returns_sample_count_and_pass_flag() -> None:
    result = SyntheticValidator(FakeJudge()).validate("original note")
    assert result["samples_tested"] == 20
    assert isinstance(result["pearson_r"], float)
    assert isinstance(result["pass"], bool)


def test_run_is_alias_for_validation() -> None:
    result = SyntheticValidator(FakeJudge()).run("original note")
    assert result["samples_tested"] == 20
