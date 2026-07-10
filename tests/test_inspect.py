#!/usr/bin/env python3
"""test_inspect.py — Regression for skills/inspect/SKILL.md schema.

Locks in the 8-dim inspect contract so a future refactor that silently
drops a dim (or rewrites the hand-off table to fewer rows) fails the
gate before merge. Asserts:

- description declares 8 dims (not 6, not 7)
- --dim flag list includes 8 entries
- dimension-charter bullets cover 8 named dims
- per-dim summary table has 8 rows
- hand-off routing table has 8 rows
- hand-off mentions the simplify skill as the whole-pipeline wrapper
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
        # The --dim description wraps across 2 lines; use DOTALL to span them.
        m = re.search(r"--dim <name>.*?Multiple", self.text, re.DOTALL)
        self.assertIsNotNone(m, "--dim flag description missing")
        block = m.group(0)
        for dim in EXPECTED_DIMS:
            self.assertIn(dim, block, f"--dim list missing {dim!r} (block: {block!r})")

    def test_dimension_charters_cover_all_eight(self):
        for dim in EXPECTED_DIMS:
            pattern = rf"-\s+\*\*{dim}\*\*"
            self.assertRegex(
                self.text, pattern,
                f"dimension charter missing for {dim!r}",
            )

    def test_per_dimension_summary_table_has_eight_rows(self):
        m = re.search(
            r"## Per-dimension summary(.*?)## Notes",
            self.text, re.DOTALL,
        )
        self.assertIsNotNone(m, "per-dim summary block missing")
        block = m.group(1)
        rows = [line for line in block.splitlines() if line.startswith("| ") and "---" not in line]
        # header + separator + 8 data rows = 10 lines; drop header -> 9; drop separator -> 8
        data_rows = [r for r in rows if not r.startswith("| dim")]
        self.assertEqual(
            len(data_rows), len(EXPECTED_DIMS),
            f"per-dim summary table has {len(data_rows)} data rows; expected {len(EXPECTED_DIMS)}",
        )

    def test_hand_off_routing_table_has_eight_rows(self):
        m = re.search(
            r"## Hand-off(.*?)## Related",
            self.text, re.DOTALL,
        )
        self.assertIsNotNone(m, "Hand-off section missing")
        block = m.group(1)
        rows = [line for line in block.splitlines() if line.startswith("| ") and "---" not in line and "Dim" not in line]
        self.assertEqual(
            len(rows), len(EXPECTED_DIMS),
            f"Hand-off table has {len(rows)} rows; expected {len(EXPECTED_DIMS)} (one per dim)",
        )

    def test_hand_off_mentions_simplify(self):
        m = re.search(
            r"## Hand-off(.*?)## Related",
            self.text, re.DOTALL,
        )
        self.assertIsNotNone(m, "Hand-off section missing")
        block = m.group(1)
        self.assertIn("/dev-kit:simplify", block, "Hand-off should route whole-pipeline to /dev-kit:simplify")


if __name__ == "__main__":
    unittest.main(verbosity=2)
