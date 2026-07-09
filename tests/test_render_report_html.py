#!/usr/bin/env python3
"""test_render_report_html.py — pure-function tests for lib/render_report_html.py.

No network. No fixtures on disk. Inputs are constructed in-memory. The
contract under test: a single self-contained HTML string with inline
CSS, no <script> tag, defensive HTML escaping, and the right sections
present for each input shape.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "lib"))
import render_report_html  # type: ignore  # noqa: E402


# ---------- fixtures (strings, not files) ----------


EVAL_MIN = """# Eval Report -- agent-behavior (dev-harness-kit)
> Generated: 2026-07-09T00:00:00+0900

## Summary
- Total cases: 3
- OK: 1
- DRIFT_WARNING: 1
- ROT: 1
- SKIPPED: 0

## Per-Dimension Scores
### review (n=2, overall=8.5)

| Axis | Mean |
|---|---|
| `precision` | 9.0 |
| `recall` | 8.0 |

## Per-Case Results
- **OK** `review-01-clean` (dim=review) score=9.0 (precision=10.0, recall=8.0)
- **DRIFT_WARNING** `review-02-trap` (dim=review) score=7.0 (precision=7.0, recall=7.0)
- **ROT** `review-03-bug` (dim=review) score=4.0 (precision=4.0, recall=4.0)
"""

INSPECT_MIN = """# Code Health Inspection -- 2026-07-09 -- /repo

**Verdict:** Critical
**Coverage:** 50 files inspected -- 7 findings (3 HIGH, 2 MED, 2 LOW)
**Precision:** 6 verified -- 1 filtered as false positive

## HIGH (3)

- [HIGH | CONFIRMED] Unused helper `foo` -- src/a.py:42
  Dim: dead -- Confidence: high
  TL;DR: dead export
  Scenario: no caller in repo
  Fix: delete `foo`

- [HIGH | CONFIRMED] SQL injection -- src/db.py:88
  Dim: slop -- Confidence: high
  TL;DR: string concat in query
  Scenario: user input -> exec
  Fix: use parameterized query

- [HIGH | PLAUSIBLE] Interface with one implementer -- src/if.py:1
  Dim: overeng -- Confidence: medium
  TL;DR: unnecessary indirection
  Scenario: harder to read
  Fix: inline

## MED (2)

- [MED | CONFIRMED] Long function -- src/long.py:200
  Dim: smell -- Confidence: high
  TL;DR: 80-line method
  Scenario: high cyclomatic complexity
  Fix: extract

- [MED | CONFIRMED] Vague name `data` -- src/x.py:10
  Dim: cleancode -- Confidence: high
  TL;DR: `data` is not descriptive
  Scenario: future reader confused
  Fix: rename to `parsed_payload`

## LOW (2)

- [LOW | PLAUSIBLE] Stale comment -- src/y.py:5
  Dim: cleancode -- Confidence: low
  TL;DR: comment says X, code does Y
  Scenario: minor confusion
  Fix: update comment

- [LOW | PLAUSIBLE] Magic number 42 -- src/z.py:30
  Dim: cleancode -- Confidence: low
  TL;DR: literal without constant
  Scenario: hard to find all sites
  Fix: name a constant

## Per-dimension summary

| dim       | HIGH | MED | LOW |
|-----------|------|-----|-----|
| dead      |  1   |  0  |  0  |
| slop      |  1   |  0  |  0  |
| overeng   |  1   |  0  |  0  |
| smell     |  0   |  1  |  0  |
| cleancode |  0   |  1  |  2  |

## Notes

