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
import tempfile
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

    def test_link_javascript_scheme_rejected(self):
        """`javascript:` href must NOT render as executable anchor.

        Reviewer finding (PR #319): HTML escape prevents attribute
        breakout but does not restrict URL scheme. A `javascript:`
        link is still a clickable executable link when the file is
        opened from `file://`. Render as escaped text instead.
        """
        out = rph.render_body("[open](javascript:alert(1))")
        # No executable anchor produced:
        self.assertNotIn("<a", out)
        # Label text + scheme text both survive (in the fallback format
        # `label (href)`):
        self.assertIn("open", out)
        self.assertIn("javascript:alert(1)", out)
        # Crucially, no executable href:
        self.assertNotIn('href="javascript:', out)

    def test_link_data_scheme_rejected(self):
        out = rph.render_body("[click](data:text/html,<script>alert(1)</script>)")
        self.assertNotIn("<a", out)
        self.assertNotIn('href="data:', out)

    def test_link_vbscript_scheme_rejected(self):
        out = rph.render_body("[click](vbscript:msgbox(1))")
        self.assertNotIn("<a", out)
        self.assertNotIn('href="vbscript:', out)

    def test_link_file_scheme_rejected(self):
        """file:// links are rejected: the proposal HTML is meant to be
        safe-to-open from file://, so allowing file: links would defeat that."""
        out = rph.render_body("[click](file:///etc/passwd)")
        self.assertNotIn('href="file:', out)

    def test_link_mailto_allowed(self):
        out = rph.render_body("[email](mailto:a@b.com)")
        self.assertIn('href="mailto:a@b.com"', out)

    def test_link_https_with_query_allowed(self):
        out = rph.render_body("[x](https://a.com/x?y=z&q=v)")
        self.assertIn('href="https://a.com/x?y=z&amp;q=v"', out)

    def test_link_relative_path_allowed(self):
        """A bare relative path is the way cross-document links work
        inside docs/proposals/&lt;main&gt;/ (e.g. `[label](protocol-layer.html)`,
        `[label](../&lt;other-main&gt;/...)`, `[label](./sibling.html)`).
        When the proposal HTML is opened from `file://`, those relative
        paths resolve to OTHER FILES on the local filesystem, not to
        `file://` URLs. They MUST render as `<a>` tags. The dangerous
        schemes (javascript:, data:, vbscript:, file:) are still
        rejected -- the allowlist is per-scheme, not per-href-shape.
        """
        # Bare sibling path
        out = rph.render_body("[protocol](protocol-layer.html)")
        self.assertIn('href="protocol-layer.html"', out)
        self.assertIn(">protocol</a>", out)
        # Parent-traversal
        out = rph.render_body("[up](../sibling.html)")
        self.assertIn('href="../sibling.html"', out)
        self.assertIn(">up</a>", out)
        # Current-dir prefix
        out = rph.render_body("[here](./sibling.html)")
        self.assertIn('href="./sibling.html"', out)
        self.assertIn(">here</a>", out)
        # Path-absolute
        out = rph.render_body("[abs](/docs/proposals/foo.html)")
        self.assertIn('href="/docs/proposals/foo.html"', out)
        self.assertIn(">abs</a>", out)

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
        path = SCRIPT_DIR.parent / "docs/proposals/harness-architecture/00-index.yaml"
        if not path.exists():
            self.skipTest("example file not present")
        html = rph.render_from_yaml(path.read_text(encoding="utf-8"))
        # Sanity: the 00-index page mentions its own title and at least one
        # sibling cross-reference -- confirms flat-filename layout is wired
        # up end-to-end and the bare `<sub>.html` refs are present.
        self.assertIn("Issue #280", html)
        self.assertIn('href="protocol-layer.html"', html)

    def test_render_is_deterministic_when_now_is_fixed(self):
        """Passing a fixed `now` makes render() deterministic so two
        back-to-back calls produce byte-identical output. Reviewer
        finding (PR #319 minor 3): the prior default of `datetime.now()`
        embedded wall-clock time in the footer.
        """
        text = "title: T\nstatus: draft\nsections: []\n"
        p = rph.parse_proposal_yaml(text)
        # Use a date that's clearly NOT today so the test is stable
        # regardless of when it runs (today is KST-dependent):
        FIXED = "1999-12-31"
        out1 = rph.render(p, now=FIXED)
        out2 = rph.render(p, now=FIXED)
        self.assertEqual(out1, out2)
        self.assertIn(FIXED, out1)
        # Default (now=None) embeds today's date — must differ from
        # the fixed date we passed:
        out3 = rph.render(p)
        self.assertNotEqual(out1, out3)

    def test_render_default_now_is_today(self):
        """Default `now=None` produces today's date in the footer."""
        import datetime as _dt
        text = "title: T\nstatus: draft\nsections: []\n"
        p = rph.parse_proposal_yaml(text)
        out = rph.render(p)
        today_kst = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=9))).strftime("%Y-%m-%d")
        self.assertIn(today_kst, out)


# ----- Per-topic directory layout (issue: proposal subdir refactor) ---------


