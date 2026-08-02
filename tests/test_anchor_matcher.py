from pathlib import Path

from lib.behavior_scorers.anchor_matcher import jaccard_similarity, match_anchor


def test_jaccard_similarity_uses_token_sets() -> None:
    assert jaccard_similarity("alpha beta beta", "beta gamma") == 1 / 3


def test_jaccard_similarity_empty_notes_match() -> None:
    assert jaccard_similarity("", "") == 1.0


def test_match_anchor_returns_nearest_tier() -> None:
    anchors = [
        {"id": "gold-01", "tier": "gold", "hand_off": "files tests verification"},
        {"id": "bronze-01", "tier": "bronze", "hand_off": "something vague"},
    ]
    result = match_anchor("files and tests with verification", anchors)
    assert result["anchor_id"] == "gold-01"
    assert result["matched_tier"] == "gold"
    assert result["similarity"] > 0.5


def test_match_anchor_loads_fixture_yaml() -> None:
    path = Path(__file__).parents[1] / "eval" / "anchors" / "communication.yaml"
    result = match_anchor("Changed lib/ci_setup.py and ran tests successfully", path)
    assert result["matched_tier"] in {"gold", "silver", "bronze"}
    assert result["anchor_id"]


def test_match_anchor_rejects_empty_anchor_set() -> None:
    try:
        match_anchor("note", [])
    except ValueError as exc:
        assert "anchor" in str(exc)
    else:
        raise AssertionError("empty anchors must fail")



def test_anchor_tie_keeps_first_anchor() -> None:
    result = match_anchor("same", [
        {"id": "first", "tier": "silver", "hand_off": "same"},
        {"id": "second", "tier": "gold", "hand_off": "same"},
    ])
    assert result["anchor_id"] == "first"
