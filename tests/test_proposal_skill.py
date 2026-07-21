"""test_proposal_skill.py -- regression tests for /dev-kit:proposal.

Pure-function tests for lib/render_proposal_html.py: parse_proposal_yaml,
render_body, render. Covers markdown-lite coverage, defensive HTML escape,
the no-script / inline-CSS-only invariants, and the forward-progress safety
that closes the infinite-loop bug (the `**bold**` at start-of-line case).

Mirrors tests/test_render_report_html.py's contract surface for the
sibling /dev-kit:report renderer.
"""
from __future__ import annotations

import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR.parent / "lib"))

import render_proposal_html as rph  # type: ignore  # noqa: E402

# ----- YAML parse -----------------------------------------------------------


class ParseYAMLTests(unittest.TestCase):
    def test_minimal_valid(self):
        p = rph.parse_proposal_yaml(
            "title: T\nstatus: draft\nsections:\n  - title: S\n    body: hi\n"
        )
        self.assertEqual(p.title, "T")
        self.assertEqual(p.status, "draft")
        self.assertIsNone(p.issue)
        self.assertEqual(p.date, "")
        self.assertEqual(p.tags, [])
        self.assertEqual(len(p.sections), 1)
        self.assertEqual(p.sections[0].title, "S")
        self.assertEqual(p.sections[0].body, "hi")

    def test_full_frontmatter(self):
        text = (
            "title: Harness\n"
            "status: design-discussion\n"
            "issue: 280\n"
            "date: 2026-07-21\n"
            "tags: [mcp, harness]\n"
            "sections:\n"
            "  - title: A\n"
            "    body: alpha\n"
        )
        p = rph.parse_proposal_yaml(text)
        self.assertEqual(p.issue, 280)
        self.assertEqual(p.date, "2026-07-21")
        self.assertEqual(p.tags, ["mcp", "harness"])
        self.assertEqual(p.status_class, "tag-info")

    def test_status_class_known_values(self):
        for status, expected in [
            ("draft", "tag-warn"),
            ("design-discussion", "tag-info"),
            ("ready-for-review", "tag-info"),
            ("accepted", "tag-ok"),
            ("rejected", "tag-bad"),
            ("superseded", "tag-warn"),
        ]:
            p = rph.parse_proposal_yaml(
                f"title: T\nstatus: {status}\nsections: []\n"
            )
            self.assertEqual(p.status_class, expected, f"status={status}")

    def test_status_class_unknown_falls_back_to_info(self):
        p = rph.parse_proposal_yaml(
            "title: T\nstatus: novel-state\nsections: []\n"
        )
        self.assertEqual(p.status_class, "tag-info")

    def test_missing_title_raises(self):
        with self.assertRaises(ValueError):
            rph.parse_proposal_yaml("status: draft\nsections: []\n")

    def test_non_mapping_top_level_raises(self):
        with self.assertRaises(ValueError):
            rph.parse_proposal_yaml("- a\n- b\n")

    def test_section_missing_title_raises(self):
        with self.assertRaises(ValueError):
            rph.parse_proposal_yaml(
                "title: T\nstatus: draft\nsections:\n  - body: no title\n"
            )

    def test_tags_must_be_list(self):
        with self.assertRaises(ValueError):
            rph.parse_proposal_yaml(
                "title: T\nstatus: draft\ntags: not-a-list\nsections: []\n"
            )


# ----- render_body (markdown-lite) ------------------------------------------


