"""Spec §Testing strategy: bootstrap with Y to the ci-setup prompt."""

from pathlib import Path


def test_bootstrap_with_ci_prompt_documented():
    text = Path(__file__).parent.parent.joinpath("skills/bootstrap/SKILL.md").read_text()
    assert "[Y/n]" in text
    # The Y branch must invoke install_ci_config
    assert "install_ci_config" in text, "Y branch must delegate to install_ci_config"
    # The end state claim must reference the legacy bootstrap-full
    assert "bootstrap-full" in text or "legacy" in text.lower(), \
        "Y branch must document end-state parity with legacy /dev-kit:bootstrap-full"
