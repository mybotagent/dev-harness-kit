"""Fixture: compile-failure worktree.

Imports a missing module so `pytest --collect-only` succeeds (file parses)
but `pytest -q` fails when actually collecting tests. This pushes
D1_outcome to ~3 (some tests fail) and triggers DRIFT_WARNING.
"""
import does_not_exist_module  # noqa: F401 — intentional, drives D1 down
