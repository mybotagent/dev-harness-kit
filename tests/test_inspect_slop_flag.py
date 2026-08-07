"""Spec §Testing strategy: --slop wiring alias."""

from pathlib import Path

from lib.analysis_core.dimensions import REGISTRY


def test_slop_dimension_in_registry():
    assert "slop" in REGISTRY, "slop dimension must exist in REGISTRY"


def test_slop_alias_documented_in_skill():
    text = Path(__file__).parent.parent.joinpath("skills/inspect/SKILL.md").read_text()
    assert "--slop" in text and ("--dim slop" in text or "slop" in text.lower())
