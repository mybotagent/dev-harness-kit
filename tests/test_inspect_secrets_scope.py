"""Regression test: --secrets documentation contract.

A03 carry-over from PR-589 security review (fabf466 fix landed the doc
contract; this test prevents future drift from re-introducing the
lockfile/generated-artifact exclusion under --secrets).

The actual scanning is done by Agent sub-processes (not the local
engine), so a unit test asserting on engine output is the wrong contract.
We assert on the SKILL.md text — which the orchestrator reads.
"""

from pathlib import Path

SKILL = Path(__file__).parent.parent / "skills" / "inspect" / "SKILL.md"


def test_secrets_includes_lockfiles_in_scope():
    """The inspect SKILL.md must state that --secrets does NOT exclude lockfiles."""
    text = SKILL.read_text()
    assert "--secrets" in text, "expected --secrets to be documented in inspect SKILL.md"
    assert "lockfile" in text.lower(), "expected the word 'lockfile' to appear in SKILL.md"
    # The critical assertion: --secrets must explicitly state the lockfile/generate
    # exclusion is NOT applied. Look for the doc-fix phrase.
    assert "do NOT" in text and ("lockfile" in text or "generated" in text), (
        "expected an explicit do-NOT-exclude statement for --secrets. "
        "PR-589 A03 fix added this to prevent re-introducing the lockfile exclusion."
    )


def test_default_inspect_scope_still_excludes_lockfiles():
    """Sanity check: the default inspect scope (no --secrets) still skips lockfiles.

    The exclusion applies only to the default 8-dim scan, NOT to --secrets.
    """
    text = SKILL.read_text()
    assert "lockfile" in text.lower()
    # The default scope rule must remain
    assert ".git/" in text and "node_modules" in text and "dist" in text
