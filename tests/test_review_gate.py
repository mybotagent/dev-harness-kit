#!/usr/bin/env python3
"""test_review_gate.py — Regression tests for the severity-gate tolerance.

The severity gate (the `Combined verdict gate` step in
.github/workflows/review.yml) used to hard-fail in pull_request mode when
either review or security verdict was empty. The fix defaults both to
Approve + ::warning:: regardless of event mode, on the theory that the
human gate (REVIEW_REQUIRED / CHANGES_REQUESTED on the PR) is what
actually blocks merge -- not a single missing agent verdict.

These tests extract the gate bash from review.yml and execute it via
subprocess with controlled R/S/EVENT env vars. They protect against:

  - Pull_request mode with empty R, empty S: must exit 0 (was exit 1)
  - Pull_request mode with empty R, non-empty S: must exit 0 (was exit 1)
  - Pull_request mode with non-empty R, empty S: must exit 0 (was exit 1)
  - Pull_request mode with both Approve: exit 0
  - Pull_request mode with Changes Requested worst-of: exit 1
  - Pull_request mode with Blocked worst-of: exit 1
  - Workflow_dispatch mode with empty R: defaults to Approve, exit 0
  - Unparseable verdict (e.g. "Requested"): ::warning:: + exit 0
"""
from __future__ import annotations

import os
import re
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
# Source-of-truth: the consumer template SSOT (templates/ci/.github/workflows/review.yml).
# The local .github/workflows/review.yml is kept in lockstep with the template, but the
# template is what ships to consumers via /dev-kit:ci-setup, so it is the canonical source.
GATE_SNIPPET = (REPO_ROOT / "templates" / "ci" / ".github" / "workflows" / "review.yml").read_text()


def _extract_gate_bash() -> str:
    """Extract the `Combined verdict gate` step's bash body.

    Looks for `      - name: Combined verdict gate` followed by `        run: |`
    and captures every subsequent line indented under the run block.
    """
    lines = GATE_SNIPPET.splitlines()
    # Find the gate step header.
    step_idx = None
    for i, ln in enumerate(lines):
        if ln.strip() == "- name: Combined verdict gate":
            step_idx = i
            break
    if step_idx is None:
        raise RuntimeError("Combined verdict gate step not found")
    # The bash body starts after the `run: |` line.
    body_start = None
    for j in range(step_idx, min(step_idx + 5, len(lines))):
        if lines[j].lstrip().startswith("run:"):
            body_start = j + 1
            break
    if body_start is None:
        raise RuntimeError("`run:` not found in gate step")
    # Find the common indent (first non-empty body line).
    indent = None
    for j in range(body_start, len(lines)):
        if lines[j].strip():
            indent = len(lines[j]) - len(lines[j].lstrip())
            break
    if indent is None:
        raise RuntimeError("empty gate body")
    # Collect lines while they stay at or beyond `indent`.
    body = []
    for j in range(body_start, len(lines)):
        if not lines[j].strip():
            body.append("")
            continue
        if len(lines[j]) - len(lines[j].lstrip()) < indent:
            break
        body.append(lines[j][indent:])
    return "\n".join(body).rstrip() + "\n"


def _run_gate(r: str, s: str, event: str = "pull_request") -> subprocess.CompletedProcess:
    """Execute the gate bash with R, S, EVENT_NAME env vars. Returns CompletedProcess."""
    bash = _extract_gate_bash()
    # Strip the `needs.<job>.outputs.verdict` interpolation lines -- they're
    # GitHub Actions expressions, not real bash. Replace with env-driven values.
    bash = bash.replace('R="${{ needs.review.outputs.verdict }}"', 'R="${R_OVERRIDE:-}"')
    bash = bash.replace('S="${{ needs.security.outputs.verdict }}"', 'S="${S_OVERRIDE:-}"')
    bash = bash.replace('EVENT="$EVENT_NAME"', 'EVENT="${EVENT_OVERRIDE:-pull_request}"')
    env = os.environ.copy()
    env["R_OVERRIDE"] = r
    env["S_OVERRIDE"] = s
    env["EVENT_OVERRIDE"] = event
    return subprocess.run(
        ["bash", "-c", bash],
        capture_output=True, text=True, env=env, timeout=10,
    )


