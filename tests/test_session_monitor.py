#!/usr/bin/env python3
"""test_session_monitor.py — unit tests for the /dev-kit:session-monitor tool.

Covers the pure logic (status derivation, process attribution, agent-graph
builder, process/worktree mapping, resume-command builder, session
collection, picker row construction). The interactive picker and the
os.execvp resume hand-off require a real TTY and are verified manually
per the skill doc.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

import session_monitor as sm  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "session_monitor"
NOW = datetime(2026, 7, 16, 12, 0, 0, tzinfo=timezone.utc)


def _agg(**kw):
    base = {"session_id": "s", "source": "claude-code", "worktree": "(main)",
            "branch": "main", "model": "m", "last_ts": NOW,
            "tool_counts": {}, "log_path": ""}
    base.update(kw)
    return base


class FakeCompleted:
    def __init__(self, stdout="", returncode=0):
        self.stdout = stdout
        self.returncode = returncode


class TestDeriveStatus(unittest.TestCase):
    def test_recent_turn_is_live(self):
        agg = _agg(last_ts=NOW - timedelta(seconds=60))
        self.assertIs(sm.derive_status(agg, "main", NOW), sm.Status.LIVE)

    def test_old_turn_is_idle(self):
        agg = _agg(last_ts=NOW - timedelta(minutes=30))
        self.assertIs(sm.derive_status(agg, "main", NOW), sm.Status.IDLE)

    def test_merged_worktree_is_stale(self):
        agg = _agg(last_ts=NOW)  # recent, but worktree merged
        self.assertIs(sm.derive_status(agg, "merged", NOW), sm.Status.STALE)

    def test_gone_worktree_is_stale(self):
        self.assertIs(sm.derive_status(_agg(), "gone", NOW), sm.Status.STALE)

    def test_missing_last_ts_is_idle(self):
        self.assertIs(sm.derive_status(_agg(last_ts=None), "live", NOW),
                      sm.Status.IDLE)


class TestAttachLiveProcesses(unittest.TestCase):
    def _sess(self, sid, wt, ts, status):
        return sm.Session(agg=_agg(session_id=sid, worktree=wt, last_ts=ts),
                          worktree_state="live", status=status)

    def test_newest_nonstale_session_gets_process(self):
        old = self._sess("old", "wt", NOW - timedelta(hours=5), sm.Status.IDLE)
        new = self._sess("new", "wt", NOW - timedelta(hours=1), sm.Status.IDLE)
        sm.attach_live_processes([old, new], {"wt": [4242]})
        self.assertIs(new.status, sm.Status.LIVE)
        self.assertEqual(new.pids, [4242])
        self.assertIs(old.status, sm.Status.IDLE)
        self.assertEqual(old.pids, [])

    def test_stale_session_never_elevated(self):
        stale = self._sess("s", "wt", NOW, sm.Status.STALE)
        sm.attach_live_processes([stale], {"wt": [1]})
        self.assertIs(stale.status, sm.Status.STALE)
        self.assertEqual(stale.pids, [])

    def test_no_pids_no_change(self):
        s = self._sess("s", "wt", NOW, sm.Status.IDLE)
        sm.attach_live_processes([s], {"other": [1]})
        self.assertIs(s.status, sm.Status.IDLE)


class TestAgentGraph(unittest.TestCase):
    def test_cc_two_subagents(self):
        g = sm.build_agent_graph(FIXTURES / "cc-subagents.jsonl")
        self.assertEqual(len(g.nodes), 2)
        self.assertEqual(g.nodes[0].subagent_type, "Explore")
        self.assertEqual(g.nodes[0].description, "scan the API layer")
        self.assertEqual(g.nodes[0].turn_count, 2)   # s1a, s1b
        self.assertEqual(g.nodes[1].subagent_type, "Plan")
        self.assertEqual(g.nodes[1].turn_count, 3)   # s2a, s2b, s2c
        self.assertIn("two helpers", g.root_user_prompt)

    def test_codex_has_no_subagents(self):
        g = sm.build_agent_graph(FIXTURES / "codex-plain.jsonl")
        self.assertEqual(g.nodes, [])

    def test_missing_file_is_empty(self):
        g = sm.build_agent_graph(FIXTURES / "does-not-exist.jsonl")
        self.assertEqual(g.nodes, [])


class TestProcessDetection(unittest.TestCase):
    def test_is_cli_process(self):
        self.assertTrue(sm._is_cli_process("claude --dangerously-skip-permissions"))
        self.assertTrue(sm._is_cli_process("/usr/local/bin/codex resume abc"))
        self.assertFalse(sm._is_cli_process("/bin/zsh -c 'echo claude'"))
        self.assertFalse(sm._is_cli_process("Claude.app/Contents/MacOS/Claude"))

    def test_is_resume_process(self):
        self.assertTrue(sm._is_resume_process("claude -r"))
        self.assertTrue(sm._is_resume_process("claude --resume abc"))
        self.assertTrue(sm._is_resume_process("codex resume abc"))
        self.assertFalse(sm._is_resume_process("claude --print"))

    def test_list_cli_processes_filters(self):
        def runner(cmd, **kw):
            return FakeCompleted(
                "  100 claude --dangerously-skip-permissions\n"
                "  101 /bin/zsh -c something\n"
                "  102 codex resume xyz\n")
        procs = sm.list_cli_processes(runner=runner)
        pids = {p["pid"] for p in procs}
        self.assertEqual(pids, {100, 102})
        codex = next(p for p in procs if p["pid"] == 102)
        self.assertTrue(codex["is_resume"])

    def test_list_cli_processes_missing_binary(self):
        def runner(cmd, **kw):
            raise FileNotFoundError("ps")
        self.assertEqual(sm.list_cli_processes(runner=runner), [])

    def test_pid_cwd_parses_lsof(self):
        def runner(cmd, **kw):
            return FakeCompleted("p100\nfcwd\nn/repo/.worktrees/foo\n")
        self.assertEqual(sm.pid_cwd(100, runner=runner),
                         Path("/repo/.worktrees/foo"))

    def test_map_processes_drops_outside_repo(self):
        wt_paths = {"(main)": Path("/repo"),
                    "foo": Path("/repo/.worktrees/foo")}

        def runner(cmd, **kw):
            if cmd[0] == "lsof":
                pid = cmd[cmd.index("-p") + 1]
                mapping = {"1": "/repo/.worktrees/foo/src",
                           "2": "/somewhere/else"}
                return FakeCompleted(f"p{pid}\nfcwd\nn{mapping[pid]}\n")
            return FakeCompleted("")
        procs = [{"pid": 1, "command": "claude", "is_resume": False},
                 {"pid": 2, "command": "claude", "is_resume": False}]
        result = sm.map_processes_to_worktrees(procs, wt_paths, runner=runner)
        self.assertEqual(result, {"foo": [1]})  # pid 2 (other repo) dropped


class TestBuildResume(unittest.TestCase):
    def test_claude_argv_in_worktree(self):
        with tempfile.TemporaryDirectory() as d:
            wt = Path(d)
            cwd, argv, warn = sm.build_resume(
                _agg(session_id="abc", source="claude-code"),
                Path("/repo"), wt)
            self.assertEqual(argv, ["claude", "--resume", "abc"])
            self.assertEqual(cwd, wt)
            self.assertIsNone(warn)

    def test_codex_argv(self):
        with tempfile.TemporaryDirectory() as d:
            cwd, argv, warn = sm.build_resume(
                _agg(session_id="xyz", source="codex"), Path("/repo"), Path(d))
            self.assertEqual(argv, ["codex", "resume", "xyz"])

    def test_gone_worktree_falls_back_to_main(self):
        cwd, argv, warn = sm.build_resume(
            _agg(session_id="abc", worktree="ghost"), Path("/repo"), None)
        self.assertEqual(cwd, Path("/repo"))
        self.assertIsNotNone(warn)
        self.assertIn("ghost", warn)


class TestCollectSessions(unittest.TestCase):
    def test_collects_cc_and_codex(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            logs = root / "logs"
            (logs / "claude-code" / "feat-x").mkdir(parents=True)
            (logs / "codex" / "main").mkdir(parents=True)
            shutil.copy(FIXTURES / "cc-subagents.jsonl",
                        logs / "claude-code" / "feat-x" / "cc-subagents.jsonl")
            shutil.copy(FIXTURES / "codex-plain.jsonl",
                        logs / "codex" / "main" / "019f-codex-plain.jsonl")
            aggs = sm.collect_sessions(root, logs, "", 3650)
            sources = {a["source"] for a in aggs}
            self.assertEqual(sources, {"claude-code", "codex"})
            self.assertEqual(len(aggs), 2)


class TestPrintResumeCommand(unittest.TestCase):
    """Dry-run path: --print-resume-command prints the cwd + argv that
    Enter would have exec'd, without entering the picker or calling exec.
    Lets CI verify the resume-argv synthesis + worktree resolution."""

    def _run(self, repo_root: Path, logs_dir: Path, days: int = 3650) -> str:
        import io
        from contextlib import redirect_stdout, redirect_stderr
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(io.StringIO()):
            original = sm.discover_repo_root
            sm.discover_repo_root = lambda *a, **kw: repo_root
            try:
                rc = sm.main([
                    "--logs-dir", str(logs_dir),
                    "--days", str(days),
                    "--print-resume-command",
                ])
            finally:
                sm.discover_repo_root = original
        self.assertEqual(rc, 0)
        return buf.getvalue()

    def test_claude_session(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            logs = root / "logs"
            (logs / "claude-code" / "feat-x").mkdir(parents=True)
            shutil.copy(FIXTURES / "cc-subagents.jsonl",
                        logs / "claude-code" / "feat-x" / "cc-subagents.jsonl")
            out = self._run(root, logs)
        self.assertIn("cd ", out)
        self.assertIn("--resume", out)
        self.assertIn("cc-subagents", out)

    def test_codex_session(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            logs = root / "logs"
            (logs / "codex" / "main").mkdir(parents=True)
            shutil.copy(FIXTURES / "codex-plain.jsonl",
                        logs / "codex" / "main" / "019f-codex-plain.jsonl")
            out = self._run(root, logs)
        self.assertIn("codex", out)
        self.assertIn("resume", out)
        self.assertIn("019f-codex-plain", out)

    def test_no_sessions(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            logs = root / "logs"
            logs.mkdir()
            import io
            from contextlib import redirect_stdout, redirect_stderr
            buf = io.StringIO()
            with redirect_stdout(buf), redirect_stderr(io.StringIO()):
                original = sm.discover_repo_root
                sm.discover_repo_root = lambda *a, **kw: root
                try:
                    rc = sm.main([
                        "--logs-dir", str(logs),
                        "--days", "3650",
                        "--print-resume-command",
                    ])
                finally:
                    sm.discover_repo_root = original
        self.assertEqual(rc, 0)
        self.assertIn("no sessions", buf.getvalue())


class TestPickerRows(unittest.TestCase):
    """Pure-logic tests for the inline-picker row builder + cursor movement."""

    def _sess(self, sid="s", wt="(main)", status=sm.Status.IDLE):
        return sm.Session(
            agg=_agg(session_id=sid, worktree=wt, last_ts=NOW),
            worktree_state="live", status=status)

    def _model(self):
        return [
            sm.WorktreeInfo("alpha", "live", None,
                            [self._sess("a1"), self._sess("a2")]),
            sm.WorktreeInfo("beta", "live", None,
                            [self._sess("b1")]),
        ]

    def test_build_rows_alternates_header_then_sessions(self):
        rows = sm.build_rows(self._model(), now=NOW)
        self.assertEqual(len(rows), 2 + 3)
        self.assertEqual([r["kind"] for r in rows],
                         ["header", "session", "session",
                          "header", "session"])
        self.assertIn("alpha", rows[0]["text"])
        self.assertEqual(rows[1]["session"].session_id, "a1")

    def test_build_rows_skips_agt_marker_when_no_subagents(self):
        rows = sm.build_rows(self._model(), now=NOW)
        for r in rows:
            if r["kind"] == "session":
                self.assertNotIn("+0agt", r["text"])
                self.assertNotIn("+1agt", r["text"])

    def test_selectable_indices_contains_only_sessions(self):
        rows = sm.build_rows(self._model(), now=NOW)
        idx = sm._selectable_indices(rows)
        self.assertEqual(idx, [1, 2, 4])
        for i in idx:
            self.assertEqual(rows[i]["kind"], "session")

    def test_move_selectable_never_lands_on_header(self):
        rows = sm.build_rows(self._model(), now=NOW)
        for start in (1, 2, 4):
            for delta in (-3, -1, +1, +5):
                moved = sm._move_selectable(rows, start, delta)
                self.assertEqual(rows[moved]["kind"], "session")

    def test_move_selectable_clamps_at_edges(self):
        rows = sm.build_rows(self._model(), now=NOW)
        self.assertEqual(sm._move_selectable(rows, 1, -10), 1)
        self.assertEqual(sm._move_selectable(rows, 4, +10), 4)

    def test_move_selectable_from_header_lands_on_nearest_session(self):
        rows = sm.build_rows(self._model(), now=NOW)
        # cursor on the "beta" header (row 3) moving down -> first beta session
        self.assertEqual(sm._move_selectable(rows, 3, +1), 4)
        # cursor on the "beta" header moving up -> last alpha session
        self.assertEqual(sm._move_selectable(rows, 3, -1), 2)

    def test_render_picker_writes_ansi_for_each_row(self):
        import io
        rows = sm.build_rows(self._model(), now=NOW)
        buf = io.StringIO()
        sm._render_picker(buf, rows, cursor=1, scroll=0, max_x=80, max_y=10)
        out = buf.getvalue()
        # header rendered, cursor row reverse-video'd
        self.assertIn("session-monitor", out)
        self.assertIn("\x1b[7m", out)  # reverse video on cursor row
        self.assertIn("\x1b[2m", out)  # dim worktree header
        # 5 visible rows + body_h=8 => 3 padding clear-lines to pin the footer
        self.assertEqual(out.count("\x1b[K"), 3)
        self.assertGreaterEqual(out.count("\n"), 5)

    def test_render_picker_no_padding_when_body_filled(self):
        import io
        rows = sm.build_rows(self._model(), now=NOW)
        buf = io.StringIO()
        # body_h = max_y - 2 = 5, exactly fits the 5 visible rows -> no padding
        sm._render_picker(buf, rows, cursor=1, scroll=0, max_x=80, max_y=7)
        out = buf.getvalue()
        self.assertNotIn("\x1b[K", out)


class TestEnrichBranches(unittest.TestCase):
    """Branch enrichment: override the log-captured branch with the
    worktree's current ``git rev-parse --abbrev-ref HEAD``. Verified with a
    real git repo in a tempdir (no mocking) so subprocess / git edge cases
    are exercised."""

    def _git(self, root: Path, *args: str) -> None:
        subprocess.run(["git", "-C", str(root), *args],
                       check=True, capture_output=True, text=True)

    def _init_repo(self, root: Path, branch: str) -> None:
        self._git(root, "init", "-q", "-b", branch)
        self._git(root, "config", "user.email", "x@example.com")
        self._git(root, "config", "user.name", "x")
        (root / "f").write_text("x")
        self._git(root, "add", ".")
        self._git(root, "commit", "-q", "-m", "i")

    def test_enrich_overrides_logged_branch(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._init_repo(root, "feat-x")
            # log says "main" (stale), worktree is actually on feat-x
            sess = sm.Session(
                agg=_agg(branch="main"),
                worktree_state="live", status=sm.Status.IDLE, wt_path=root,
            )
            sm._enrich_branches_from_worktrees([sess], runner=subprocess.run)
            self.assertEqual(sess.branch, "feat-x")

    def test_enrich_skips_stale_worktrees(self):
        sess = sm.Session(
            agg=_agg(branch="main"),
            worktree_state="merged", status=sm.Status.STALE,
        )
        sm._enrich_branches_from_worktrees([sess], runner=subprocess.run)
        self.assertEqual(sess.branch, "main")  # log branch preserved

    def test_enrich_skips_missing_wt_path(self):
        sess = sm.Session(
            agg=_agg(branch="main"),
            worktree_state="live", status=sm.Status.IDLE, wt_path=None,
        )
        sm._enrich_branches_from_worktrees([sess], runner=subprocess.run)
        self.assertEqual(sess.branch, "main")

    def test_enrich_keeps_log_on_non_git_path(self):
        with tempfile.TemporaryDirectory() as d:
            sess = sm.Session(
                agg=_agg(branch="main"),
                worktree_state="live", status=sm.Status.IDLE,
                wt_path=Path(d),  # not a git repo
            )
            sm._enrich_branches_from_worktrees([sess], runner=subprocess.run)
            self.assertEqual(sess.branch, "main")

    def test_enrich_skips_detached_head(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            self._init_repo(root, "feat-x")
            self._git(root, "checkout", "--quiet", "--detach")
            sess = sm.Session(
                agg=_agg(branch="main"),
                worktree_state="live", status=sm.Status.IDLE, wt_path=root,
            )
            sm._enrich_branches_from_worktrees([sess], runner=subprocess.run)
            # detached -> "HEAD" sentinel -> log branch preserved
            self.assertEqual(sess.branch, "main")


class TestPrintJson(unittest.TestCase):
    """--json emits the AskUserQuestion-flow contract: stable top-level keys
    + full session_id + worktree abs path so the skill can synthesize the
    resume command without re-running the tool."""

    def _run(self, repo_root: Path, logs_dir: Path) -> dict:
        import io
        from contextlib import redirect_stdout, redirect_stderr
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(io.StringIO()):
            original = sm.discover_repo_root
            sm.discover_repo_root = lambda *a, **kw: repo_root
            try:
                rc = sm.main([
                    "--logs-dir", str(logs_dir),
                    "--days", "3650",
                    "--json",
                ])
            finally:
                sm.discover_repo_root = original
        self.assertEqual(rc, 0)
        return json.loads(buf.getvalue())

    def test_claude_session_full_id_and_path(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            logs = root / "logs"
            (logs / "claude-code" / "feat-x").mkdir(parents=True)
            shutil.copy(FIXTURES / "cc-subagents.jsonl",
                        logs / "claude-code" / "feat-x" / "cc-subagents.jsonl")
            payload = self._run(root, logs)
        self.assertEqual(set(payload.keys()),
                         {"logs_dir", "generated_at", "total_sessions",
                          "live_sessions", "worktrees"})
        self.assertEqual(payload["total_sessions"], 1)
        # Without a real worktree in the tempdir, worktree_from_path falls
        # back to the (main) sentinel. The exact mapping is verified by
        # the live runtime; here we just confirm the JSON shape is stable.
        wt = payload["worktrees"][0]
        self.assertEqual(wt["name"], "(main)")
        self.assertTrue(wt["sessions"])
        sess = wt["sessions"][0]
        self.assertEqual(sess["source"], "claude-code")
        # fixture's last_ts is ~2h before NOW, so it falls outside the
        # 180s LIVE window and lands as IDLE. Status transitions are
        # covered by TestDeriveStatus; here we only assert shape.
        self.assertEqual(sess["status"], "idle")
        self.assertIn("-", sess["session_id"])  # full UUID, not truncated
        self.assertTrue(sess["log_path"].endswith("cc-subagents.jsonl"))

    def test_codex_session_status_round_trips(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            logs = root / "logs"
            (logs / "codex" / "main").mkdir(parents=True)
            shutil.copy(FIXTURES / "codex-plain.jsonl",
                        logs / "codex" / "main" / "019f-codex-plain.jsonl")
            payload = self._run(root, logs)
        sess = payload["worktrees"][0]["sessions"][0]
        self.assertEqual(sess["source"], "codex")
        self.assertEqual(sess["status"], "idle")  # fixture is older than window
        self.assertTrue(sess["last_rel"].endswith("ago"))

    def test_empty_logs_emits_zero_totals(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            logs = root / "logs"
            logs.mkdir()
            payload = self._run(root, logs)
        self.assertEqual(payload["total_sessions"], 0)
        self.assertEqual(payload["live_sessions"], 0)
        self.assertEqual(payload["worktrees"], [])


if __name__ == "__main__":
    unittest.main()
