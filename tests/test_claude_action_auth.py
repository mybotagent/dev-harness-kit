"""Regression tests for deterministic GitHub authentication in Claude jobs."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
WORKFLOWS = (
    REPO_ROOT / ".github/workflows/review.yml",
    REPO_ROOT / ".github/workflows/maintenance.yml",
    REPO_ROOT / "templates/ci/.github/workflows/review.yml",
)


def _claude_with_blocks(text: str) -> list[str]:
    return re.findall(
        r"uses:\s+anthropics/claude-code-action@v1\n(?P<block>\s+with:\n.*?)(?=\n\s*(?:- name:|uses:|$))",
        text,
        re.DOTALL,
    )


def test_every_claude_action_uses_workflow_token() -> None:
    for workflow in WORKFLOWS:
        blocks = _claude_with_blocks(workflow.read_text())
        assert blocks, f"no Claude action blocks found in {workflow}"
        for block in blocks:
            assert "github_token: ${{ secrets.GITHUB_TOKEN }}" in block, workflow


def test_review_jobs_do_not_request_unneeded_oidc_tokens() -> None:
    for workflow in WORKFLOWS:
        text = workflow.read_text()
        assert "id-token: write" not in text, workflow
