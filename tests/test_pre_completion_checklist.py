"""Tests for the pre-completion intent checklist."""
from __future__ import annotations

from lib.pre_completion_checklist import check, read_user_request

ALL_DIFF = """
+requirements addressed: implemented the requested cache feature
+docs updated in the README
+edge cases flagged: empty, missing, and timeout inputs are validated
+public APIs documented with a reference docstring
+tests not skipped: pytest passed
+def implementation():
+    return True
+"""


def test_empty_diff_fails_all_items() -> None:
    result = check("Implement the cache feature", "", [])
    assert result.passed is False
    assert len(result.failed_items) == 5
    assert result.blocking is True


def test_diff_with_all_five_items_passes() -> None:
    result = check("Implement the cache feature", ALL_DIFF, ["lib/cache.py", "README.md", "tests/test_cache.py"])
    assert result.passed is True
    assert result.failed_items == []
    assert result.blocking is False


def test_partial_diff_reports_specific_reasons() -> None:
    result = check("Implement the cache feature", "+requirements addressed: implemented\n+tests not skipped: pytest passed", ["lib/cache.py"])
    assert result.passed is False
    assert result.failed_items == ["docs updated", "edge cases flagged", "public APIs documented"]
    assert result.blocking is False


def test_blocking_only_for_failed_critical_items() -> None:
    advisory = check("Implement the cache feature", ALL_DIFF.replace("edge cases flagged: empty, missing, and timeout inputs are validated", ""), ["lib/cache.py", "README.md", "tests/test_cache.py"])
    critical = check("Implement the cache feature", "+docs updated\n+edge cases flagged\n+public APIs documented", ["lib/cache.py"])
    assert advisory.blocking is False
    assert critical.blocking is True


def test_reads_original_request_from_handoff(tmp_path) -> None:
    handoff = tmp_path / ".dev-kit" / "hand-off"
    handoff.mkdir(parents=True)
    (handoff / "request.md").write_text("Implement the cache feature", encoding="utf-8")
    result = check(read_user_request(tmp_path), "+cache feature implemented\n+tests passed", ["tests/test_cache.py"])
    assert "Implement the cache feature" in read_user_request(tmp_path)
    assert result.failed_items == ["docs updated", "edge cases flagged", "public APIs documented"]