class TestSeverityGateTolerance(unittest.TestCase):
    """The new contract: empty R or S HARD-FAILS (block merge if LLM didn't run).

    Pre-#44 the gate defaulted missing verdicts to Approve + warning silently,
    which hid workflow-validation skips from PR authors. The new gate exits 1
    on any missing/unparseable verdict so the PR author sees a red check
    immediately and re-runs CI. Real review feedback (Changes Requested /
    Blocked) still exits 1.
    """

    def test_pull_request_empty_R_empty_S_exits_one(self):
        """Empty R AND empty S: HARD FAIL — LLM didn't run at all. Gate exits
        on the first missing verdict (review), so only that error is checked."""
        cp = _run_gate(r="", s="", event="pull_request")
        self.assertEqual(
            cp.returncode, 1,
            f"empty R/S in pull_request mode MUST hard-fail (block silent-Approve).\nstdout={cp.stdout}\nstderr={cp.stderr}",
        )
        self.assertIn("::error::review verdict missing", cp.stdout)

    def test_pull_request_empty_R_nonempty_S_exits_one(self):
        cp = _run_gate(r="", s="Approve", event="pull_request")
        self.assertEqual(cp.returncode, 1, cp.stdout + cp.stderr)
        self.assertIn("::error::review verdict missing", cp.stdout)

    def test_pull_request_nonempty_R_empty_S_exits_one(self):
        cp = _run_gate(r="Approve", s="", event="pull_request")
        self.assertEqual(cp.returncode, 1, cp.stdout + cp.stderr)
        self.assertIn("::error::security verdict missing", cp.stdout)

    def test_pull_request_both_approve_exits_zero(self):
        cp = _run_gate(r="Approve", s="Approve", event="pull_request")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        self.assertIn("Combined worst verdict: Approve", cp.stdout)

    def test_pull_request_changes_requested_exits_one(self):
        """Real review feedback still blocks: this is not a free-pass."""
        cp = _run_gate(r="Changes Requested", s="Approve", event="pull_request")
        self.assertEqual(cp.returncode, 1, cp.stdout + cp.stderr)
        self.assertIn("::error::Changes Requested", cp.stdout)

    def test_pull_request_blocked_exits_one(self):
        cp = _run_gate(r="Blocked", s="Approve", event="pull_request")
        self.assertEqual(cp.returncode, 1, cp.stdout + cp.stderr)
        self.assertIn("::error::Blocked", cp.stdout)

    def test_pull_request_unparseable_verdict_blocks(self):
        """The 'Requested' truncation case: now HARD-FAIL (was previously tolerated)."""
        cp = _run_gate(r="Requested", s="Approve", event="pull_request")
        self.assertEqual(cp.returncode, 1, cp.stdout + cp.stderr)
        self.assertIn("Unparseable verdict", cp.stdout)

    def test_workflow_dispatch_empty_R_blocks(self):
        """Even workflow_dispatch: empty R HARD-FAILS (no silent Approve)."""
        cp = _run_gate(r="", s="Approve", event="workflow_dispatch")
        self.assertEqual(cp.returncode, 1, cp.stdout + cp.stderr)

    def test_extracted_bash_is_nonempty(self):
        """Sanity: the extractor actually returns bash, not a header."""
        bash = _extract_gate_bash()
        self.assertIn("R=", bash)
        self.assertIn("S=", bash)
        self.assertIn("EVENT=", bash)
        self.assertNotIn("run:", bash, "extractor must strip the run: | header")


if __name__ == "__main__":
    unittest.main()
