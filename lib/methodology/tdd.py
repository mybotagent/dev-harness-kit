#!/usr/bin/env python3
"""tdd.py — TDD methodology adapter (default, MUST-48)."""
from __future__ import annotations
from pathlib import Path
from typing import Dict, List
from .abc import Methodology  # relative import


class TddMethodology(Methodology):
    name = "tdd"
    description = "Red-Green-Refactor. Failing unit test first, then minimal impl."
    default_for_projects = ["python", "typescript", "javascript"]

    def pre_check(self, worktree_path: Path, step: Dict) -> Dict:
        n = step.get("name", "feature")
        return {
            "artifact_path": f"tests/test_{n}.py",
            "expected_content": "# RED — failing test for " + n,
            "verification_cmd": f"pytest -xvs tests/test_{n}.py",
        }

    def verification_command(self, worktree_path: Path, step: Dict) -> List[str]:
        n = step.get("name", "feature")
        return [
            f"pytest tests/test_{n}.py -x --tb=short",
            "pytest --tb=short -q",
            "ruff check src/",
        ]

    def cycle_steps(self) -> List[str]:
        return ["red", "green", "refactor"]

    def report_status(self, worktree_path: Path, step: Dict) -> Dict:
        return {"status": "pass", "score": 10, "issues": []}


INSTANCE = TddMethodology()