class RenderBodyTests(unittest.TestCase):
    def test_paragraph(self):
        out = rph.render_body("hello world")
        self.assertIn("<p>hello world</p>", out)

    def test_headings(self):
        out = rph.render_body("# h1\n\n## h2\n\n### h3")
        self.assertIn("<h1>h1</h1>", out)
        self.assertIn("<h2>h2</h2>", out)
        self.assertIn("<h3>h3</h3>", out)

    def test_bold_inline(self):
        out = rph.render_body("a **bold** word")
        self.assertIn("<strong>bold</strong>", out)

    def test_italic_inline(self):
        out = rph.render_body("a *italic* word")
        self.assertIn("<em>italic</em>", out)

    def test_code_inline(self):
        out = rph.render_body("run `ls -la` here")
        self.assertIn("<code>ls -la</code>", out)

    def test_link_inline(self):
        out = rph.render_body("see [the issue](https://example.com/280)")
        self.assertIn('href="https://example.com/280"', out)
        self.assertIn(">the issue</a>", out)

    def test_unordered_list(self):
        out = rph.render_body("- one\n- two\n- three")
        self.assertIn("<ul>", out)
        self.assertIn("<li>one</li>", out)
        self.assertIn("<li>two</li>", out)
        self.assertIn("<li>three</li>", out)
        self.assertIn("</ul>", out)

    def test_ordered_list(self):
        out = rph.render_body("1. one\n2. two\n3. three")
        self.assertIn("<ol>", out)
        self.assertIn("<li>one</li>", out)
        self.assertIn("<li>three</li>", out)

    def test_table(self):
        body = (
            "| Loop | Fit |\n"
            "|------|-----|\n"
            "| Validation | High |\n"
            "| Research | High |\n"
        )
        out = rph.render_body(body)
        self.assertIn("<table>", out)
        self.assertIn("<th>Loop</th>", out)
        self.assertIn("<th>Fit</th>", out)
        self.assertIn("<td>Validation</td>", out)
        self.assertIn("<td>High</td>", out)
        self.assertIn("</table>", out)

    def test_fenced_code_block(self):
        out = rph.render_body("```bash\necho hi\n```")
        self.assertIn("<pre>", out)
        self.assertIn("<code", out)
        self.assertIn("echo hi", out)
        self.assertIn("</code></pre>", out)

    def test_blockquote(self):
        out = rph.render_body("> quoted line")
        self.assertIn("<blockquote>", out)
        self.assertIn("quoted line", out)
        self.assertIn("</blockquote>", out)

    def test_horizontal_rule(self):
        out = rph.render_body("above\n\n---\n\nbelow")
        self.assertIn('<hr class="section-divider">', out)

    def test_bold_at_start_of_line_is_inline_not_block(self):
        """Regression: `**Pick rule of thumb**:` at the start of a line
        was being treated as a block start, causing render_body to loop
        infinitely. This must render as a paragraph with inline bold."""
        out = rph.render_body(
            "**Pick rule of thumb**: reach for MCP when the loop crosses actor boundaries."
        )
        self.assertIn("<p>", out)
        self.assertIn("<strong>Pick rule of thumb</strong>", out)
        # Must terminate (forward-progress safety; loop bug would hang).
        self.assertIsInstance(out, str)

    def test_paragraph_terminates(self):
        """Forward-progress safety: any input must terminate."""
        # The previous bug hung the parser indefinitely.
        # We assert termination by timing out if render_body exceeds 1s.
        import signal

        def handler(signum, frame):
            raise TimeoutError("render_body did not terminate")

        signal.signal(signal.SIGALRM, handler)
        signal.alarm(1)
        try:
            for body in [
                "**bold at start**",
                "*italic at start*",
                "# heading then paragraph\n\n**inline bold** paragraph",
                "- list item\n\n**inline** between",
                "para with `code` and **bold**",
            ]:
                rph.render_body(body)
        finally:
            signal.alarm(0)


# ----- Defensive HTML escape (Iron Law) ------------------------------------


