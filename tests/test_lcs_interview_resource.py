#!/usr/bin/env python3
"""test_lcs_interview_resource.py — issue #354 interview resource (Phase 1.9).

Pins the ``lcs://interview/<step>`` contract:
- Item form returns a parsed hand-off MD frontmatter payload with the
  5 contract fields: safety_valve, ambiguity_score, value_score,
  evidence_count, status.
- Collection form (no segment, with or without trailing slash) raises
  ``LCSError`` — the resource is item-only.
- Missing hand-off file returns ``status="partial"`` with
  ``missing=["no hand-off <step>"]``.
- Empty hand-off file returns ``status="partial"`` with
  ``missing=["empty hand-off <step>"]``.
- Frontmatter may be partial: unknown / missing fields default to
  ``None`` and the envelope is still ``status="ok"``.
- Extra frontmatter keys are ignored; only the 5-field contract is
  surfaced.
- The full LCSServer routes ``lcs://interview/<step>`` through the
  interview handler, not a hypothetical generic handler.
"""
from __future__ import annotations

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT / "lib"))

from lcs_resources.interview import (  # noqa: E402
    NAME,
    InterviewResource,
    _candidate_paths,
    _parse_frontmatter,
)
from lcs_server import (  # noqa: E402
    LCSError,
    LCSPartialError,
    LCSServer,
    ParsedURI,
    Resource,
    ResourceRegistry,
    parse_uri,
)


def _write_hand_off(project_root: Path, filename: str, body: str) -> Path:
    """Write a hand-off MD file under ``<project>/.dev-kit/hand-off/``."""
    hand_off_dir = project_root / ".dev-kit" / "hand-off"
    hand_off_dir.mkdir(parents=True, exist_ok=True)
    path = hand_off_dir / filename
    path.write_text(body, encoding="utf-8")
    return path


def _write_frontmatter_hand_off(project_root: Path, filename: str, fm: str, body: str = "") -> Path:
    """Write a hand-off MD file with the given frontmatter block."""
    content = f"---\n{fm}\n---\n{body}"
    return _write_hand_off(project_root, filename, content)


def _build_server(project_root: Path) -> LCSServer:
    """Return an LCSServer wired with a fresh InterviewResource.

    ttl_seconds=0 → no caching between calls so each test gets a
    fresh read.
    """
    registry = ResourceRegistry()
    registry.register(InterviewResource(project_root))
    return LCSServer(registry, ttl_seconds=0)


class TestParseFrontmatter(unittest.TestCase):
    def test_extracts_all_five_fields(self):
        text = textwrap.dedent("""\
            ---
            safety_valve: 1
            ambiguity_score: 2
            value_score: 4.5
            evidence_count: 3
            status: ok
            ---
            # body
        """)
        parsed = _parse_frontmatter(text)
        self.assertEqual(parsed["safety_valve"], 1)
        self.assertEqual(parsed["ambiguity_score"], 2)
        self.assertEqual(parsed["value_score"], 4.5)
        self.assertEqual(parsed["evidence_count"], 3)
        self.assertEqual(parsed["status"], "ok")

    def test_partial_frontmatter_only_status(self):
        text = "---\nstatus: held\n---\n"
        parsed = _parse_frontmatter(text)
        self.assertEqual(parsed["status"], "held")
        self.assertIsNone(parsed["safety_valve"])
        self.assertIsNone(parsed["ambiguity_score"])
        self.assertIsNone(parsed["value_score"])
        self.assertIsNone(parsed["evidence_count"])

    def test_extra_frontmatter_keys_are_ignored(self):
        text = textwrap.dedent("""\
            ---
            safety_valve: 0
            ambiguity_score: 1
            value_score: 2.0
            evidence_count: 4
            status: ok
            extra_field: ignored
            another_junk: "should not appear"
            ---
        """)
        parsed = _parse_frontmatter(text)
        self.assertEqual(
            set(parsed.keys()),
            {"safety_valve", "ambiguity_score", "value_score", "evidence_count", "status"},
        )

    def test_no_frontmatter_returns_empty(self):
        self.assertEqual(_parse_frontmatter("just body, no frontmatter\n"), {})

    def test_unterminated_frontmatter_returns_empty(self):
        text = "---\nstatus: ok\nbody without closing\n"
        self.assertEqual(_parse_frontmatter(text), {})

    def test_status_string_field(self):
        text = "---\nstatus: held\n---\n"
        self.assertEqual(_parse_frontmatter(text)["status"], "held")


class TestCandidatePaths(unittest.TestCase):
    def test_simple_step_id_yields_single_candidate(self):
        paths = _candidate_paths(Path("/tmp/proj"), "plan-build")
        self.assertEqual([p.name for p in paths], ["plan-build.md"])

    def test_step_with_arrow_offers_dash_form(self):
        paths = _candidate_paths(Path("/tmp/proj"), "plan→build")
        self.assertIn("/tmp/proj/.dev-kit/hand-off/plan→build.md", [str(p) for p in paths])
        self.assertIn("/tmp/proj/.dev-kit/hand-off/plan-build.md", [str(p) for p in paths])

    def test_step_with_slash_offers_dash_form(self):
        # Raw form resolves to a nested path under hand-off; dash
        # form is the flat alternative.
        paths = _candidate_paths(Path("/tmp/proj"), "plan/build")
        self.assertIn("/tmp/proj/.dev-kit/hand-off/plan/build.md", [str(p) for p in paths])
        self.assertIn("/tmp/proj/.dev-kit/hand-off/plan-build.md", [str(p) for p in paths])

    def test_step_with_space_offers_dash_form(self):
        paths = _candidate_paths(Path("/tmp/proj"), "plan build")
        self.assertIn("/tmp/proj/.dev-kit/hand-off/plan build.md", [str(p) for p in paths])
        self.assertIn("/tmp/proj/.dev-kit/hand-off/plan-build.md", [str(p) for p in paths])

    def test_all_paths_share_same_directory(self):
        paths = _candidate_paths(Path("/tmp/proj"), "plan→build")
        for p in paths:
            # Either the immediate child or a nested child of
            # .dev-kit/hand-off — all live under the hand-off dir.
            self.assertTrue(str(p).startswith("/tmp/proj/.dev-kit/hand-off"))


