#!/usr/bin/env python3
"""test_lcs_routes_flag.py — Gap 4 of issue #455.

Pins the ``--list-routes`` flag on ``bin/dev-kit-lcs.py``. The flag
prints the registered-vs-reserved split that fixes the "documented
but not wired" trap (operators reading the SKILL.md URI table
discover which URIs are real).

The CLI is invoked as a subprocess so the same exit-code / framing
contract used by ``test_dev_kit_lcs_cli.py`` is exercised
end-to-end.

The complementary invariant — SKILL.md's main URI table lists ONLY
registered routes — is asserted at the doc level via a direct
parse of the markdown table.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).parent.parent
CLI = REPO_ROOT / "bin" / "dev-kit-lcs.py"
SKILL_MD = REPO_ROOT / "skills" / "lcs" / "SKILL.md"


def _run_cli(*args: str, timeout: float = 5.0) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        str(REPO_ROOT / "lib") + os.pathsep + env.get("PYTHONPATH", "")
    )
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
        check=False,
    )


def _split_sections(output: str) -> dict[str, list[str]]:
    """Split ``--list-routes`` output into ``{section_name: [lines...]}``.

    A line starting with ``<word>:`` at column 0 starts a new section.
    All subsequent lines until the next section marker belong to it.
    """
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in output.splitlines():
        if line and not line.startswith(" ") and line.endswith(":"):
            current = line[:-1]
            sections[current] = []
        elif current is not None and line:
            sections[current].append(line)
    return sections


def _strip_code_span(text: str) -> str:
    """Strip a single backtick-wrapped code span (`` `xxx` ``)."""
    s = text.strip()
    if s.startswith("`") and s.endswith("`") and len(s) >= 2:
        return s[1:-1].strip()
    return s


# ──────────────────────────────────────────────────────────────────
# --list-routes flag
# ──────────────────────────────────────────────────────────────────

class TestListRoutes(unittest.TestCase):
    def test_list_routes_exits_zero(self):
        cp = _run_cli("--list-routes")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)

    def test_output_has_both_sections(self):
        cp = _run_cli("--list-routes")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        sections = _split_sections(cp.stdout)
        self.assertIn("registered", sections)
        self.assertIn("reserved (not implemented)", sections)

    def test_reserved_section_lists_all_three_routes(self):
        cp = _run_cli("--list-routes")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        reserved_lines = "\n".join(
            _split_sections(cp.stdout).get("reserved (not implemented)", [])
        )
        for reserved_uri in (
            "lcs://hooks/coverage",
            "lcs://interview/<step>",
            "lcs://research/cache",
        ):
            self.assertIn(reserved_uri, reserved_lines,
                          f"{reserved_uri} missing from reserved section")

    def test_registered_section_lists_all_six_production_routes(self):
        cp = _run_cli("--list-routes")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        registered_lines = "\n".join(
            _split_sections(cp.stdout).get("registered", [])
        )
        # Each registered resource appears in the registered section.
        for resource_name in (
            "worktrees", "branches", "pr", "sessions", "spend", "valuations",
        ):
            self.assertIn(resource_name, registered_lines,
                          f"{resource_name} missing from registered section")

    def test_registered_section_includes_demo_route_when_enabled(self):
        with mock.patch.dict(os.environ, {"DEV_KIT_LCS_DEMO": "1"}):
            cp = _run_cli("--list-routes")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        registered_lines = "\n".join(
            _split_sections(cp.stdout).get("registered", [])
        )
        self.assertRegex(
            registered_lines, r"(?m)^\s+lcs://demo/<path>\s+demo$",
        )


# ──────────────────────────────────────────────────────────────────
# SKILL.md honesty invariant
# ──────────────────────────────────────────────────────────────────

class TestSkillMdReservedRoutes(unittest.TestCase):
    """The SKILL.md main URI table must NOT list reserved URIs.

    Reserved URIs live in a dedicated "Reserved (planned, not
    implemented)" section with an explicit ``status: not-registered``
    field. Anything in the main URI table must correspond to a
    registered handler — that's the contract Gap 4 enforces.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.body = SKILL_MD.read_text(encoding="utf-8")

    def _main_uri_table_rows(self) -> list[tuple[str, str]]:
        """Return [(uri, description), ...] from the FIRST markdown table.

        The first table in the SKILL.md is the main URI contract table.
        Reserved URIs live outside it (in a dedicated section), so this
        function targets the main table exclusively. Each URI cell is
        stripped of its surrounding backticks (markdown code span).
        """
        lines = self.body.splitlines()
        table_start = None
        for idx, line in enumerate(lines):
            if line.lstrip().startswith("|") and "---" not in line:
                table_start = idx
                break
        if table_start is None:
            self.fail("SKILL.md has no markdown table — main URI table missing")
        rows: list[str] = []
        for line in lines[table_start:]:
            if not line.lstrip().startswith("|"):
                if rows:
                    break
                continue
            rows.append(line)
        body_rows = [r for r in rows if "---" not in r][1:]
        parsed: list[tuple[str, str]] = []
        for r in body_rows:
            cells = [c.strip() for c in r.strip().strip("|").split("|")]
            if len(cells) >= 2:
                parsed.append((_strip_code_span(cells[0]), cells[1]))
        return parsed

    def test_main_table_excludes_all_reserved_uris(self):
        main_rows = self._main_uri_table_rows()
        main_uris = {uri for uri, _ in main_rows}
        for reserved in (
            "lcs://hooks/coverage",
            "lcs://interview/<step>",
            "lcs://research/cache",
        ):
            self.assertNotIn(reserved, main_uris,
                             f"reserved URI {reserved} leaked into main URI table")

    def test_main_table_only_contains_registered_resource_names(self):
        registered_names = {
            "worktrees", "branches", "pr", "sessions", "spend", "valuations",
        }
        main_rows = self._main_uri_table_rows()
        for uri, _desc in main_rows:
            segment = uri[len("lcs://"):].split("/", 1)[0]
            self.assertIn(segment, registered_names,
                          f"main table URI {uri!r} points to unregistered "
                          f"resource segment {segment!r}")

    def test_reserved_section_has_status_not_registered_field(self):
        """The reserved section must carry the explicit status marker."""
        body = self.body
        m = re.search(
            r"^#{2,}\s*reserved[^\n]*$",
            body, flags=re.MULTILINE | re.IGNORECASE,
        )
        self.assertIsNotNone(m,
                             "no 'Reserved ...' section heading in SKILL.md")
        section_body = body[m.end():m.end() + 2000]
        self.assertIn("not-registered", section_body,
                      "reserved section is missing 'status: not-registered'")


if __name__ == "__main__":
    unittest.main()
