#!/usr/bin/env python3
"""Tests for lib/dispatch_classifier.py.

Covers the 5-rule classifier priority order + each rule's edge cases:
  1. Dependency edge → sequential
  2. Vague scope (TODO/FIXME/TBD/maybe/perhaps/either) → sequential
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

    def test_question_mark_in_preamble_alone_is_not_vague(self):
        """Regression: bare '?' must not trigger vague-scope.

        Single-character markers are too coarse (collide with URLs,
        ternary expressions, legitimate questions). Ambiguity is captured
        by the multi-character words ("maybe", "perhaps", "either").
        """
        steps = [
            _step(1, partition="a", preamble="What if the cache is stale?"),
            _step(2, partition="b"),
            _step(3, partition="c"),
            _step(4, partition="d"),
        ]
        d = classify(steps)
        self.assertEqual(d.mode, "parallel")


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
        # Per the first-match-wins contract, when both signals are present
        # the dependency rule (Rule 1) must fire before the vague-scope rule
        # (Rule 2). Lock the specific reason that won.
        self.assertIn("dependency edge", d.reason,
                      f"first-match-wins requires dependency rule to win over vague scope; got: {d.reason!r}")

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

class TestClassifyVagueScopeFalsePositives(unittest.TestCase):
    """Regression: markers that LOOK like ambiguity but aren't.

    Single-character markers (e.g. "?") must NOT trigger sequential —
    they appear in URLs, ternary expressions, and legitimate questions.
    """

    def test_url_with_query_string_is_not_vague(self):
        steps = [
            _step(1, partition="a", preamble="fetch https://api.example.com/items?id=42&page=2"),
            _step(2, partition="b"),
            _step(3, partition="c"),
            _step(4, partition="d"),
        ]
        d = classify(steps)
        self.assertEqual(d.mode, "parallel",
                         "URL with ?query=string must not trigger '?' as vague-scope")

    def test_ternary_expression_is_not_vague(self):
        steps = [
            _step(1, partition="a", preamble="value = (a > b) ? c : d"),
            _step(2, partition="b"),
            _step(3, partition="c"),
            _step(4, partition="d"),
        ]
        d = classify(steps)
        self.assertEqual(d.mode, "parallel",
                         "ternary expression ? : must not trigger '?' as vague-scope")

    def test_legitimate_question_in_preamble_is_not_vague(self):
        steps = [
            _step(1, partition="a", preamble="How does the runner choose parallel?"),
            _step(2, partition="b"),
            _step(3, partition="c"),
            _step(4, partition="d"),
        ]
        d = classify(steps)
        self.assertEqual(d.mode, "parallel",
                         "legitimate ? in a question must not trigger '?' as vague-scope")


class TestClassifyCanonicalMetadataFailClosed(unittest.TestCase):
    """PR #579 3-dim review round 8: missing metadata is treated as
    proof of clean isolation, causing four ordinary plan-generated
    pending steps (which have only step/name/status, no writes/partition)
    to be classified as parallel.

    The fix: classify() must fail closed. Missing writes OR missing
    partition on a step = sequential, regardless of count.
    """

    def test_canonical_register_step_entry_with_no_writes_is_sequential(self):
        """A plan-generated step has only {step, name, status}; no
        writes, no partition. With N=4 of these, the classifier must
        return sequential — the safety default."""
        # Simulate canonical register_step() entries.
        steps = [
            {"step": 1, "name": "a", "status": "pending"},
            {"step": 2, "name": "b", "status": "pending"},
            {"step": 3, "name": "c", "status": "pending"},
            {"step": 4, "name": "d", "status": "pending"},
        ]
        d = classify(steps)
        self.assertEqual(
            d.mode, "sequential",
            f"canonical plan entries (no writes/partition) must be "
            f"sequential, not parallel; got mode={d.mode!r} reason={d.reason!r}",
        )

    def test_explicit_writes_but_missing_partition_is_sequential(self):
        """Writes present without partition is not enough — partition
        documents intent for the shared-state. Without it, sequential."""
        steps = [
            _step(1, partition="api-routes", writes=["src/api/users.ts"]),
            _step(2, partition="db-schema", writes=["src/db/users.ts"]),
            _step(3, partition="ui-components", writes=["src/ui/users.tsx"]),
            _step(4, partition="docs", writes=["docs/users.md"]),
        ]
        # Remove the partition field from each step
        for s in steps:
            del s["partition"]
        d = classify(steps)
        self.assertEqual(d.mode, "sequential",
                         f"writes-without-partition must be sequential, not parallel; got {d.mode!r}")





class TestClassifyACFieldValidation(unittest.TestCase):
    """PR #579 3-dim review round 8: unvalidated ac field shapes can
    bypass the vague-scope safety rule. ac="TODO: investigate" is
    joined char-by-char into "T O D O : ...", missing the todo: marker.

    The fix: normalize ac to a list of strings before searching for
    markers. Strings are wrapped; lists are used as-is; other types
    raise a clear, safe-default.
    """

    def test_ac_string_TODO_triggers_sequential(self):
        steps = [
            _step(1, partition="a", ac="TODO: investigate the cache"),
            _step(2, partition="b"),
            _step(3, partition="c"),
            _step(4, partition="d"),
        ]
        d = classify(steps)
        self.assertEqual(d.mode, "sequential",
                         f"ac='TODO: investigate' must trigger vague scope; got {d.mode!r}")

    def test_ac_list_with_TODO_triggers_sequential(self):
        steps = [
            _step(1, partition="a", ac=["TODO: investigate", "Other AC"]),
            _step(2, partition="b"),
            _step(3, partition="c"),
            _step(4, partition="d"),
        ]
        d = classify(steps)
        self.assertEqual(d.mode, "sequential")

    def test_ac_dict_with_string_TODO_value_triggers_sequential(self):
        """If ac is a dict (some plan outputs), the string values are
        searched for markers — the dict keys are not the source of
        the marker, the values are."""
        steps = [
            _step(1, partition="a", ac={"q1": "TODO: investigate"}),
            _step(2, partition="b"),
            _step(3, partition="c"),
            _step(4, partition="d"),
        ]
        d = classify(steps)
        self.assertEqual(d.mode, "sequential")

    def test_ac_list_with_clean_text_does_not_trigger(self):
        steps = [
            _step(1, partition="a", ac=["Use existing test", "Be specific"]),
            _step(2, partition="b"),
            _step(3, partition="c"),
            _step(4, partition="d"),
        ]
        d = classify(steps)
        self.assertEqual(d.mode, "parallel",
                         f"clean ACs should not trigger vague scope; got {d.mode!r}")


class TestVagueScopeLogInjection(unittest.TestCase):
    """Regression: step number can be a string containing a newline.

    Without coercion, the reason spans multiple stderr lines and
    could mislead a downstream log parser. The fix: coerce to a
    single line via str().splitlines()[0].
    """

    def test_step_with_newline_in_value_is_single_line(self):
        # A crafted phases/.../index.json with a step number that is
        # a string containing a newline. The reason must be single-line.
        steps = [
            _step(1, partition="a", preamble="TODO: investigate"),
            _step(2, partition="b"),
            _step(3, partition="c"),
            _step(4, partition="d"),
        ]
        # Override step[0] with a string containing a newline.
        steps[0]["step"] = "1\n[ERROR] fake log"
        d = classify(steps)
        self.assertEqual(d.mode, "sequential")
        # Coercion: only the first line of the step number is in the
        # reason. The injected "[ERROR] fake log" is dropped.
        self.assertIn("1 ", d.reason)
        self.assertNotIn("[ERROR] fake log", d.reason)



if __name__ == "__main__":
    unittest.main()
