#!/usr/bin/env python3
"""test_repo_license.py — regression for the README badge → LICENSE file claim.

The README badge `[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)`
and `.claude-plugin/plugin.json`/`LICENSE` field both promise an MIT-licensed
project at the repo root. If `LICENSE` ever disappears, the badge link 404s
and the project fails its own self-declared license claim.

  T1: `LICENSE` exists at the repo root.
  T2: the file contains the `MIT License` token.
  T3: the file contains a `Copyright (c)` line with a 4-digit year.
"""
from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LICENSE = REPO_ROOT / "LICENSE"


class LicenseFilePresent(unittest.TestCase):
    def test_license_file_exists_at_repo_root(self) -> None:
        self.assertTrue(
            LICENSE.is_file(),
            f"LICENSE missing at {LICENSE}; README badge and plugin.json MIT claim 404.",
        )

    def test_license_file_contains_mit_token(self) -> None:
        text = LICENSE.read_text(encoding="utf-8")
        self.assertIn(
            "MIT License",
            text,
            f"{LICENSE} does not contain the 'MIT License' token; verify the badge claim.",
        )

    def test_license_file_has_copyright_line(self) -> None:
        text = LICENSE.read_text(encoding="utf-8")
        self.assertRegex(
            text,
            r"Copyright \(c\) \d{4}",
            f"{LICENSE} has no 'Copyright (c) <year>' line.",
        )


if __name__ == "__main__":
    raise SystemExit(unittest.main())
