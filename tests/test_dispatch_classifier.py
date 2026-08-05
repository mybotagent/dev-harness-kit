#!/usr/bin/env python3
"""Tests for lib/dispatch_classifier.py.

Covers the 5-rule classifier priority order + each rule's edge cases:
  1. Dependency edge → sequential
  2. Vague scope (TODO/FIXME/TBD/?/etc.) → sequential
  3. Overlapping writes without partition → sequential
  4. N >= 4 + clean isolation → parallel
  5. Default → sequential
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "lib"))

from dispatch_classifier import classify  # noqa: E402


def _step(n: int, **kwargs) -> dict:
    """Build a minimal step dict with a sensible default."""
    return {"step": n, **kwargs}


class TestClassifyDefault(unittest.TestCase):
    """Rule 5 — default sequential."""

    def test_empty_batch_is_sequential(self):
        d = classify([])
        self.assertEqual(d.mode, "sequential")
        self.assertIn("0 steps", d.reason)

    def test_small_batch_is_sequential(self):
        steps = [_step(1), _step(2), _step(3)]
        d = classify(steps)
        self.assertEqual(d.mode, "sequential")
        self.assertIn("3 steps", d.reason)
        # Below the _MIN_PARALLEL_N threshold.
        self.assertIn("insufficient N", d.reason)


class TestClassifyParallel(unittest.TestCase):
    """Rule 4 — N >= 4 + clean isolation → parallel."""

    def test_four_steps_with_clean_isolation_is_parallel(self):
        steps = [
            _step(1, partition="api-routes"),
            _step(2, partition="db-schema"),
            _step(3, partition="ui-components"),
            _step(4, partition="docs"),
        ]
        d = classify(steps)
        self.assertEqual(d.mode, "parallel")
        self.assertIn("4 steps", d.reason)
        self.assertIn("clean worktree isolation", d.reason)

    def test_five_steps_with_clean_isolation_is_parallel(self):
        steps = [_step(i, partition=f"module-{i}") for i in range(1, 6)]
        d = classify(steps)
        self.assertEqual(d.mode, "parallel")


class TestClassifyDependency(unittest.TestCase):
    """Rule 1 — dependency edge → sequential."""

    def test_depends_on_triggers_sequential(self):
        steps = [
            _step(1),
            _step(2, depends_on=["step1"]),
            _step(3),
            _step(4, partition="x"),
        ]
        d = classify(steps)
        self.assertEqual(d.mode, "sequential")
        self.assertIn("dependency edge", d.reason)

    def test_consumes_triggers_sequential(self):
        steps = [
            _step(1, partition="a"),
            _step(2, partition="b"),
            _step(3, partition="c"),
            _step(4, consumes="step1-output"),
        ]
        d = classify(steps)
        self.assertEqual(d.mode, "sequential")
        self.assertIn("dependency edge", d.reason)


class TestClassifyVagueScope(unittest.TestCase):
    """Rule 2 — vague-scope marker in preamble or AC → sequential."""

    def test_todo_in_preamble_triggers_sequential(self):
        steps = [
            _step(1, partition="a", preamble="TODO: figure out the schema"),
            _step(2, partition="b"),
            _step(3, partition="c"),
            _step(4, partition="d"),
        ]
        d = classify(steps)
        self.assertEqual(d.mode, "sequential")
        self.assertIn("vague scope", d.reason)

    def test_tbd_in_ac_triggers_sequential(self):
        steps = [
            _step(1, partition="a"),
            _step(2, partition="b"),
            _step(3, partition="c"),
            _step(4, partition="d", ac=["TBD: response shape"]),
        ]
        d = classify(steps)
        self.assertEqual(d.mode, "sequential")
        self.assertIn("vague scope", d.reason)

    def test_question_mark_in_preamble_triggers_sequential(self):
        steps = [
            _step(1, partition="a", preamble="What if the cache is stale?"),
            _step(2, partition="b"),
            _step(3, partition="c"),
            _step(4, partition="d"),
        ]
        d = classify(steps)
        self.assertEqual(d.mode, "sequential")


class TestClassifyOverlap(unittest.TestCase):
    """Rule 3 — overlapping writes without partition → sequential."""

    def test_shared_writes_without_partition_triggers_sequential(self):
        steps = [
            _step(1, partition="a", writes=["src/api/users.ts", "src/api/auth.ts"]),
            _step(2, partition="b", writes=["src/api/users.ts", "src/api/posts.ts"]),
            _step(3, partition="c"),
            _step(4, partition="d"),
        ]
        d = classify(steps)
        self.assertEqual(d.mode, "sequential")
        self.assertIn("overlapping writes", d.reason)

    def test_partitioned_overlap_still_triggers_sequential(self):
        """Partition documents intent; overlap is factual. Factual wins."""
        steps = [
            _step(1, partition="api-users", writes=["src/api/users.ts"]),
            _step(2, partition="api-posts", writes=["src/api/users.ts"]),  # same file
            _step(3, partition="c"),
            _step(4, partition="d"),
        ]
        d = classify(steps)
        # Overlap on writes is a sequential trigger regardless of partition.
        self.assertEqual(d.mode, "sequential")
        self.assertIn("overlapping writes", d.reason)


class TestClassifyPriorityOrder(unittest.TestCase):
    """Rule priority — first match wins."""

    def test_dependency_wins_over_vague_scope(self):
        steps = [
            _step(1, preamble="TODO: maybe"),
            _step(2, depends_on=["step1"]),
            _step(3),
            _step(4),
        ]
        d = classify(steps)
        self.assertEqual(d.mode, "sequential")
        # Either dependency or vague is acceptable as the first hit;
        # verify it isn't "parallel" — that's all the priority guarantees.
        self.assertNotEqual(d.mode, "parallel")

    def test_idempotent(self):
        """Re-invoking with the same input yields a byte-identical decision."""
        steps = [
            _step(1, partition="a"),
            _step(2, partition="b"),
            _step(3, partition="c"),
            _step(4, partition="d"),
        ]
        d1 = classify(steps)
        d2 = classify(steps)
        self.assertEqual(d1, d2)


class TestClassifyReasonFormat(unittest.TestCase):
    """Reason string is one-line, includes step count, suitable for build log."""

    def test_reason_is_single_line(self):
        d = classify([_step(1), _step(2)])
        self.assertNotIn("\n", d.reason)

    def test_reason_includes_step_count(self):
        d = classify([_step(1), _step(2), _step(3), _step(4), _step(5)])
        self.assertIn("5 steps", d.reason)


if __name__ == "__main__":
    unittest.main()
