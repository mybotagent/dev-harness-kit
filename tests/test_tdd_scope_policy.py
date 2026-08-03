#!/usr/bin/env python3
"""Rules-first TDD scope policy tests."""
from __future__ import annotations

import unittest

from lib.tdd_scope_policy import Decision, classify_path


class TestTddScopePolicy(unittest.TestCase):
    def test_documents_and_maintenance_are_exempt(self):
        for path in (
            "docs/guide.py", "README.md", "tools/one_off.py",
            "scripts/migrate.py", "hooks/check.sh", "config/app.yaml",
            "tests/test_feature.py", "fixtures/sample.json",
        ):
            self.assertEqual(classify_path(path), Decision.EXEMPT, path)

    def test_core_code_requires_tdd(self):
        for path in ("lib/auth.py", "src/services/user.py", "app/api/users.py"):
            self.assertEqual(classify_path(path), Decision.REQUIRED, path)

    def test_unknown_path_is_deferred_to_judge(self):
        self.assertEqual(classify_path("packages/plugin/index.ts"), Decision.JUDGE)
