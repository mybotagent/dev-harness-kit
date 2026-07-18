#!/usr/bin/env python3
"""test_analysis_core_runner.py — End-to-end on a tiny synthetic repo.

Builds a 3-file synthetic repo, runs the engine with a synthetic
candidate stream, and asserts:

  - the engine resolves the right dimensions for each mode
  - candidate JSON parses into Evidence
  - the FP filter pipeline drops/retains as expected
  - the renderer produces stable markdown with the per-dim summary
  - the diff emitter emits `rm` for delete mode and a `# rewrite:`
    header for rewrite mode
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lib.analysis_core import (  # noqa: E402
    run_analysis,
    render_markdown,
    emit_suggested_diffs,
    group,
    Severity,
    Evidence,
)


def _build_synth_repo() -> Path:
    """Create a tiny 3-file repo. Returns the tmp dir."""
    tmp = tempfile.mkdtemp(prefix="ac-synth-")
    root = Path(tmp)
    (root / "a.py").write_text(
        "def add(a, b):\n"
        "    return a + b\n",
        encoding="utf-8",
    )
    (root / "b.py").write_text(
        "def add(a, b):  # dup\n"
        "    return a + b\n",
        encoding="utf-8",
    )
    (root / "c.py").write_text(
        "import os\n"
        "x = os.environ.get('X')\n",
        encoding="utf-8",
    )
    return root


class TestRunAnalysis(unittest.TestCase):
    def test_run_analysis_review_keeps_real_finds(self):
        """Review-mode run on a synthetic repo with realistic candidate stream."""
        repo = _build_synth_repo()
        candidates = {
            "correctness": [
                {
                    "file": str(repo / "a.py"),
                    "line": 1,
                    "severity": "major",
                    "confidence": "high",
                    "title": "missing input validation",
                    "tldr": "add() does not check types",
                    "failure_scenario": "add(1, 'x') raises TypeError",
                    "fix_hint": "guard with isinstance",
                },
            ],
            "security": [
                {
                    "file": str(repo / "c.py"),
                    "line": 2,
                    "severity": "critical",
                    "confidence": "high",
                    "title": "insecure env read",
                    "tldr": "no secret filter",
                    "failure_scenario": "leaks X in logs",
                },
            ],
            "architecture": [],
        }
        result = run_analysis(
            dimensions=group("review"),
            mode="read-only",
            paths=[repo],
            candidates=candidates,
        )
        self.assertEqual(result.kept_count, 2)
        self.assertEqual(result.filtered_count, 0)
        self.assertEqual(len(result.findings), 2)
        severities = [f.severity for f in result.findings]
        self.assertEqual(
            sorted(severities, key=lambda s: s.value),
            sorted([Severity.CRITICAL, Severity.MAJOR], key=lambda s: s.value),
        )

    def test_run_analysis_filters_missing_failure_scenario(self):
        repo = _build_synth_repo()
        candidates = {
            "correctness": [
                {
                    "file": str(repo / "a.py"),
                    "line": 1,
                    "severity": "major",
                    "confidence": "high",
                    "title": "speculative",
                    "tldr": "maybe",
                    "failure_scenario": "",  # empty → drop
                },
            ],
        }
        result = run_analysis(
            dimensions=["correctness"],
            mode="read-only",
            paths=[repo],
            candidates=candidates,
        )
        self.assertEqual(result.kept_count, 0)
        self.assertGreaterEqual(result.filtered_count, 1)

    def test_run_analysis_delete_drops_nits(self):
        repo = _build_synth_repo()
        candidates = {
            "dead": [
                {
                    "file": str(repo / "b.py"),
                    "line": 1,
                    "severity": "nit",
                    "confidence": "medium",
                    "title": "unused",
                    "tldr": "trivia",
                    "failure_scenario": "no callers",
                    "fix_hint": "rm b.py",
                },
            ],
        }
        result = run_analysis(
            dimensions=["dead"],
            mode="delete",
            paths=[repo],
            candidates=candidates,
        )
        self.assertEqual(result.kept_count, 0)

    def test_run_analysis_unknown_dimension_raises(self):
        with self.assertRaises(KeyError):
            run_analysis(
                dimensions=["not-a-dim"],
                mode="read-only",
                paths=[],
                candidates={},
            )


class TestRenderMarkdown(unittest.TestCase):
    def test_markdown_contains_per_dim_summary(self):
        repo = _build_synth_repo()
        candidates = {
            "correctness": [
                {
                    "file": str(repo / "a.py"),
                    "line": 1,
                    "severity": "major",
                    "confidence": "high",
                    "title": "missing guard",
                    "tldr": "no type check",
                    "failure_scenario": "bad input crashes",
                },
            ],
        }
        result = run_analysis(
            dimensions=["correctness"],
            mode="read-only",
            paths=[repo],
            candidates=candidates,
        )
        md = render_markdown(result)
        self.assertIn("# Analysis Report", md)
        self.assertIn("correctness", md)
        self.assertIn("missing guard", md)
        self.assertIn("Verdict:", md)

    def test_empty_findings_renders_clean(self):
        repo = _build_synth_repo()
        result = run_analysis(
            dimensions=["correctness"],
            mode="read-only",
            paths=[repo],
            candidates={"correctness": []},
        )
        md = render_markdown(result)
        self.assertIn("Verdict:", md)
        self.assertIn("Healthy", md)


class TestEmitSuggestedDiffs(unittest.TestCase):
    def test_delete_mode_emits_rm(self):
        repo = _build_synth_repo()
        candidates = {
            "dead": [
                {
                    "file": str(repo / "a.py"),
                    "line": 1,
                    "severity": "major",
                    "confidence": "high",
                    "title": "unused file",
                    "tldr": "no importers",
                    "failure_scenario": "no callers",
                    "fix_hint": "rm a.py",
                },
            ],
        }
        result = run_analysis(
            dimensions=["dead"],
            mode="delete",
            paths=[repo],
            candidates=candidates,
        )
        diffs = emit_suggested_diffs(result)
        self.assertEqual(len(diffs), 1)
        self.assertIn("rm ", diffs[0].command)

    def test_rewrite_mode_emits_header(self):
        repo = _build_synth_repo()
        candidates = {
            "smell": [
                {
                    "file": str(repo / "c.py"),
                    "line": 1,
                    "severity": "major",
                    "confidence": "high",
                    "title": "long method",
                    "tldr": "too big",
                    "failure_scenario": "unmaintainable",
                    "fix_hint": "split into helpers",
                },
            ],
        }
        result = run_analysis(
            dimensions=["smell"],
            mode="rewrite",
            paths=[repo],
            candidates=candidates,
        )
        diffs = emit_suggested_diffs(result)
        self.assertEqual(len(diffs), 1)
        self.assertIn("# rewrite:", diffs[0].command)

    def test_read_only_emits_no_command(self):
        repo = _build_synth_repo()
        candidates = {
            "correctness": [
                {
                    "file": str(repo / "a.py"),
                    "line": 1,
                    "severity": "major",
                    "confidence": "high",
                    "title": "x",
                    "tldr": "y",
                    "failure_scenario": "z",
                },
            ],
        }
        result = run_analysis(
            dimensions=["correctness"],
            mode="read-only",
            paths=[repo],
            candidates=candidates,
        )
        self.assertEqual(emit_suggested_diffs(result), [])


class TestDeterministicEndToEnd(unittest.TestCase):
    """Two runs with identical inputs MUST produce identical outputs."""

    def test_repeatable_output(self):
        repo = _build_synth_repo()
        candidates = {
            "correctness": [
                {
                    "file": str(repo / "a.py"),
                    "line": 1,
                    "severity": "major",
                    "confidence": "high",
                    "title": "x",
                    "tldr": "y",
                    "failure_scenario": "z",
                },
            ],
        }
        r1 = run_analysis(
            dimensions=["correctness"],
            mode="read-only",
            paths=[repo],
            candidates=candidates,
        )
        r2 = run_analysis(
            dimensions=["correctness"],
            mode="read-only",
            paths=[repo],
            candidates=candidates,
        )
        self.assertEqual(render_markdown(r1), render_markdown(r2))


class TestScopeEnforcement(unittest.TestCase):
    """`paths` is a real scope filter — out-of-scope findings must not
    reach the dedupe pipeline or the mutation emitter.
    """

    def test_out_of_scope_finding_dropped(self):
        repo = _build_synth_repo()
        candidates = {
            "dead": [
                {
                    "file": "/some/other/path/elsewhere.py",
                    "line": 1,
                    "severity": "major",
                    "confidence": "high",
                    "title": "out of scope",
                    "tldr": "x",
                    "failure_scenario": "y",
                },
            ],
        }
        result = run_analysis(
            dimensions=["dead"],
            mode="read-only",
            paths=[repo],
            candidates=candidates,
        )
        self.assertEqual(result.kept_count, 0)

    def test_in_scope_finding_kept(self):
        repo = _build_synth_repo()
        candidates = {
            "dead": [
                {
                    "file": str(repo / "a.py"),
                    "line": 1,
                    "severity": "major",
                    "confidence": "high",
                    "title": "in scope",
                    "tldr": "x",
                    "failure_scenario": "y",
                },
            ],
        }
        result = run_analysis(
            dimensions=["dead"],
            mode="read-only",
            paths=[repo],
            candidates=candidates,
        )
        self.assertEqual(result.kept_count, 1)


class TestPerDimModeRespect(unittest.TestCase):
    """`emit_suggested_diffs` MUST skip dims whose `Dimension.mode`
    doesn't match the requested mutation mode. Otherwise a refactor
    smell would surface as `git rm` and destroy a valid source file.
    """

    def test_rewrite_only_dim_skipped_in_delete_mode(self):
        repo = _build_synth_repo()
        # 'smell' has mode='rewrite'. In delete mode it must NOT emit git rm.
        candidates = {
            "smell": [
                {
                    "file": str(repo / "a.py"),
                    "line": 1,
                    "severity": "major",
                    "confidence": "high",
                    "title": "long method",
                    "tldr": "too big",
                    "failure_scenario": "unmaintainable",
                    "fix_hint": "extract helper",
                },
            ],
        }
        result = run_analysis(
            dimensions=["smell"],
            mode="delete",
            paths=[repo],
            candidates=candidates,
        )
        diffs = emit_suggested_diffs(result)
        self.assertEqual(diffs, [])

    def test_delete_dim_emits_git_rm_in_delete_mode(self):
        repo = _build_synth_repo()
        # 'dead' has mode='delete'. In delete mode it MUST emit git rm.
        candidates = {
            "dead": [
                {
                    "file": str(repo / "b.py"),
                    "line": 1,
                    "severity": "major",
                    "confidence": "high",
                    "title": "unused",
                    "tldr": "no importers",
                    "failure_scenario": "no callers",
                    "fix_hint": "rm b.py",
                },
            ],
        }
        result = run_analysis(
            dimensions=["dead"],
            mode="delete",
            paths=[repo],
            candidates=candidates,
        )
        diffs = emit_suggested_diffs(result)
        self.assertEqual(len(diffs), 1)
        self.assertIn("git rm", diffs[0].command)


class TestMarkdownFormatCompatibility(unittest.TestCase):
    """`render_markdown` MUST emit bullets that
    `lib/render_report_html._parse_inspect_findings` can consume.
    Otherwise the HTML report silently drops findings.
    """

    def test_bullets_match_report_parser(self):
        repo = _build_synth_repo()
        candidates = {
            "dead": [
                {
                    "file": str(repo / "a.py"),
                    "line": 1,
                    "severity": "critical",
                    "confidence": "high",
                    "title": "unused module",
                    "tldr": "no importers",
                    "failure_scenario": "no callers",
                    "fix_hint": "rm a.py",
                },
            ],
        }
        result = run_analysis(
            dimensions=["dead"],
            mode="read-only",
            paths=[repo],
            candidates=candidates,
        )
        md = render_markdown(result)
        from lib.render_report_html import _parse_inspect_findings
        # Section header shape is HIGH/MED/LOW (N) — matches the
        # dispatch keys in lib/render_report_html.py:387-393.
        body_start = md.find("## HIGH (")
        self.assertNotEqual(body_start, -1, "missing '## HIGH (N)' section header")
        body = md[body_start:]
        parsed = _parse_inspect_findings(body)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["severity"], "CRITICAL")
        self.assertEqual(parsed[0]["confidence"], "HIGH")
        self.assertEqual(parsed[0]["title"], "unused module")
        self.assertEqual(parsed[0]["Dim"], "dead")

    def test_field_keys_match_report_parser(self):
        repo = _build_synth_repo()
        candidates = {
            "dead": [
                {
                    "file": str(repo / "a.py"),
                    "line": 1,
                    "severity": "major",
                    "confidence": "high",
                    "title": "x",
                    "tldr": "tl",
                    "failure_scenario": "sc",
                    "fix_hint": "fh",
                },
            ],
        }
        md = render_markdown(run_analysis(
            dimensions=["dead"],
            mode="read-only",
            paths=[repo],
            candidates=candidates,
        ))
        # Each known field key must appear in the report body.
        for key in ("Dim", "TL;DR", "Scenario", "Fix"):
            self.assertIn(f"{key}:", md, f"missing field key: {key}")

    def test_findings_bucketed_into_high_med_low(self):
        # Sections are emitted so the HTML consumer's dispatch at
        # lib/render_report_html.py:387-393 can route every block.
        repo = _build_synth_repo()
        candidates = {
            "dead": [
                {"file": str(repo / "a.py"), "line": 1,
                 "severity": "critical", "confidence": "high",
                 "title": "h", "tldr": "t", "failure_scenario": "s"},
                {"file": str(repo / "b.py"), "line": 1,
                 "severity": "minor", "confidence": "high",
                 "title": "m", "tldr": "t", "failure_scenario": "s"},
                {"file": str(repo / "c.py"), "line": 1,
                 "severity": "nit", "confidence": "high",
                 "title": "l", "tldr": "t", "failure_scenario": "s"},
            ],
        }
        md = render_markdown(run_analysis(
            dimensions=["dead"],
            mode="read-only",
            paths=[repo],
            candidates=candidates,
        ))
        self.assertIn("## HIGH (1)", md)
        self.assertIn("## MED (1)", md)
        self.assertIn("## LOW (1)", md)

    def test_end_to_end_html_render_includes_findings(self):
        # Integration test: drive render_report_html.render directly so
        # the section-header → dispatch → HTML pipeline is exercised.
        # This locks in the fix for finding #5 (silently dropped
        # findings in /dev-kit:report output).
        repo = _build_synth_repo()
        candidates = {
            "dead": [
                {
                    "file": str(repo / "a.py"),
                    "line": 1,
                    "severity": "critical",
                    "confidence": "high",
                    "title": "unused module",
                    "tldr": "no importers",
                    "failure_scenario": "no callers",
                },
            ],
        }
        md = render_markdown(run_analysis(
            dimensions=["dead"],
            mode="read-only",
            paths=[repo],
            candidates=candidates,
        ))
        from lib.render_report_html import render as render_html
        html = render_html("", md)
        self.assertIn("unused module", html)
        self.assertIn("CRITICAL", html)
        self.assertIn("finding", html.lower())


class TestSecretMasking(unittest.TestCase):
    """Secret-dim free-text MUST be masked at the engine boundary."""

    def test_aws_key_masked_in_markdown(self):
        repo = _build_synth_repo()
        candidates = {
            "secret": [
                {
                    "file": str(repo / "a.py"),
                    "line": 1,
                    "severity": "critical",
                    "confidence": "high",
                    "title": "AWS key leaked",
                    "tldr": "t",
                    "failure_scenario": "found AKIAIOSFODNN7EXAMPLE in env",
                    "fix_hint": "rotate AKIAIOSFODNN7EXAMPLE",
                },
            ],
        }
        result = run_analysis(
            dimensions=["secret"],
            mode="read-only",
            paths=[repo],
            candidates=candidates,
        )
        md = render_markdown(result)
        self.assertNotIn("AKIAIOSFODNN7EXAMPLE", md)
        self.assertIn("[REDACTED]", md)

    def test_gcp_key_masked_in_markdown(self):
        repo = _build_synth_repo()
        candidates = {
            "secret": [
                {
                    "file": str(repo / "a.py"),
                    "line": 1,
                    "severity": "major",
                    "confidence": "high",
                    "title": "GCP key",
                    "tldr": "t",
                    "failure_scenario": "AIzaSyA-aBcDeFgHiJkLmNoPqRsTuVwXyZ01234 leaked",
                },
            ],
        }
        md = render_markdown(run_analysis(
            dimensions=["secret"],
            mode="read-only",
            paths=[repo],
            candidates=candidates,
        ))
        self.assertNotIn("AIzaSyA-aBcDeFgHiJkLmNoPqRsTuVwXyZ01234", md)
        self.assertIn("[REDACTED]", md)

    def test_secret_in_suggested_diff_path_masked(self):
        repo = _build_synth_repo()
        # secret-dim finding whose file path embeds a key
        candidates = {
            "secret": [
                {
                    "file": "/tmp/AKIAIOSFODNN7EXAMPLE-leak.log",
                    "line": 1,
                    "severity": "major",
                    "confidence": "high",
                    "title": "leak file",
                    "tldr": "t",
                    "failure_scenario": "x",
                },
            ],
        }
        # No scope match → out of scope, so this should be dropped.
        # Use a real path under repo to exercise diff path masking.
        secret_file = repo / "AKIAIOSFODNN7EXAMPLE.log"
        secret_file.write_text("x")
        candidates["secret"][0]["file"] = str(secret_file)
        result = run_analysis(
            dimensions=["secret"],
            mode="delete",
            paths=[repo],
            candidates=candidates,
        )
        diffs = emit_suggested_diffs(result)
        # secret dim has mode=read-only → no diff emitted (correct)
        self.assertEqual(diffs, [])

    def test_anthropic_sk_ant_key_masked(self):
        from lib.analysis_core.runner import _mask_secrets
        self.assertNotIn(
            "sk-ant-abcdefghijklmnopqrstuvwxyz123456",
            _mask_secrets("found sk-ant-abcdefghijklmnopqrstuvwxyz123456 in env"),
        )

    def test_github_oauth_token_masked(self):
        from lib.analysis_core.runner import _mask_secrets
        self.assertNotIn(
            "gho_abcdefghijklmnopqrstuvwxyz0123456789AB",
            _mask_secrets("token=gho_abcdefghijklmnopqrstuvwxyz0123456789AB"),
        )

    def test_pem_private_key_block_masked(self):
        from lib.analysis_core.runner import _mask_secrets
        pem = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEAxxxx...\n"
            "-----END RSA PRIVATE KEY-----"
        )
        masked = _mask_secrets(pem)
        self.assertNotIn("BEGIN RSA PRIVATE KEY", masked)
        self.assertIn("[REDACTED]", masked)

    def test_postgres_credential_uri_masked(self):
        from lib.analysis_core.runner import _mask_secrets
        uri = "postgres://user:pass@host:5432/db"
        masked = _mask_secrets(uri)
        self.assertNotIn(uri, masked)
        self.assertIn("[REDACTED]", masked)

    def test_mongodb_credential_uri_masked(self):
        from lib.analysis_core.runner import _mask_secrets
        uri = "mongodb+srv://user:pass@cluster.example.net/db"
        masked = _mask_secrets(uri)
        self.assertNotIn(uri, masked)
        self.assertIn("[REDACTED]", masked)

    def test_secret_path_masked_in_markdown_bullet(self):
        # f.file goes through _mask_secrets in render_markdown so a
        # secret-shaped path cannot leak through the bullet line.
        repo = _build_synth_repo()
        secret_path = repo / "sk-ant-abcdefghijklmnopqrstuvwxyz123456.log"
        secret_path.write_text("x")
        candidates = {
            "secret": [
                {
                    "file": str(secret_path),
                    "line": 1,
                    "severity": "critical",
                    "confidence": "high",
                    "title": "x",
                    "tldr": "t",
                    "failure_scenario": "y",
                },
            ],
        }
        md = render_markdown(run_analysis(
            dimensions=["secret"],
            mode="read-only",
            paths=[repo],
            candidates=candidates,
        ))
        self.assertNotIn("sk-ant-abcdefghijklmnopqrstuvwxyz123456", md)
        self.assertIn("[REDACTED]", md)

    def test_delete_mode_diff_file_is_masked(self):
        # SuggestedDiff.file in delete mode must also be masked.
        # Use a delete-mode-supported dim so we actually get a diff.
        repo = _build_synth_repo()
        secret_path = repo / "gho_abcdefghijklmnopqrstuvwxyz0123456789AB.log"
        secret_path.write_text("x")
        candidates = {
            "dead": [
                {
                    "file": str(secret_path),
                    "line": 1,
                    "severity": "major",
                    "confidence": "high",
                    "title": "unused",
                    "tldr": "t",
                    "failure_scenario": "y",
                },
            ],
        }
        result = run_analysis(
            dimensions=["dead"],
            mode="delete",
            paths=[repo],
            candidates=candidates,
        )
        diffs = emit_suggested_diffs(result)
        self.assertEqual(len(diffs), 1)
        self.assertNotIn(
            "gho_abcdefghijklmnopqrstuvwxyz0123456789AB", diffs[0].file
        )
        self.assertNotIn(
            "gho_abcdefghijklmnopqrstuvwxyz0123456789AB", diffs[0].command
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