class PerTopicLayoutTests(unittest.TestCase):
    """Cover the docs/proposals/<main>/<sub>.{yaml,html} layout.

    The renderer's CLI surfaces the two-level, flat-filename layout:
    - `_list_proposals(root)` returns `<main>/<sub>` slugs (one `/`
      separator) for every `<sub>.yaml` at the umbrella level, sorted
      by main then sub.
    - `_render_one(root, "<main>/<sub>")` reads `<main>/<sub>.yaml`
      and writes `<main>/<sub>.html`.
    - Path-traversal guard still holds for the new shape: anything not
      a single `<main>/<sub>` slug is rejected before filesystem touch.
    """

    def _make(self, root: Path, main: str, sub: str, body: str = "title: T\nstatus: draft\nsections: []\n") -> Path:
        main_dir = root / "docs" / "proposals" / main
        main_dir.mkdir(parents=True, exist_ok=True)
        (main_dir / f"{sub}.yaml").write_text(body, encoding="utf-8")
        return main_dir

    def test_list_proposals_returns_two_level_slugs_alphabetical(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for main, sub in [("z", "zebra"), ("a", "alpha"), ("a", "middle"),
                              ("a", "00-index"), ("m", "topic")]:
                self._make(root, main, sub)
            # Stash a stray dir under a valid umbrella (the old
            # one-level layout) -- must be skipped, not surfaced.
            (root / "docs" / "proposals" / "a" / "scratch").mkdir(parents=True)
            (root / "docs" / "proposals" / "a" / "scratch" / "notes.txt").write_text("x", encoding="utf-8")
            # Stash a flat file under proposals/ (pre-refactor legacy) --
            # must not surface as a topic.
            (root / "docs" / "proposals" / "00-legacy.yaml").write_text("legacy", encoding="utf-8")
            # Stash a stray umbrella dir with no sub-topics -- skipped.
            (root / "docs" / "proposals" / "empty-umbrella").mkdir(parents=True)
            topics = rph._list_proposals(root)
            self.assertEqual(
                topics,
                [
                    "a/00-index",
                    "a/alpha",
                    "a/middle",
                    "m/topic",
                    "z/zebra",
                ],
            )

    def test_list_proposals_empty_when_dir_missing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertEqual(rph._list_proposals(root), [])

    def test_render_one_writes_flat_filename(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._make(root, "main", "alpha")
            rc = rph._render_one(root, "main/alpha")
            self.assertEqual(rc, 0)
            out = root / "docs" / "proposals" / "main" / "alpha.html"
            self.assertTrue(out.is_file(), f"missing {out}")
            # The old `<sub>/index.html` shape MUST NOT exist.
            self.assertFalse(
                (root / "docs" / "proposals" / "main" / "alpha").exists(),
                f"stray sub-topic dir created: {root / 'docs/proposals/main/alpha'}",
            )
            self.assertIn("<h1>T</h1>", out.read_text(encoding="utf-8"))

    def test_render_one_source_not_found_reports_flat_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            rc = rph._render_one(root, "main/missing")
            self.assertEqual(rc, 1)
            # Re-run via subprocess for a clean stderr assertion -- the
            # function writes directly to sys.stderr at module level.
            import subprocess
            r = subprocess.run(
                [sys.executable, "-m", "lib.render_proposal_html",
                 "main/missing", "--project-root", str(root)],
                cwd=str(Path(__file__).parent.parent),
                env={**__import__("os").environ, "PYTHONPATH": str(Path(__file__).parent.parent)},
                capture_output=True, text=True, timeout=15,
            )
            self.assertEqual(r.returncode, 1)
            self.assertIn("main/missing.yaml", r.stderr)
            self.assertIn("main/missing", r.stderr)

    def test_render_one_rejects_invalid_two_level_slug(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # The two-level regex allows exactly one `/` with valid
            # kebab/snake on each side. Anything else is rejected.
            for bad in [
                "../escape",            # path traversal
                "no-slash",             # no `/` separator
                "main/",                # trailing slash
                "/main/sub",            # leading slash
                "main//sub",            # double slash
                "main/./sub",           # dot segment
                "main/../escape",       # traversal inside
                "main/sub/extra",       # too many levels
                "main/foo bar",         # space in sub
                "main/foo;rm",          # shell metachar
            ]:
                rc = rph._render_one(root, bad)
                self.assertEqual(rc, 1, f"bad topic {bad!r} should be rejected")
            # No proposal artifacts should have been created.
            proposals_dir = root / "docs" / "proposals"
            assert not proposals_dir.exists() or \
                list(proposals_dir.iterdir()) == [], \
                f"no proposal artifacts should be created for invalid slugs, found: {list(proposals_dir.iterdir()) if proposals_dir.exists() else 'nothing'}"

    def test_list_proposals_ignores_legacy_shapes(self):
        """The pre-refactor layouts (flat `<name>.yaml`, one-level
        `<name>/proposal.yaml`, and the intermediate two-level
        `<main>/<sub>/index.{yaml,html}`) MUST NOT surface as topics.
        This pins the flat-filename invariant against any future
        regression that re-introduces the old shapes."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "docs" / "proposals").mkdir(parents=True)
            # Flat file (pre-refactor #1)
            (root / "docs" / "proposals" / "00-index.yaml").write_text("legacy", encoding="utf-8")
            # One-level dir with the pre-refactor proposal.yaml name
            (root / "docs" / "proposals" / "old-shape").mkdir(parents=True)
            (root / "docs" / "proposals" / "old-shape" / "proposal.yaml").write_text("legacy", encoding="utf-8")
            # Two-level-with-index intermediate shape
            intermediate = root / "docs" / "proposals" / "intermediate" / "old-sub"
            intermediate.mkdir(parents=True)
            (intermediate / "index.yaml").write_text("legacy", encoding="utf-8")
            # Valid flat-filename two-level topic
            self._make(root, "real-main", "real-sub")
            topics = rph._list_proposals(root)
            self.assertEqual(topics, ["real-main/real-sub"])


# ----- Back-to-index nav (auto-detected when sibling 00-index exists) -------


class BackToIndexNavTests(unittest.TestCase):
    """The renderer's CLI auto-attaches a `<nav class="back-link">` to
    a sub-topic page when a sibling `00-index.yaml` exists in the same
    umbrella dir. The 00-index page itself gets no back link (it IS
    the index). The pure function `render()` is unchanged in
    behaviour unless `back_to_href=` is passed."""

    def _make(self, root: Path, main: str, sub: str, body: str = "title: T\nstatus: draft\nsections: []\n") -> None:
        main_dir = root / "docs" / "proposals" / main
        main_dir.mkdir(parents=True, exist_ok=True)
        (main_dir / f"{sub}.yaml").write_text(body, encoding="utf-8")

    def test_render_pure_function_no_nav_by_default(self):
        """`render(p)` with no kwargs emits no back-link nav (the pure
        function default; the CLI driver adds it via filesystem check)."""
        text = "title: T\nstatus: draft\nsections: []\n"
        p = rph.parse_proposal_yaml(text)
        html = rph.render(p)
        self.assertNotIn('class="back-link"', html)

    def test_render_pure_function_emits_nav_when_kwarg_set(self):
        text = "title: T\nstatus: draft\nsections: []\n"
        p = rph.parse_proposal_yaml(text)
        html = rph.render(p, back_to_href="00-index.html")
        self.assertIn('class="back-link"', html)
        self.assertIn('href="00-index.html"', html)
        # Default label = "00-index" (basename without .html)
        self.assertIn("← 00-index", html)

    def test_render_pure_function_custom_label(self):
        text = "title: T\nstatus: draft\nsections: []\n"
        p = rph.parse_proposal_yaml(text)
        html = rph.render(
            p, back_to_href="00-index.html", back_to_label="← Index"
        )
        self.assertIn("← Index", html)
        self.assertNotIn("← 00-index", html)

    def test_render_pure_function_href_escapes_quotes(self):
        """A `"` in the href must not break the attribute parse."""
        text = "title: T\nstatus: draft\nsections: []\n"
        p = rph.parse_proposal_yaml(text)
        html = rph.render(p, back_to_href='a"b.html')
        self.assertIn('href="a&quot;b.html"', html)

    def test_cli_subtopic_with_index_sibling_emits_back_link(self):
        """The CLI's auto-detect wires the back link when the umbrella
        contains both the current sub-topic AND a sibling `00-index.yaml`."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._make(root, "main", "00-index")
            self._make(root, "main", "alpha")
            rc = rph._render_one(root, "main/alpha")
            self.assertEqual(rc, 0)
            out = (root / "docs" / "proposals" / "main" / "alpha.html").read_text(
                encoding="utf-8"
            )
            self.assertIn('class="back-link"', out)
            self.assertIn('href="00-index.html"', out)
            self.assertIn("← 00-index", out)

    def test_cli_index_page_has_no_back_link(self):
        """The 00-index page is the navigation root; it does NOT need
        a back link to itself."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._make(root, "main", "00-index")
            rc = rph._render_one(root, "main/00-index")
            self.assertEqual(rc, 0)
            out = (root / "docs" / "proposals" / "main" / "00-index.html").read_text(
                encoding="utf-8"
            )
            # CSS class definitions for `.back-link` are present (in
            # INLINE_CSS) but the actual <nav> element is not.
            self.assertNotIn('<nav class="back-link">', out)
            self.assertNotIn("← 00-index", out)

    def test_cli_subtopic_without_index_sibling_has_no_back_link(self):
        """When the umbrella has no `00-index.yaml` (e.g. a single
        standalone proposal that doesn't need navigation), no back
        link is attached. The sub-topic renders standalone."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self._make(root, "main", "lone-sub")
            rc = rph._render_one(root, "main/lone-sub")
            self.assertEqual(rc, 0)
            out = (root / "docs" / "proposals" / "main" / "lone-sub.html").read_text(
                encoding="utf-8"
            )
            self.assertNotIn('<nav class="back-link">', out)


if __name__ == "__main__":
    unittest.main()
