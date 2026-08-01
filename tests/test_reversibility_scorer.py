"""test_reversibility_scorer.py — covers all 5 signals + aggregation."""
from __future__ import annotations

import subprocess
from pathlib import Path

from lib.behavior_scorers.reversibility import (
    _signal_commit_granularity,
    _signal_feature_flag_usage,
    _signal_handoff_next_step,
    _signal_migrations_reversible,
    _signal_no_magic_markers,
    score,
)
from lib.behavior_scorers.types import Context


def _init_git(worktree: Path, commits: int = 1) -> None:
    subprocess.run(["git", "init", "-q", "-b", "main", str(worktree)], check=True)
    subprocess.run(["git", "-C", str(worktree), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(worktree), "config", "user.name", "T"], check=True)
    subprocess.run(
        ["git", "-C", str(worktree), "commit", "--allow-empty", "-q", "-m", "init"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(worktree), "checkout", "-q", "-b", "feat/test"],
        check=True,
    )


def _commit(worktree: Path, msg: str) -> None:
    subprocess.run(["git", "-C", str(worktree), "commit", "--allow-empty", "-q", "-m", msg], check=True)


def _set_origin_main(worktree: Path) -> None:
    head = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "main"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "-C", str(worktree), "update-ref", "refs/remotes/origin/main", head],
        check=True,
    )


def test_signal_commit_granularity_fine_grained(tmp_path: Path) -> None:
    """N commits → 1; one giant commit → 0."""
    wt = tmp_path / "wt"
    wt.mkdir()
    _init_git(wt)
    # 3 commits, each 10 lines → 30 lines total → ceil(30/50)=1 commit needed.
    (wt / "lib").mkdir()
    for i in range(3):
        (wt / "lib" / f"f{i}.py").write_text(f"x = {i}\n" * 10)
        subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
        _commit(wt, f"feat: file {i}")
    _set_origin_main(wt)
    assert _signal_commit_granularity(wt) == 1


def test_signal_commit_granularity_giant_commit(tmp_path: Path) -> None:
    """One commit covering > 50 lines → 0."""
    wt = tmp_path / "wt"
    wt.mkdir()
    _init_git(wt)
    (wt / "lib").mkdir()
    (wt / "lib" / "big.py").write_text("x = 1\n" * 200)
    subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
    _commit(wt, "feat: one giant commit")
    _set_origin_main(wt)
    assert _signal_commit_granularity(wt) == 0


def test_signal_handoff_next_step_present(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    handoff = wt / ".dev-kit" / "hand-off"
    handoff.mkdir(parents=True)
    (handoff / "round-1.md").write_text(
        "# Round 1\n\n## next\n- ship the auth fix\n"
    )
    assert _signal_handoff_next_step(wt) == 1


def test_signal_handoff_next_step_absent(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    (wt / ".dev-kit" / "hand-off").mkdir(parents=True)
    (wt / ".dev-kit" / "hand-off" / "r.md").write_text("no next step here\n")
    assert _signal_handoff_next_step(wt) == 0


def test_signal_handoff_next_step_no_dir(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    assert _signal_handoff_next_step(wt) == 0


def test_signal_no_magic_markers_clean(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    _init_git(wt)
    (wt / "lib").mkdir()
    (wt / "lib" / "f.py").write_text("def f(): return 1\n")
    subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
    _commit(wt, "feat: clean")
    _set_origin_main(wt)
    assert _signal_no_magic_markers(wt) == 1


def test_signal_no_magic_markers_forbidden(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    _init_git(wt)
    (wt / "lib").mkdir()
    (wt / "lib" / "f.py").write_text("# TODO: clean me\ndef f(): return 1\n")
    subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
    _commit(wt, "feat: with TODO")
    _set_origin_main(wt)
    assert _signal_no_magic_markers(wt) == 0


def test_signal_migrations_reversible_no_migrations_dir(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    assert _signal_migrations_reversible(wt) == 1


def test_signal_migrations_reversible_all_have_down(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    mig = wt / "migrations"
    mig.mkdir()
    (mig / "001_init.py").write_text(
        "def up(): pass\ndef downgrade(): pass\n"
    )
    assert _signal_migrations_reversible(wt) == 1


def test_signal_migrations_reversible_missing_down(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    mig = wt / "migrations"
    mig.mkdir()
    (mig / "001_init.py").write_text("def up(): pass\n")
    assert _signal_migrations_reversible(wt) == 0


def test_signal_feature_flag_usage_present(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    _init_git(wt)
    (wt / "lib").mkdir()
    (wt / "lib" / "f.py").write_text("FLAG = feature_flag('X')\n")
    subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
    _commit(wt, "feat: with flag")
    _set_origin_main(wt)
    assert _signal_feature_flag_usage(wt) == 1


def test_signal_feature_flag_usage_absent(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    _init_git(wt)
    (wt / "lib").mkdir()
    (wt / "lib" / "f.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
    _commit(wt, "feat: no flag")
    _set_origin_main(wt)
    assert _signal_feature_flag_usage(wt) == 0


def test_score_full_passes(tmp_path: Path) -> None:
    """Score 5 when all five signals pass."""
    wt = tmp_path / "wt"
    wt.mkdir()
    _init_git(wt)
    # Hand-off next step.
    handoff = wt / ".dev-kit" / "hand-off"
    handoff.mkdir(parents=True)
    (handoff / "r.md").write_text("## next\n- ship it\n")
    # Fine-grained lib commits with feature-flag, no markers.
    (wt / "lib").mkdir()
    (wt / "lib" / "f.py").write_text("FEATURE_FLAG = feature_flag('X')\n")
    subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
    _commit(wt, "feat: small one")
    _set_origin_main(wt)
    ds = score(wt, Context(no_llm=True))
    assert ds.dim == "D8_reversibility"
    assert ds.value >= 4  # at least 4/5
    assert ds.evidence["checks_passed"] >= 4


def test_score_clamped_to_1_when_no_signals(tmp_path: Path) -> None:
    """Score floor 1 even with 0/5 signals passing (fixtures don't crash)."""
    wt = tmp_path / "wt"
    ds = score(wt, Context(no_llm=True))
    assert 1 <= ds.value <= 5
