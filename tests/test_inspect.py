#!/usr/bin/env python3
"""test_inspect.py — Regression for skills/inspect/SKILL.md schema.

After P1 (analysis-core engine), inspect is a thin procedural shell
that delegates to `lib.analysis_core.run_analysis(...)`. This test
locks in the new compact shape:

- description declares 8 dims
- --dim flag list mentions all 8 named dims
- dimension charter bullets cover 8 named dims (one-line charters)
- the engine handles per-dim HIGH/MED/LOW counts (renderer in
  lib.analysis_core.runner.render_markdown) — not duplicated here
- hand-off routing table has 8 rows
- hand-off routes to /dev-kit:refactor AND /dev-kit:prune
- body references the engine entrypoint (lib.analysis_core.run_analysis)
- body has <= 60 lines (procedural shell)
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
INSPECT_SKILL = PROJECT_ROOT / "skills" / "inspect" / "SKILL.md"
EXPECTED_DIMS = (
    "dead", "dup", "smell", "overeng", "overarch", "cleancode",
    "tokenbudget", "slop",
)
MAX_BODY_LINES = 60


class TestInspectSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not INSPECT_SKILL.exists():
            raise unittest.SkipTest(f"{INSPECT_SKILL} missing")
        cls.text = INSPECT_SKILL.read_text(encoding="utf-8")

    def test_description_mentions_eight_dims(self):
        m = re.search(r"^description:\s*(.+)$", self.text, re.MULTILINE)
        self.assertIsNotNone(m, "description: frontmatter missing")
        desc = m.group(1)
        self.assertIn("8-dim", desc, f"description should declare 8-dim; got: {desc!r}")

    def test_dim_flag_lists_all_eight(self):
        # Find the --dim <name> usage line and check the dim list
        # that follows it contains all 8 named dims.
        m = re.search(r"`--dim <name>`[^\n]*", self.text)
        self.assertIsNotNone(m, "--dim flag description missing")
        # The list of dim names appears in a backtick-quoted span on
        # the same line OR in the next backtick-quoted span. Walk
        # forward through backtick-delimited tokens and assert each
        # appears somewhere in the document (engine SSOT) but the
        # --dim scope line lists them all.
        scope_line = m.group(0)
        for dim in EXPECTED_DIMS:
            self.assertIn(
                dim, scope_line,
                f"--dim flag scope line must list {dim!r}; got: {scope_line!r}",
            )

    def test_dimension_charters_cover_all_eight(self):
        for dim in EXPECTED_DIMS:
            pattern = rf"-\s+\*\*{dim}\*\*"
            self.assertRegex(
                self.text, pattern,
                f"dimension charter missing for {dim!r}",
            )

    def test_hand_off_routing_table_has_eight_rows(self):
        # The hand-off section now starts with `## Hand-off` and runs
        # to end-of-body or `## Next step` / similar. New shape: 8 rows.
        m = re.search(r"## Hand-off(.*?)(?:## Next|\Z)", self.text, re.DOTALL)
        self.assertIsNotNone(m, "Hand-off section missing")
        block = m.group(1)
        rows = [
            line for line in block.splitlines()
            if line.startswith("| ") and "---" not in line and "Dim" not in line
        ]
        self.assertEqual(
            len(rows), len(EXPECTED_DIMS),
            f"Hand-off table has {len(rows)} rows; expected {len(EXPECTED_DIMS)} (one per dim)",
        )

    def test_hand_off_routes_to_refactor_and_prune(self):
        m = re.search(r"## Hand-off(.*?)(?:## Next|\Z)", self.text, re.DOTALL)
        self.assertIsNotNone(m, "Hand-off section missing")
        block = m.group(1)
        self.assertIn(
            "/dev-kit:refactor", block,
            "Hand-off should route whole-pipeline to /dev-kit:refactor",
        )
        self.assertIn(
            "/dev-kit:prune", block,
            "Hand-off should route deletion candidates to /dev-kit:prune",
        )

    def test_delegates_to_engine(self):
        # New procedural shape: the body must reference the engine
        # entrypoint so the dimension knowledge lives in one place.
        self.assertIn(
            "lib.analysis_core.run_analysis",
            self.text,
            "inspect SKILL.md must delegate to lib.analysis_core.run_analysis",
        )
        self.assertIn(
            "group(\"inspect\")",
            self.text,
            "inspect SKILL.md must request its dimension set via group(\"inspect\")",
        )

    def test_skill_is_thin_shell(self):
        # Procedural shell budget: the entire SKILL.md is <= 60 lines.
        line_count = len(self.text.splitlines())
        self.assertLessEqual(
            line_count, MAX_BODY_LINES,
            f"inspect SKILL.md has {line_count} lines; "
            f"procedural shell budget is {MAX_BODY_LINES}",
        )

    def test_engine_owns_per_dim_counts(self):
        # The renderer's HIGH/MED/LOW per-dim table moved into
        # lib.analysis_core.runner.render_markdown. The skill body
        # must NOT duplicate that table.
        self.assertNotIn(
            "## Per-dimension summary",
            self.text,
            "Per-dim HIGH/MED/LOW table moved to lib.analysis_core.runner.render_markdown",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
