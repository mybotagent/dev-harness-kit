#!/usr/bin/env python3
"""
test_write_project_md.py — RED-first tests for write_project_md.py.

Tests cover:
- IRON_LAWS list (5 items, contains L1-L5 keywords)
- render_stub_section_3 = lazy-loading index (canonical file refs, no inline tree)
- render_codebase_map_doc = full 4-section map (Tree, Manifest, Deps, Conventions)
- render_claude_md has §1 §2 §3 §4 §5
- write_project_md atomic (no .tmp leftover)
- write_project_md includes AUTO-GENERATED marker
- write_project_md also writes AGENTS.md
- write_project_md(full_map=True) writes docs/CODEBASE-MAP.md
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

import write_project_md  # noqa: E402


class TestWriteProjectMd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_iron_laws_count_and_content(self):
        laws = write_project_md.IRON_LAWS
        self.assertEqual(len(laws), 5)
        self.assertIn("verification artifact", laws[0])
        self.assertIn("reproducing", laws[1])
        self.assertIn("completion claim", laws[2])
        self.assertIn("TODO", laws[3])
        self.assertIn("option", laws[4])

    def test_render_stub_is_lazy_loading_index(self):
        """§3 stub = canonical file refs + opt-in dump command. No inline tree."""
        stub = write_project_md.render_stub_section_3(self.root)
        # Canonical manifest refs
        self.assertIn("package.json", stub)
        self.assertIn("pyproject.toml", stub)
        # Canonical lockfile refs
        self.assertIn("pnpm-lock.yaml", stub)
        # Opt-in dump command
        self.assertIn("--full-claude-md", stub)
        self.assertIn("docs/CODEBASE-MAP.md", stub)
        # NO inline tree dump
        self.assertNotIn("### Tree (depth 4)", stub)
        self.assertNotIn("lib/{", stub)

    def test_render_codebase_map_doc_has_4_sections(self):
        full = write_project_md.render_codebase_map_doc(self.root)
        for tag in ("## Tree", "## Manifest", "## External deps", "## Conventions"):
            self.assertIn(tag, full)

    def test_render_claude_md_has_all_5_sections(self):
        md = write_project_md.render_claude_md(self.root)
        for section in ("§1", "§2", "§3", "§4", "§5"):
            self.assertIn(section, md)

    def test_render_claude_md_includes_iron_laws(self):
        md = write_project_md.render_claude_md(self.root)
        for i in range(1, 6):
            self.assertIn(f"**L{i}**", md)

    def test_render_claude_md_section_3_is_always_lazy(self):
        """§3 is the lazy-loading index regardless of full_map flag."""
        md_slim = write_project_md.render_claude_md(self.root, full_map=False)
        md_full = write_project_md.render_claude_md(self.root, full_map=True)
        for md in (md_slim, md_full):
            self.assertIn("lazy-loading index", md)
            self.assertNotIn("### Tree (depth 4)", md)
            self.assertIn("--full-claude-md", md)

    def test_render_claude_md_with_stage_override(self):
        md = write_project_md.render_claude_md(self.root, stage="design")
        self.assertIn("current_stage: design", md)

    def test_write_atomic(self):
        p = write_project_md.write_project_md(self.root, full_map=False, stage="plan")
        self.assertTrue(p.exists())
        content = p.read_text()
        self.assertIn("AUTO-GENERATED", content)
        self.assertIn("current_stage: plan", content)
        # No tmp leftover
        leftover = list(self.root.glob(".CLAUDE.md.*.tmp"))
        self.assertEqual(leftover, [])

    def test_write_also_writes_agents_md(self):
        write_project_md.write_project_md(self.root, stage="plan")
        agents_path = self.root / "AGENTS.md"
        self.assertTrue(agents_path.exists())
        self.assertTrue(agents_path.is_symlink())
        self.assertEqual(agents_path.readlink(), Path("CLAUDE.md"))
        self.assertEqual(agents_path.resolve(), (self.root / "CLAUDE.md").resolve())

    def test_write_full_map_writes_codebase_map_doc(self):
        write_project_md.write_project_md(self.root, full_map=True, stage="plan")
        doc_path = self.root / "docs" / "CODEBASE-MAP.md"
        self.assertTrue(doc_path.exists())
        content = doc_path.read_text()
        self.assertIn("## Tree", content)
        self.assertIn("## Manifest", content)
        # CLAUDE.md §3 must still be the lazy-loading index
        claude = (self.root / "CLAUDE.md").read_text()
        self.assertIn("lazy-loading index", claude)

    def test_write_default_skips_codebase_map_doc(self):
        write_project_md.write_project_md(self.root, full_map=False, stage="plan")
        doc_path = self.root / "docs" / "CODEBASE-MAP.md"
        self.assertFalse(doc_path.exists())

    def test_write_overwrites_cleanly(self):
        write_project_md.write_project_md(self.root, stage="plan")
        write_project_md.write_project_md(self.root, stage="design")
        content = (self.root / "CLAUDE.md").read_text()
        self.assertIn("current_stage: design", content)
        self.assertNotIn("current_stage: plan", content.replace("current_stage: design", ""))

    def test_codebase_map_doc_filters_credentials_and_dotfiles(self):
        """CODEBASE-MAP.md must not leak `.git/` or `x-access-token:...@` credentials."""
        # Create fake "credential" directory + .git file at root of tmp
        cred_dir = self.root / "https:"
        cred_dir.mkdir()
        (cred_dir / "x-access-token:fake-pat@github.com").mkdir()
        # Create a fake .git worktree-pointer file
        (self.root / ".git").write_text("gitdir: /tmp/fake/.git/worktrees/x")
        write_project_md.write_project_md(self.root, full_map=True, stage="plan")
        content = (self.root / "docs" / "CODEBASE-MAP.md").read_text()
        self.assertNotIn("x-access-token", content)
        self.assertNotIn("fake-pat", content)
        # .git as a top-level file should be filtered (worktree pointer)
        self.assertNotIn("\n  .git\n", content)
        self.assertNotIn("\n  .git/", content)

    def test_safe_deps_redacts_credentialed_registry_urls(self):
        """_safe_deps must redact x-access-token:...@ URLs in lockfile lines."""
        # Fake requirements.txt with a credentialed index URL
        (self.root / "requirements.txt").write_text(
            "# Sample lockfile\n"
            "--index-url https://x-access-token:fake-pat@pypi.example.com/simple\n"
            "requests==2.31.0\n"
        )
        out = write_project_md._safe_deps(self.root)
        self.assertNotIn("fake-pat", out)
        self.assertNotIn("x-access-token", out)
        self.assertIn("requests==2.31.0", out)

    # --- per-section helpers (issue #97) -------------------------------------

    def test_render_iron_laws_section(self):
        """_render_iron_laws(state) returns just §1 body (header + items)."""
        out = write_project_md._render_iron_laws(write_project_md.IRON_LAWS)
        self.assertIn("## §1 Iron Laws", out)
        self.assertIn("**L1**", out)
        self.assertIn("verification artifact", out)
        # No §2+ content
        self.assertNotIn("## §2", out)
        self.assertNotIn("## §3", out)

    def test_render_active_stage_section(self):
        """_render_active_stage(state) returns just §2 body."""
        out = write_project_md._render_active_stage(stage="build", step=2, methodology="tdd")
        self.assertIn("## §2 Active Stage", out)
        self.assertIn("current_stage: build", out)
        self.assertIn("current_step: 2", out)
        self.assertIn("methodology: tdd", out)
        # No §1 or §3+ content
        self.assertNotIn("## §1", out)
        self.assertNotIn("## §3", out)

    def test_render_active_stage_section_default_step(self):
        """Default step is 1/1, methodology tdd."""
        out = write_project_md._render_active_stage(stage="bootstrap")
        self.assertIn("current_step: 1/1", out)
        self.assertIn("shortcut_used: none", out)

    def test_render_codebase_map_index_section(self):
        """_render_codebase_map_index(root) returns just §3 lazy-loading body."""
        out = write_project_md._render_codebase_map_index(self.root)
        self.assertIn("## §3 Codebase Map", out)
        self.assertIn("lazy-loading index", out)
        self.assertIn("--full-claude-md", out)
        # No §2 or §4+ content
        self.assertNotIn("## §2", out)
        self.assertNotIn("## §4", out)

    def test_render_hook_matrix_section_default(self):
        """_render_hook_matrix() returns just §4 with the DEFAULT_MATRIX table."""
        out = write_project_md._render_hook_matrix()
        self.assertIn("## §4 Hook Matrix", out)
        self.assertIn("active-hooks.json", out)
        self.assertIn("tdd-guard", out)
        # No §3 or §5 content
        self.assertNotIn("## §3", out)
        self.assertNotIn("## §5", out)

    def test_render_hook_matrix_section_custom(self):
        """Custom hook matrix string passes through unchanged."""
        custom = "custom matrix body"
        out = write_project_md._render_hook_matrix(hook_matrix=custom)
        self.assertIn(custom, out)

    def test_render_handoff_section_default(self):
        """_render_handoff() returns just §5 with default hand-off pointer."""
        out = write_project_md._render_handoff()
        self.assertIn("## §5 Hand-off Pointer", out)
        self.assertIn("/dev-kit:plan", out)
        self.assertIn("/dev-kit:tdd-fast", out)
        # No §4 content
        self.assertNotIn("## §4", out)

    def test_render_handoff_section_custom(self):
        """Custom hand-off string passes through unchanged."""
        custom = "next_stage_trigger: /dev-kit:foo\nshortcut_trigger: /dev-kit:bar"
        out = write_project_md._render_handoff(hand_off_chain=custom)
        self.assertIn("/dev-kit:foo", out)
        self.assertIn("/dev-kit:bar", out)

    def test_render_claude_md_is_dispatcher(self):
        """render_claude_md body should be thin — under 30 lines of logic.

        Issue #97 acceptance: 'render_claude_md becomes a 5-line dispatcher.'
        """
        import inspect
        source = inspect.getsource(write_project_md.render_claude_md)
        # Count non-empty, non-comment lines
        logic_lines = [
            l for l in source.splitlines()
            if l.strip() and not l.strip().startswith("#")
        ]
        self.assertLess(len(logic_lines), 30, f"render_claude_md too long: {len(logic_lines)} lines\n{source}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
