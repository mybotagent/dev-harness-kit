"""test_side_effects_scorer.py — covers all 5 signals + aggregation."""
from __future__ import annotations

import subprocess
from pathlib import Path

from lib.behavior_scorers.side_effects import (
    _signal_no_lock_files_modified,
    _signal_no_out_of_scope_files,
    _signal_no_secret_shape_changes,
    _signal_no_unrelated_directories,
    _signal_worktree_scoped_changes,
    score,
)
from lib.behavior_scorers.types import Context


def _init_git(worktree: Path) -> None:
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


def _commit(worktree: Path, msg: str = "feat: x") -> None:
    subprocess.run(["git", "-C", str(worktree), "commit", "--allow-empty", "-q", "-m", msg], check=True)


def _add_and_commit(worktree: Path, file: Path, content: str, msg: str = "feat: x") -> None:
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(content)
    subprocess.run(["git", "-C", str(worktree), "add", "."], check=True)
    _commit(worktree, msg)


def _set_origin_main(worktree: Path) -> None:
    head = subprocess.run(
        ["git", "-C", str(worktree), "rev-parse", "main"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "-C", str(worktree), "update-ref", "refs/remotes/origin/main", head],
        check=True,
    )


def test_signal_no_out_of_scope_no_task(tmp_path: Path) -> None:
    """Vacuously 1 when no task.md."""
    wt = tmp_path / "wt"
    assert _signal_no_out_of_scope_files(wt) == 1


def test_signal_no_out_of_scope_in_scope(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    _init_git(wt)
    (wt / "task.md").write_text("update `lib/foo.py` for the auth fix\n")
    (wt / "lib").mkdir()
    (wt / "lib" / "foo.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
    _commit(wt)
    _set_origin_main(wt)
    assert _signal_no_out_of_scope_files(wt) == 1


def test_signal_no_out_of_scope_oos_file(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    _init_git(wt)
    (wt / "task.md").write_text("update `lib/foo.py`\n")
    (wt / "lib").mkdir()
    (wt / "lib" / "foo.py").write_text("x = 1\n")
    # File NOT mentioned in task.md.
    (wt / "random_other_thing.py").write_text("y = 1\n")
    subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
    _commit(wt)
    _set_origin_main(wt)
    assert _signal_no_out_of_scope_files(wt) == 0


def test_signal_no_unrelated_dirs_allowed(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    _init_git(wt)
    (wt / "lib").mkdir()
    (wt / "lib" / "foo.py").write_text("x = 1\n")
    (wt / "tests").mkdir()
    (wt / "tests" / "t.py").write_text("def test_x(): assert True\n")
    subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
    _commit(wt)
    _set_origin_main(wt)
    assert _signal_no_unrelated_directories(wt) == 1


def test_signal_no_unrelated_dirs_random_dir(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    _init_git(wt)
    (wt / "lib").mkdir()
    (wt / "lib" / "foo.py").write_text("x = 1\n")
    # An extension-less directory in root.
    (wt / "myappdir").mkdir()
    (wt / "myappdir" / "stuff.txt").write_text("hi\n")
    subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
    _commit(wt)
    _set_origin_main(wt)
    assert _signal_no_unrelated_directories(wt) == 0


def test_signal_no_lock_files_clean(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    _init_git(wt)
    (wt / "lib").mkdir()
    (wt / "lib" / "foo.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
    _commit(wt)
    _set_origin_main(wt)
    assert _signal_no_lock_files_modified(wt) == 1


def test_signal_no_lock_files_with_package_lock(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    _init_git(wt)
    _add_and_commit(wt, wt / "package-lock.json", '{}\n')
    _set_origin_main(wt)
    assert _signal_no_lock_files_modified(wt) == 0


def test_signal_no_lock_files_with_pnpm_lock(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    _init_git(wt)
    _add_and_commit(wt, wt / "pnpm-lock.yaml", "x: 1\n")
    _set_origin_main(wt)
    assert _signal_no_lock_files_modified(wt) == 0


def test_signal_no_lock_files_with_workflow_yaml(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    _init_git(wt)
    _add_and_commit(wt, wt / ".github" / "workflows" / "ci.yml", "name: x\n")
    _set_origin_main(wt)
    assert _signal_no_lock_files_modified(wt) == 0


def test_signal_no_secret_shape_clean(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    _init_git(wt)
    (wt / "lib").mkdir()
    (wt / "lib" / "foo.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
    _commit(wt)
    _set_origin_main(wt)
    assert _signal_no_secret_shape_changes(wt) == 1


def test_signal_no_secret_shape_env(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    _init_git(wt)
    _add_and_commit(wt, wt / ".env", "SECRET=x\n")
    _set_origin_main(wt)
    assert _signal_no_secret_shape_changes(wt) == 0


def test_signal_no_secret_shape_pem(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    _init_git(wt)
    _add_and_commit(wt, wt / "lib" / "server.pem", "-----BEGIN RSA\n")
    _set_origin_main(wt)
    assert _signal_no_secret_shape_changes(wt) == 0


def test_signal_no_secret_shape_secrets_dir(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    _init_git(wt)
    _add_and_commit(wt, wt / "secrets" / "x.txt", "hi\n")
    _set_origin_main(wt)
    assert _signal_no_secret_shape_changes(wt) == 0


def test_signal_worktree_scoped_no_worktrees_dir(tmp_path: Path) -> None:
    """Top-level worktree → vacuous 1."""
    wt = tmp_path / "wt"
    assert _signal_worktree_scoped_changes(wt) == 1


def test_score_full_passes(tmp_path: Path) -> None:
    """Score 5 when all five signals pass — well-formed narrow change."""
    wt = tmp_path / "wt"
    wt.mkdir()
    _init_git(wt)
    (wt / "task.md").write_text("update `lib/foo.py`\n")
    (wt / "lib").mkdir()
    (wt / "lib" / "foo.py").write_text("def foo(): return 1\n")
    subprocess.run(["git", "-C", str(wt), "add", "."], check=True)
    _commit(wt, "feat: scope-clean change")
    _set_origin_main(wt)
    ds = score(wt, Context(no_llm=True))
    assert ds.dim == "D9_side_effects"
    assert ds.value >= 4  # at least 4/5
    assert ds.evidence["checks_passed"] >= 4


def test_score_when_lock_in_diff(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    _init_git(wt)
    (wt / "task.md").write_text("do stuff\n")
    _add_and_commit(wt, wt / "lib" / "foo.py", "x=1\n")
    _add_and_commit(wt, wt / "package-lock.json", "{}\n")
    _set_origin_main(wt)
    ds = score(wt, Context(no_llm=True))
    assert ds.evidence["no_lock_files_modified"] == 0
