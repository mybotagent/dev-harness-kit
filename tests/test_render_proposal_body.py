#!/usr/bin/env python3
"""
test_render_proposal_body.py — regression coverage for ``render_body``.

PR #494 review finding (🟡 minor #5): YAML block-scalar bullet lists with
continuation lines were rendering as a ``<ul>`` followed by stray ``<p>``
elements because the list collector only consumed lines starting with a
bullet marker. The renderer fix greedily consumes indented continuations
and the tests below pin that contract.
"""
from __future__ import annotations

import unittest

from lib.render_proposal_html import render_body


class TestRenderBody(unittest.TestCase):
    def test_unordered_list_with_indented_continuation_stays_in_li(self):
        """Indented continuations of a bullet item must live inside that
        bullet's ``<li>`` — NOT split out into a separate ``<p>``."""
        body = (
            "- **Swarm** (peer agents, shared memory, dynamic spawning) — no\n"
            "  task in this repo needs agent-to-agent coordination rather than\n"
            "  orchestrator-to-agent; adopting it imports \"coordination\n"
            "  thrashing\" risk for zero measured benefit.\n"
            "- **Debate** (same prompt to N agents, judge arbitrates) — useful\n"
            "  when ~2.5x cost buys multi-perspective validation.\n"
        )
        out = render_body(body)
        self.assertIn("<ul>", out)
        self.assertIn("</ul>", out)
        # Single open <ul> + single close </ul>: no parallel broken lists.
        self.assertEqual(out.count("<ul>"), 1, "regression: list split into multiple <ul>")
        self.assertEqual(out.count("</ul>"), 1)
        # Two <li> openers, two closers — one per item.
        self.assertEqual(out.count("<li>"), 2)
        self.assertEqual(out.count("</li>"), 2)
        # The continuation text must live inside the first <li>, not in
        # a sibling <p>.
        first_li = out.split("</li>")[0]
        self.assertIn("thrashing", first_li,
            "regression: continuation text split out of <li>")
        self.assertNotIn("<p>task in this repo", out,
            "regression: continuation wrapped in <p>")
        self.assertNotIn("<p>orchestrator-to-agent", out)

    def test_ordered_list_with_indented_continuation_stays_in_li(self):
        body = (
            "1. First decision\n"
            "   continued onto a second line.\n"
            "2. Second decision\n"
            "   also continued.\n"
        )
        out = render_body(body)
        self.assertEqual(out.count("<ol>"), 1)
        self.assertEqual(out.count("</ol>"), 1)
        self.assertEqual(out.count("<li>"), 2)
        first_li = out.split("</li>")[0]
        self.assertIn("continued onto a second line.", first_li)
        self.assertNotIn("<p>continued", out)

    def test_paragraph_after_list_is_not_absorbed(self):
        """Continuation stops at the first non-indented line — a paragraph
        after a list must remain a paragraph, not get absorbed into the
        last bullet's <li>.
        """
        body = (
            "- First bullet\n"
            "- Second bullet\n"
            "\n"
            "A separate paragraph that follows the list.\n"
        )
        out = render_body(body)
        self.assertIn("<ul>", out)
        self.assertIn("A separate paragraph", out)
        self.assertIn("<p>A separate paragraph", out)
        self.assertNotIn("First bullet</li><p>A separate paragraph",
            "regression: paragraph bled into last <li>")

    def test_plain_unordered_list_no_continuation_still_works(self):
        """Sanity: single-line bullet items with no continuation behave
        as before (no regression on the simple case)."""
        body = "- alpha\n- beta\n- gamma\n"
        out = render_body(body)
        self.assertEqual(out.count("<li>"), 3)
        self.assertIn("<ul>", out)
        self.assertNotIn("<p>", out)


if __name__ == "__main__":
    unittest.main()
