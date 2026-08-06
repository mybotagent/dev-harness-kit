"""Spec §Testing strategy: --secrets wiring alias.

Asserts that the SKILL.md body documents the --secrets -> --dim secret
alias and that the audit-family secret dimension is in the registry.
The actual scan runs via Agent sub-processes (not local engine), so
this is a doc-contract + registry-presence test.
"""

from pathlib import Path

from lib.analysis_core.dimensions import REGISTRY


def test_secrets_dimension_in_registry():
    assert "secret" in REGISTRY, "secret dimension must exist in REGISTRY for --secrets to resolve"


def test_secrets_alias_documented_in_skill():
    text = Path(__file__).parent.parent.joinpath("skills/inspect/SKILL.md").read_text()
    assert "--secrets" in text and ("--dim secret" in text or "secret" in text.lower()), \
        "inspect SKILL.md must document the --secrets alias"
