#!/usr/bin/env python3
"""
test_write_claude_md.py — RED-first tests for write_claude_md.py.

Tests cover:
- IRON_LAWS list (5 items, contains L1-L5 keywords)
- render_stub_section_3 (5-line default)
- render_full_section_3 (4 sections: Tree, Manifest, Deps, Conventions)
- render_claude_md has §1 §2 §3 §4 §5
- write_claude_md atomic (no .tmp leftover)
- write_claude_md includes AUTO-GENERATED marker
"""
from __future__ import annotations

import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import write_claude_md  # noqa: E402


class TestWriteClaudeMd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_iron_laws_count_and_content(self):
        laws = write_claude_md.IRON_LAWS
        self.assertEqual(len(laws), 5)
        self.assertIn("verification artifact", laws[0])
        self.assertIn("reproducing", laws[1])
        self.assertIn("completion claim", laws[2])
        self.assertIn("TODO", laws[3])
        self.assertIn("option", laws[4])

    def test_render_stub_5_line(self):
        stub = write_claude_md.render_stub_section_3(self.root)
        # Default STUB is ~5-9 lines (1-line tree + opt-in marker)
        line_count = len([l for l in stub.split("\n") if l.strip()])
        self.assertLessEqual(line_count, 10)
        self.assertIn("--full-claude-md", stub)

    def test_render_full_section_3_has_4_sections(self):
        full = write_claude_md.render_full_section_3(self.root)
        for tag in ("### Tree", "### Manifest", "### External deps", "### Conventions"):
            self.assertIn(tag, full)

    def test_render_claude_md_has_all_9_sections(self):
        md = write_claude_md.render_claude_md(self.root)
        for section in ("§1", "§2", "§3", "§4", "§5"):
            self.assertIn(section, md)

    def test_render_claude_md_includes_iron_laws(self):
        md = write_claude_md.render_claude_md(self.root)
        for i in range(1, 6):
            self.assertIn(f"**L{i}**", md)

    def test_render_claude_md_with_overrides(self):
        md = write_claude_md.render_claude_md(self.root, stage="design", full_map=True)
        self.assertIn("current_stage: design", md)
        # Full map should NOT include opt-in marker
        self.assertNotIn("+codebase-map:full", md)

    def test_write_atomic(self):
        p = write_claude_md.write_claude_md(self.root, full_map=False, stage="plan")
        self.assertTrue(p.exists())
        content = p.read_text()
        self.assertIn("AUTO-GENERATED", content)
        self.assertIn("current_stage: plan", content)
        # No tmp leftover
        leftover = list(self.root.glob(".CLAUDE.md.*.tmp"))
        self.assertEqual(leftover, [])

    def test_write_overwrites_cleanly(self):
        write_claude_md.write_claude_md(self.root, stage="plan")
        write_claude_md.write_claude_md(self.root, stage="design")
        content = (self.root / "CLAUDE.md").read_text()
        self.assertIn("current_stage: design", content)
        self.assertNotIn("current_stage: plan", content.replace("current_stage: design", ""))


if __name__ == "__main__":
    unittest.main(verbosity=2)