class HtmlEscapeTests(unittest.TestCase):
    def test_script_in_title_escaped(self):
        text = (
            "title: <script>alert(1)</script>\n"
            "status: draft\nsections: []\n"
        )
        p = rph.parse_proposal_yaml(text)
        html = rph.render(p)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_script_in_body_escaped(self):
        body = "hello <script>evil()</script> world"
        out = rph.render_body(body)
        self.assertNotIn("<script>evil()</script>", out)
        self.assertIn("&lt;script&gt;evil()&lt;/script&gt;", out)

    def test_link_href_escapes_quotes(self):
        body = '[click](javascript:alert("x"))'
        out = rph.render_body(body)
        # The href attribute value must be HTML-escaped; the literal JS
        # must not survive unescaped inside an attribute.
        self.assertNotIn('href="javascript:alert("x")"', out)

    def test_ampersand_escaped(self):
        out = rph.render_body("AT&T and &amp;already")
        self.assertIn("AT&amp;T", out)
        self.assertIn("&amp;amp;already", out)  # double-escape is correct

    def test_less_than_greater_than_escaped(self):
        out = rph.render_body("a < b > c")
        self.assertIn("a &lt; b &gt; c", out)


# ----- Output invariants ----------------------------------------------------


class OutputInvariantsTests(unittest.TestCase):
    def _render_full(self):
        text = (
            "title: T\nstatus: draft\nsections:\n  - title: S\n    body: hi\n"
        )
        return rph.render_from_yaml(text)

    def test_no_script_tag_in_output(self):
        html = self._render_full()
        self.assertNotIn("<script", html)

    def test_no_link_stylesheet_in_output(self):
        html = self._render_full()
        self.assertNotIn('rel="stylesheet"', html)

    def test_no_remote_img_in_output(self):
        html = self._render_full()
        self.assertNotIn('src="http', html)

    def test_dark_mode_block_present(self):
        html = self._render_full()
        self.assertIn("prefers-color-scheme: dark", html)

    def test_output_is_well_formed_html(self):
        html = self._render_full()

        class _P(HTMLParser):
            def __init__(self):
                super().__init__()
                self.stack: list[str] = []
                self.errors: list[str] = []

            def handle_starttag(self, tag, attrs):
                if tag not in ("br", "meta", "link", "img", "hr", "input"):
                    self.stack.append(tag)

            def handle_endtag(self, tag):
                if not self.stack:
                    self.errors.append(f"close {tag} with empty stack")
                    return
                if self.stack[-1] != tag:
                    self.errors.append(
                        f"mismatch: open={self.stack[-1]} close={tag}"
                    )
                else:
                    self.stack.pop()

        p = _P()
        p.feed(html)
        self.assertEqual(p.errors, [], f"HTML errors: {p.errors}")
        self.assertEqual(p.stack, [], f"unclosed tags: {p.stack}")

    def test_frontmatter_renders_into_meta(self):
        text = (
            "title: T\nstatus: design-discussion\nissue: 280\n"
            "date: 2026-07-21\ntags: [mcp, harness]\n"
            "sections:\n  - title: S\n    body: hi\n"
        )
        html = rph.render_from_yaml(text)
        self.assertIn("2026-07-21", html)
        self.assertIn("issue #280", html)
        self.assertIn("design-discussion", html)
        self.assertIn("mcp", html)
        self.assertIn("harness", html)


# ----- Top-level render + real example --------------------------------------


class RenderFromYamlTests(unittest.TestCase):
    def test_empty_sections_still_renders(self):
        text = "title: T\nstatus: draft\nsections: []\n"
        html = rph.render_from_yaml(text)
        self.assertIn("<h1>T</h1>", html)

    def test_example_file_renders(self):
        path = SCRIPT_DIR.parent / "docs/proposals/harness-architecture.yaml"
        if not path.exists():
            self.skipTest("example file not present")
        html = rph.render_from_yaml(path.read_text(encoding="utf-8"))
        self.assertIn("Harness Architecture Proposal", html)
        self.assertIn("When MCP harness is most needed", html)
        # Each section title must appear as a heading.
        for title in [
            "TL;DR",
            "MCP vs document harness",
            "Hackathon principles mapped to dev-harness-kit",
            "Strategic direction",
            "Recommendation",
            "Open questions",
        ]:
            self.assertIn(title, html, f"missing section: {title}")


if __name__ == "__main__":
    unittest.main()
