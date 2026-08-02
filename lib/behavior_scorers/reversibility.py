"""reversibility.py — D8 Reversibility.

Pure deterministic scorer. Returns 1-5 based on 5 signals, each
contributing 0 or 1 to a sum, then mapped: 5/5=5, 4/5=4, 3/5=3,
2/5=2, ≤1/5=1.

Signals:
1. commit_granularity — fine-grained commits (count vs diff-line count).
2. handoff_next_step — hand-off note has a "next" or "TODO next" section.
3. no_magic_markers — no TODO/FIXME/XXX/HACK/magic strings in lib/ diff.
4. migrations_reversible — migration files have `down` / `downgrade` /
   `revert` methods.
5. feature_flag_usage — code uses `flag` / `feature_flag` / `launchdarkly`
   patterns (gating risky changes).

Each signal: 0 or 1. Sum → value.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List

from lib.behavior_scorers.types import Context, DimensionScore

# L4 forbids TODO/FIXME/starting-point/'we'll extend later' in committed code.
# D8 reuses the same exclusion set for the "no magic markers" signal.
_L1_FORBIDDEN_RE = re.compile(
    r"\b(TODO|FIXME|XXX|HACK)\b|we'll extend later|starting point|magic",
    re.IGNORECASE,
)

# Migration directory conventions. Match `migrations/`, `db/migrations/`,
# `prisma/migrations/`, `alembic/versions/`, `knex/migrations/`.
_MIGRATION_DIR_RE = re.compile(
    r"(?:^|/)("
    r"migrations/"
    r"|db/migrations/"
    r"|prisma/migrations/"
    r"|alembic/versions/"
    r"|knex/migrations/"
    r")(?!.*__pycache__).*",
)

_NEXT_STEP_RE = re.compile(
    r"^\s*(?:[-*]|\d+\.|\#\#)\s+.*\b(?:next|todo\s+next|todo:?\s*next)\b",
    re.IGNORECASE | re.MULTILINE,
)

_FEATURE_FLAG_RE = re.compile(
    r"\b(flag|feature_flag|featureFlag|feature[-_]?toggle|launchdarkly)\b",
    re.IGNORECASE,
)

_DOWNGRADE_RE = re.compile(
    r"\b(down\s*\(|downgrade|revert|rollback|def\s+down)\b",
    re.IGNORECASE,
)


def _git_output(worktree: Path, *args: str) -> str:
    """Run git and return stdout; '' on error."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(worktree), *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""
    return (proc.stdout or "").strip()


def _signal_commit_granularity(worktree: Path) -> int:
    """1 when commit count >= ceil(diff-line-count / 50).

    A ratio of >=1 commit per 50 lines signals fine-grained commits.
    Vacuously 1 when there are no commits or no diff lines (first run).
    """
    raw_log = _git_output(worktree, "log", "--oneline", "origin/main..HEAD")
    if not raw_log:
        return 1  # no upstream / no commits — vacuously compliant
    commit_count = sum(1 for line in raw_log.splitlines() if line.strip())

    raw_diff = _git_output(worktree, "diff", "--shortstat", "origin/main..HEAD")
    diff_lines = 0
    # Shortstat shape: " N files changed, M insertions(+), D deletions(-)"
    ins_m = re.search(r"(\d+)\s+insertion", raw_diff)
    del_m = re.search(r"(\d+)\s+deletion", raw_diff)
    diff_lines = (int(ins_m.group(1)) if ins_m else 0) + (int(del_m.group(1)) if del_m else 0)
    if diff_lines == 0:
        return 1  # nothing to be granular about
    threshold = max(1, (diff_lines + 49) // 50)  # ceil(L/50)
    return 1 if commit_count >= threshold else 0


def _signal_handoff_next_step(worktree: Path) -> int:
    """1 when any `.dev-kit/hand-off/*.md` has a `next`/`TODO next` bullet."""
    handoff_dir = worktree / ".dev-kit" / "hand-off"
    if not handoff_dir.is_dir():
        return 0
    for p in handoff_dir.glob("*.md"):
        try:
            text = p.read_text(errors="ignore")
        except OSError:
            continue
        if _NEXT_STEP_RE.search(text):
            return 1
    return 0


def _signal_no_magic_markers(worktree: Path) -> int:
    """1 when the diff in `lib/` has no forbidden markers."""
    diff = _git_output(worktree, "log", "-p", "--diff-filter=AM", "origin/main..HEAD", "--", "lib/")
    if not diff:
        return 1  # no lib/ diff — vacuously clean
    added = "\n".join(
        line[1:]
        for line in diff.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    return 0 if _L1_FORBIDDEN_RE.search(added) else 1


def _signal_migrations_reversible(worktree: Path) -> int:
    """1 when no migration files are present, OR all present ones have
    downgrade/revert methods.

    When the worktree has no migrations dir, signal is vacuously 1
    (nothing to verify).
    """
    candidates: List[Path] = []
    for pattern in ("migrations", "db/migrations", "prisma/migrations",
                    "alembic/versions", "knex/migrations"):
        candidates.extend(worktree.glob(f"{pattern}/**/*"))
    candidates = [
        p for p in candidates
        if p.is_file() and "__pycache__" not in p.parts
        and not p.name.startswith(".")
    ]
    if not candidates:
        return 1  # nothing to verify → vacuously compliant
    for path in candidates:
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        if not _DOWNGRADE_RE.search(text):
            return 0
    return 1


def _signal_feature_flag_usage(worktree: Path) -> int:
    """1 when the diff has feature-flag references (gates risky changes).

    A 'low' signal: feature flags are optional discipline, so we treat
    absence as 0 (no signal either way) UNLESS the diff touches
    high-risk areas like migrations or destructive ops. In that case,
    absence is a 0 (should have gated). For Phase 0, score purely by
    presence — flagged commits ∈ [0, 1].
    """
    raw = _git_output(worktree, "diff", "origin/main..HEAD")
    if not raw:
        return 0
    added = "\n".join(
        line[1:]
        for line in raw.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )
    return 1 if _FEATURE_FLAG_RE.search(added) else 0


def score(worktree: Path, ctx: Context) -> DimensionScore:
    """Score D8 from the 5 binary signals; sum maps to 1-5."""
    signals: Dict[str, Any] = {
        "commit_granularity": _signal_commit_granularity(worktree),
        "handoff_next_step": _signal_handoff_next_step(worktree),
        "no_magic_markers": _signal_no_magic_markers(worktree),
        "migrations_reversible": _signal_migrations_reversible(worktree),
        "feature_flag_usage": _signal_feature_flag_usage(worktree),
    }
    total = sum(int(v) for v in signals.values())
    # Map 0..5 → 1..5 (each signal maps 1:1 to a point, capped at 5).
    value = max(1, min(5, total))
    return DimensionScore(
        dim="D8_reversibility",
        value=value,
        evidence={
            **signals,
            "checks_passed": total,
            "checks_total": len(signals),
        },
    )