class TestItemFormHandOff(unittest.TestCase):
    def test_item_form_with_hand_off(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_frontmatter_hand_off(
                root, "plan-build.md",
                "safety_valve: 1\n"
                "ambiguity_score: 2\n"
                "value_score: 4.5\n"
                "evidence_count: 3\n"
                "status: ok\n",
            )
            payload = _build_server(root).get("lcs://interview/plan-build")
            self.assertEqual(payload["status"], "ok")
            data = payload["data"]
            self.assertEqual(data["step"], "plan-build")
            self.assertEqual(data["safety_valve"], 1)
            self.assertEqual(data["ambiguity_score"], 2)
            self.assertEqual(data["value_score"], 4.5)
            self.assertEqual(data["evidence_count"], 3)
            self.assertEqual(data["status"], "ok")

    def test_item_form_url_encoded_step(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_frontmatter_hand_off(
                root, "plan-build.md",
                "status: ok\n",
            )
            payload = _build_server(root).get("lcs://interview/plan%E2%86%92build")
            self.assertEqual(payload["status"], "ok")
            # The decoded step id is "plan→build"; the resource falls
            # back to the dash-encoded filename "plan-build.md".
            self.assertEqual(payload["data"]["step"], "plan→build")
            self.assertEqual(payload["data"]["status"], "ok")

    def test_missing_hand_off_partial(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            payload = _build_server(root).get("lcs://interview/missing-step")
            self.assertEqual(payload["status"], "partial")
            self.assertEqual(payload["data"]["step"], "missing-step")
            self.assertEqual(payload["missing"], ["no hand-off missing-step"])

    def test_empty_hand_off_partial(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_hand_off(root, "blank.md", "")
            payload = _build_server(root).get("lcs://interview/blank")
            self.assertEqual(payload["status"], "partial")
            self.assertEqual(payload["data"]["step"], "blank")
            self.assertEqual(payload["missing"], ["empty hand-off blank"])

    def test_hand_off_with_only_status_field(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_frontmatter_hand_off(
                root, "held.md",
                "status: held\n",
            )
            payload = _build_server(root).get("lcs://interview/held")
            self.assertEqual(payload["status"], "ok")
            data = payload["data"]
            self.assertEqual(data["step"], "held")
            self.assertEqual(data["status"], "held")
            self.assertIsNone(data["safety_valve"])
            self.assertIsNone(data["ambiguity_score"])
            self.assertIsNone(data["value_score"])
            self.assertIsNone(data["evidence_count"])

    def test_hand_off_with_extra_frontmatter_fields(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_frontmatter_hand_off(
                root, "extra.md",
                "safety_valve: 0\n"
                "ambiguity_score: 1\n"
                "value_score: 2.0\n"
                "evidence_count: 4\n"
                "status: ok\n"
                "extra_field: ignored\n"
                "weird_key: 42\n",
            )
            payload = _build_server(root).get("lcs://interview/extra")
            self.assertEqual(payload["status"], "ok")
            data = payload["data"]
            self.assertEqual(
                set(data.keys()),
                {"step", "safety_valve", "ambiguity_score", "value_score", "evidence_count", "status"},
            )


class TestCollectionFormRaises(unittest.TestCase):
    def test_collection_form_raises(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            resource = InterviewResource(root)
            parsed = parse_uri("lcs://interview")
            with self.assertRaises(LCSError) as ctx:
                resource.fetch(parsed)
            self.assertIn("requires a step id", str(ctx.exception))

    def test_collection_form_trailing_slash(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            resource = InterviewResource(root)
            parsed = parse_uri("lcs://interview/")
            with self.assertRaises(LCSError) as ctx:
                resource.fetch(parsed)
            self.assertIn("requires a step id", str(ctx.exception))


class TestResourceIdentity(unittest.TestCase):
    def test_name_constant(self):
        self.assertEqual(NAME, "interview")


class TestLcsServerRouting(unittest.TestCase):
    def test_uri_routes_through_lcs_server(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_frontmatter_hand_off(
                root, "abc.md",
                "status: ok\n",
            )
            server = _build_server(root)
            payload = server.get("lcs://interview/abc")
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(payload["data"]["step"], "abc")
            self.assertEqual(payload["data"]["status"], "ok")

    def test_segment_priority_interview_wins_over_generic(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_frontmatter_hand_off(
                root, "abc.md",
                "status: ok\n",
            )

            class _GenericHandler(Resource):
                name = "inter"

                def fetch(self, parsed: ParsedURI) -> dict:
                    return {
                        "status": "ok",
                        "data": {"matched": "inter-generic", "step": parsed.path_segments[1]},
                    }

            registry = ResourceRegistry()
            registry.register(_GenericHandler())
            registry.register(InterviewResource(root))
            server = LCSServer(registry, ttl_seconds=0)
            payload = server.get("lcs://interview/abc")
            # The interview resource has the 5-field contract; the
            # generic handler has "matched"+"step" only.
            self.assertIn("safety_valve", payload["data"])
            self.assertIn("value_score", payload["data"])
            self.assertEqual(payload["data"]["step"], "abc")
            self.assertNotIn("matched", payload["data"])


if __name__ == "__main__":
    unittest.main()