- scoped to src/
"""


# ---------- tests ----------


class TestRenderOutputShape(unittest.TestCase):
    def test_doctype_and_lang(self):
        out = render_report_html.render(EVAL_MIN, INSPECT_MIN)
        self.assertTrue(out.startswith("<!DOCTYPE html>"))
        self.assertIn('<html lang="en">', out)
        self.assertIn("</html>", out)

    def test_no_script_tag_anywhere(self):
        out = render_report_html.render(EVAL_MIN, INSPECT_MIN)
        # no <script> opening tag, no on*= handlers, no javascript: URLs
        self.assertNotIn("<script", out.lower())
        self.assertNotIn("javascript:", out.lower())
        self.assertNotIn("onload=", out.lower())
        self.assertNotIn("onerror=", out.lower())

    def test_inline_css_only_no_external_assets(self):
        out = render_report_html.render(EVAL_MIN, INSPECT_MIN)
        self.assertNotIn('<link rel="stylesheet"', out)
        self.assertNotIn('<link href=', out)
        self.assertNotIn('<img src="http', out)
        self.assertIn("<style>", out)
        self.assertIn("</style>", out)

    def test_html_escapes_user_content(self):
        # Plant an XSS-shaped string in a finding title.
        evil = INSPECT_MIN.replace(
            "Unused helper `foo`",
            "Evil <script>alert(1)</script> helper `foo`",
        )
        out = render_report_html.render(EVAL_MIN, evil)
        self.assertNotIn("<script>alert(1)</script>", out)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", out)


class TestEvalSection(unittest.TestCase):
    def test_summary_cards_present(self):
        out = render_report_html.render(EVAL_MIN, "")
        # cards show counts (1 OK, 1 DRIFT, 1 ROT, 0 SKIPPED) with verdict classes
        self.assertIn('class="value verdict-ok">1</div>', out)
        self.assertIn('class="value verdict-bad">1</div>', out)
        self.assertIn('class="value verdict-warn">1</div>', out)
        self.assertIn('class="value verdict-skip">0</div>', out)

    def test_per_dim_axes_with_bars(self):
        out = render_report_html.render(EVAL_MIN, "")
        self.assertIn("review", out)
        self.assertIn("precision", out)
        self.assertIn("recall", out)
        self.assertIn('class="bar"', out)

    def test_per_case_table(self):
        out = render_report_html.render(EVAL_MIN, "")
        self.assertIn("review-01-clean", out)
        self.assertIn("review-03-bug", out)
        self.assertIn("verdict-ok", out)
        self.assertIn("verdict-bad", out)


class TestInspectSection(unittest.TestCase):
    def test_verdict_chip(self):
        out = render_report_html.render("", INSPECT_MIN)
        self.assertIn("Critical", out)
        self.assertIn('class="verdict-bad"', out)

    def test_per_dim_table(self):
        out = render_report_html.render("", INSPECT_MIN)
        self.assertIn("dead", out)
        self.assertIn("overeng", out)
        self.assertIn("cleancode", out)

    def test_finding_blocks_have_severity_class(self):
        out = render_report_html.render("", INSPECT_MIN)
        self.assertIn("finding-high", out)
        self.assertIn("finding-med", out)
        self.assertIn("finding-low", out)

    def test_all_three_severity_sections_rendered(self):
        out = render_report_html.render("", INSPECT_MIN)
        self.assertIn("HIGH (3)", out)
        self.assertIn("MED (2)", out)
        self.assertIn("LOW (2)", out)

    def test_finding_fields_extracted(self):
        out = render_report_html.render("", INSPECT_MIN)
        self.assertIn("src/a.py:42", out)
        self.assertIn("delete `foo`", out)
        self.assertIn("TL;DR:", out)
        self.assertIn("Scenario:", out)
        self.assertIn("Fix:", out)


class TestMissingInputs(unittest.TestCase):
    def test_both_empty_returns_skeleton(self):
        out = render_report_html.render("", "")
        self.assertIn("<!DOCTYPE html>", out)
        self.assertIn("No eval report found", out)
        self.assertIn("No inspect report found", out)
        # missing banner is yellow-ish
        self.assertIn("missing", out.lower())

    def test_only_eval(self):
        out = render_report_html.render(EVAL_MIN, "")
        self.assertIn("review-01-clean", out)
        self.assertIn("No inspect report found", out)

    def test_only_inspect(self):
        out = render_report_html.render("", INSPECT_MIN)
        self.assertIn("Critical", out)
        self.assertIn("No eval report found", out)


class TestParserRobustness(unittest.TestCase):
    def test_section_parser_handles_missing_closing(self):
        sections = render_report_html._parse_sections("## foo\nbody\nmore body")
        self.assertIn("foo", sections)
        self.assertIn("body", sections["foo"])

    def test_section_parser_preserves_title(self):
        sections = render_report_html._parse_sections("# Title\n## foo\nbody")
        self.assertEqual(sections["_title"], "Title")
        self.assertEqual(sections["foo"], "body")

    def test_finding_parser_stops_at_next_bullet(self):
        findings = render_report_html._parse_inspect_findings(INSPECT_MIN.split("## HIGH (3)")[1])
        self.assertGreaterEqual(len(findings), 1)
        # First finding is the 'foo' one
        self.assertEqual("dead", findings[0]["Dim"])

    def test_per_dim_table_parser(self):
        rows = render_report_html._parse_inspect_per_dim_table(
            INSPECT_MIN.split("## Per-dimension summary")[1]
        )
        # Filter out the header row that might match loosely
        body_rows = [r for r in rows if r[0] not in ("dim", "---")]
        self.assertEqual(5, len(body_rows))
        self.assertEqual(("dead", 1, 0, 0), body_rows[0])

    def test_color_map_has_every_verdict(self):
        # If we add a new verdict type to either skill, the renderer's
        # VERDICT_CLASS dict must include it -- this test forces a
        # conscious decision to extend the map rather than silently
        # render uncolored.
        for v in ("OK", "DRIFT_WARNING", "ROT", "SKIPPED",
                  "Critical", "Major drift", "Minor drift", "Healthy"):
            self.assertIn(v, render_report_html.VERDICT_CLASS,
                          f"verdict {v!r} missing from VERDICT_CLASS")


if __name__ == "__main__":
    unittest.main(verbosity=2)
