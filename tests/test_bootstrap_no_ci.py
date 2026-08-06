"""Spec §Testing strategy: bootstrap with N to the ci-setup prompt."""

from pathlib import Path


def test_bootstrap_no_ci_prompt_documented():
    """The bootstrap SKILL.md must document the Y/n prompt and the unavailable-features list."""
    text = Path(__file__).parent.parent.joinpath("skills/bootstrap/SKILL.md").read_text()
    assert "ci-setup" in text.lower(), "expected ci-setup prompt documentation"
    assert "[Y/n]" in text, "expected the literal [Y/n] prompt"
    assert "/dev-kit:ci-doctor" in text and "/dev-kit:bump" in text, \
        "unavailable-features list must include /dev-kit:ci-doctor and /dev-kit:bump"
