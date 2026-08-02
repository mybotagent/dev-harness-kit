#!/usr/bin/env python3
"""
test_agent_governance.py — shape gates for Claude and Codex project agents.

This repo has a deliberately minimal flat check for project subagents,
proportionate for the small agent surface. Claude agents use Markdown
frontmatter; Codex agents use standalone TOML files. Both provider formats
live in the root agents/ SSOT directory.
Unlike skills/*/SKILL.md, which has rules/skill-authoring.md
and an alpha-gate baseline-diff test). This is deliberately minimal: a flat
check over the whole directory, proportionate for a single-agent dir. Do not
add baseline-diff / alpha-gate machinery here until a real over-investment
problem exists for agents the way it did for skills (see
tests/test_skill_governance.py's docstring for that history).
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

import tomllib

from tests.test_naming import KEBAB_RE, extract_frontmatter_field

PROJECT_ROOT = Path(__file__).parent.parent
AGENTS_DIR = PROJECT_ROOT / "agents"
CODEX_AGENTS_DIR = PROJECT_ROOT / "agents"

# Inline description accepted form (one value on a single line):
#   description: some non-empty text
# Block-scalar (`description: |`, `|-`, `>+`, ...) is NOT a real description —
# the FIRST LINE after the colon is just the indicator, so an agent author who
# wrote `description: |\n...` (or even `description: |` followed by no content)
# would pass a naive "extract the first line after colon, assert non-empty"
# check while shipping a descriptionless agent file. PR #494 review finding.
_BLOCK_SCALAR_RE = re.compile(r"^[|>][+-]?\s*(?:\d+)?\s*$")


def _extract_description_body(text: str) -> str:
    """Return the actual description body, walking block scalars if present.

    Mirrors ``extract_frontmatter_field`` for the inline case (in which case it
    returns the same string the helper does), but for a ``description: | …``
    block scalar it reads the indented continuation lines instead of the
    indicator. The result is what's "really" the description text.
    """
    m = re.match(r"^---\s*\n(.+?)\n---", text, re.DOTALL)
    if not m:
        return ""
    lines = m.group(1).splitlines()
    for idx, line in enumerate(lines):
        if line.startswith("description:"):
            value = line.split(":", 1)[1].strip()
            if not _BLOCK_SCALAR_RE.match(value or ""):
                return value  # inline, first line is the body
            # Block scalar — walk subsequent lines, keep the dedented body.
            body_lines = []
            for cont in lines[idx + 1:]:
                if cont and (cont.startswith((" ", "\t"))):
                    body_lines.append(cont)
                else:
                    break  # blank or non-indented ends the block
            return "\n".join(body_lines).strip()
    return ""


class TestAgentGovernance(unittest.TestCase):
    def test_agent_filename_matches_name(self):
        if not AGENTS_DIR.exists():
            self.skipTest("no agents dir yet")
        mismatches = []
        for agent_file in sorted(AGENTS_DIR.glob("*.md")):
            expected_name = agent_file.stem
            text = agent_file.read_text(encoding="utf-8")
            name_field = extract_frontmatter_field(text, "name")
            if name_field != expected_name:
                mismatches.append(
                    f"file={agent_file.name} but frontmatter name={name_field}"
                )
        self.assertEqual(mismatches, [], "Agent naming mismatches:\n" + "\n".join(mismatches))

    def test_agent_has_nonempty_description(self):
        if not AGENTS_DIR.exists():
            self.skipTest("no agents dir yet")
        violations = []
        for agent_file in sorted(AGENTS_DIR.glob("*.md")):
            text = agent_file.read_text(encoding="utf-8")
            body = _extract_description_body(text)
            if not body:
                violations.append(
                    f"{agent_file.name}: description is empty (inline miss or "
                    "block-scalar with no continuation lines) — PR #494 review"
                )
        self.assertEqual(
            violations, [],
            "Agents missing a non-empty description body:\n" + "\n".join(violations),
        )

    def test_description_block_scalar_must_have_real_body(self):
        """PR #494 reviewer finding: a ``description: |`` (or ``|-``, ``>``)
        block scalar passes naive "first line after colon, non-empty" checks
        even when the body has no real prose. ``_extract_description_body``
        must walk the continuation lines and require at least one real line.
        """
        # Empty block scalar (no continuation lines at all).
        self.assertEqual(
            _extract_description_body(
                "---\nname: empty-block-desc\n"
                "description: |\n---\nbody\n",
            ),
            "",
            "empty block-scalar must read as empty",
        )
        # Whitespace-only continuation.
        self.assertEqual(
            _extract_description_body(
                "---\nname: ws-block-desc\ndescription: |-\n   \n---\nbody\n",
            ),
            "",
            "whitespace-only block body must read as empty",
        )
        # Real multi-line body.
        body = _extract_description_body(
            "---\nname: real-block-desc\ndescription: |\n"
            "  Real description\n  with multiple lines.\n---\n",
        )
        self.assertIn("Real description", body)
        # Inline description unchanged.
        self.assertEqual(
            _extract_description_body(
                "---\nname: inline\ndescription: inline text\n---\n",
            ),
            "inline text",
        )

    def test_agents_kebab_case(self):
        if not AGENTS_DIR.exists():
            self.skipTest("no agents dir yet")
        violations = [
            agent_file.name
            for agent_file in sorted(AGENTS_DIR.glob("*.md"))
            if not KEBAB_RE.match(agent_file.stem)
        ]
        self.assertEqual(violations, [], "Agent filenames must be kebab-case:\n" + "\n".join(violations))

    def test_codex_agents_have_required_fields(self):
        if not CODEX_AGENTS_DIR.exists():
            self.skipTest("no agents dir yet")
        violations = []
        for agent_file in sorted(CODEX_AGENTS_DIR.glob("*.toml")):
            try:
                data = tomllib.loads(agent_file.read_text(encoding="utf-8"))
            except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
                violations.append(f"{agent_file.name}: invalid TOML ({exc})")
                continue
            expected_name = agent_file.stem
            if not KEBAB_RE.match(expected_name):
                violations.append(f"{agent_file.name}: filename must be kebab-case")
            if data.get("name") != expected_name:
                violations.append(
                    f"{agent_file.name}: name must be {expected_name!r}, got {data.get('name')!r}"
                )
            for field in ("description", "developer_instructions"):
                if not isinstance(data.get(field), str) or not data[field].strip():
                    violations.append(f"{agent_file.name}: {field} must be non-empty")
        self.assertEqual(violations, [], "Codex agent violations:\n" + "\n".join(violations))

    def test_codex_agents_are_read_only_when_declared(self):
        if not CODEX_AGENTS_DIR.exists():
            self.skipTest("no agents dir yet")
        violations = []
        for agent_file in sorted(CODEX_AGENTS_DIR.glob("*.toml")):
            data = tomllib.loads(agent_file.read_text(encoding="utf-8"))
            if data.get("name") == "worktree-janitor" and data.get("sandbox_mode") != "read-only":
                violations.append(f"{agent_file.name}: worktree-janitor must use sandbox_mode = 'read-only'")
        self.assertEqual(violations, [], "Codex agent safety violations:\n" + "\n".join(violations))


if __name__ == "__main__":
    unittest.main()
