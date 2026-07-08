#!/usr/bin/env python3
"""test_log_skill.py — exercise /dev-kit:log skill scripts.

Verifies, for the skills/log/scripts/*.sh family:
- SKILL.md frontmatter: name=log, category=shortcuts, description non-empty
- All 4 scripts present + executable + bash-syntax-valid
- log-setup.sh: copies save_log.py + scaffolds logs/ in target
- log-on.sh: merges loghooks hooks into target's .claude/settings.json,
  tags new entries with _loghooks_managed=true, preserves user entries
- log-off.sh: strips only managed entries; user entries survive round-trip
- log-status.sh: reports managed count + captured transcript count

Tests build a fake loghooks source repo + a fake target project under
tempfile.mkdtemp() and exercise the real scripts via subprocess. No mocks.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SKILL_DIR = REPO_ROOT / "skills" / "log"
SCRIPT_DIR = SKILL_DIR / "scripts"

# Real loghooks source for the "scripts/lib.sh helpers" path:
# we always build a self-contained fake source under tmp; we do not
# depend on the user's ~/dev/loghooks being present.
SENTINEL = "_loghooks_managed"

FAKE_SETTINGS = {
    "hooks": {
        "Stop": [
            {
                "hooks": [
                    {"type": "command",
                     "command": "for i in python3 python py; do if \"$i\" -c \"\" </dev/null >/dev/null 2>&1; then exec \"$i\" \"${CLAUDE_PROJECT_DIR}/tools/save_log.py\" --tool claude-code; fi; done"}
                ]
            }
        ],
        "SessionEnd": [
            {
                "hooks": [
                    {"type": "command",
                     "command": "for i in python3 python py; do if \"$i\" -c \"\" </dev/null >/dev/null 2>&1; then exec \"$i\" \"${CLAUDE_PROJECT_DIR}/tools/save_log.py\" --tool claude-code; fi; done"}
                ]
            }
        ],
    }
}

FAKE_SAVE_LOG_PY = textwrap.dedent("""\
    #!/usr/bin/env python3
    # stub save_log.py for tests
    import sys, os, json
    payload = json.load(sys.stdin)
    sid = payload.get("session_id", "session")
    tool = sys.argv[sys.argv.index("--tool") + 1]
    os.makedirs(f"logs/{tool}", exist_ok=True)
    with open(f"logs/{tool}/{sid}.jsonl", "w") as fh:
        fh.write("")
    sys.exit(0)
""")


def _make_fake_loghooks(tmp: Path) -> Path:
    """Build a self-contained fake loghooks repo at tmp/<name>."""
    src = tmp / "loghooks"
    (src / "tools").mkdir(parents=True)
    (src / "logs" / "claude-code").mkdir(parents=True)
    (src / ".claude").mkdir(parents=True)
    (src / ".codex").mkdir(parents=True)
    (src / ".claude" / "settings.json").write_text(json.dumps(FAKE_SETTINGS))
    (src / ".codex" / "hooks.json").write_text(json.dumps(
        {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "tools/save_log.py --tool codex"}]}]}}
    ))
    (src / "tools" / "save_log.py").write_text(FAKE_SAVE_LOG_PY)
    (src / "tools" / "save_log.py").chmod(0o755)
    return src


def _make_fake_target(tmp: Path) -> Path:
    """Build a target project with a baseline user-authored hook."""
    tgt = tmp / "target"
    (tgt / ".claude").mkdir(parents=True)
    (tgt / ".codex").mkdir(parents=True)
    user_claude = {
        "hooks": {
            "UserPromptSubmit": [
                {"hooks": [{"type": "command", "command": "echo user-authored"}]}
            ]
        }
    }
    user_codex = {
        "hooks": {
            "Stop": [
                {"hooks": [{"type": "command", "command": "echo codex-user-hook"}]}
            ]
        }
    }
    (tgt / ".claude" / "settings.json").write_text(json.dumps(user_claude))
    (tgt / ".codex" / "hooks.json").write_text(json.dumps(user_codex))
    return tgt


def _run(script: str, *args: str, cwd: Path | None = None,
         env_extra: dict | None = None) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", str(SCRIPT_DIR / script), *args],
        capture_output=True, text=True, timeout=15,
        cwd=str(cwd) if cwd else None, env=env,
    )


class TestSkillFiles(unittest.TestCase):
    def test_skill_md_frontmatter(self):
        md = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
        m = re.match(r"^---\s*\n(.+?)\n---", md, re.DOTALL)
        self.assertIsNotNone(m, "SKILL.md missing frontmatter")
        fields = {}
        for line in m.group(1).splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                fields[k.strip()] = v.strip()
        self.assertEqual(fields.get("name"), "log",
                         f"name must be 'log', got {fields.get('name')!r}")
        self.assertEqual(fields.get("category"), "shortcuts",
                         f"category must be 'shortcuts', got {fields.get('category')!r}")
        self.assertTrue(fields.get("description"),
                        "description must be non-empty")
        self.assertIn("setup", fields.get("description", ""),
                      "description should mention setup/on/off")
        self.assertIn("on", fields.get("description", ""))
        self.assertIn("off", fields.get("description", ""))

    def test_all_scripts_present_executable(self):
        for s in ("lib.sh", "log-setup.sh", "log-on.sh", "log-off.sh", "log-status.sh"):
            p = SCRIPT_DIR / s
            self.assertTrue(p.exists(), f"missing: {p}")
            mode = p.stat().st_mode
            self.assertTrue(mode & stat.S_IXUSR, f"not executable: {p}")

    def test_scripts_pass_bash_syntax_check(self):
        for s in ("lib.sh", "log-setup.sh", "log-on.sh", "log-off.sh", "log-status.sh"):
            r = subprocess.run(["bash", "-n", str(SCRIPT_DIR / s)],
                               capture_output=True, text=True, timeout=5)
            self.assertEqual(r.returncode, 0,
                             f"bash syntax error in {s}: {r.stderr}")


class TestSetup(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="log-test-"))
        self.src = _make_fake_loghooks(self.tmp)
        self.tgt = _make_fake_target(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_setup_copies_script_and_scaffolds_logs(self):
        r = _run("log-setup.sh", "--target", str(self.tgt),
                 env_extra={"LOGHOOKS_DIR": str(self.src)})
        self.assertEqual(r.returncode, 0,
                         f"setup failed:\nstdout={r.stdout}\nstderr={r.stderr}")
        self.assertTrue((self.tgt / "tools" / "save_log.py").exists(),
                        "tools/save_log.py not copied")
        self.assertTrue(os.access(self.tgt / "tools" / "save_log.py", os.X_OK),
                        "copied save_log.py not executable")
        self.assertTrue((self.tgt / "logs" / "claude-code").is_dir(),
                        "logs/claude-code/ not created")
        self.assertTrue((self.tgt / "logs" / "codex").is_dir(),
                        "logs/codex/ not created")
        self.assertTrue((self.tgt / "logs" / ".gitignore").exists(),
                        "logs/.gitignore not written")

    def test_setup_is_idempotent(self):
        for _ in range(2):
            r = _run("log-setup.sh", "--target", str(self.tgt),
                     env_extra={"LOGHOOKS_DIR": str(self.src)})
            self.assertEqual(r.returncode, 0, f"setup failed: {r.stderr}")
        self.assertTrue((self.tgt / "tools" / "save_log.py").exists())


class TestOnOffRoundTrip(unittest.TestCase):
    """End-to-end: setup -> on merges hooks -> off strips them; user hooks survive."""

    BASELINE_CLAUDE = {
        "hooks": {
            "UserPromptSubmit": [
                {"hooks": [{"type": "command", "command": "echo user-authored"}]}
            ]
        }
    }
    BASELINE_CODEX = {
        "hooks": {
            "Stop": [
                {"hooks": [{"type": "command", "command": "echo codex-user-hook"}]}
            ]
        }
    }

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="log-test-"))
        self.src = _make_fake_loghooks(self.tmp)
        self.tgt = _make_fake_target(self.tmp)
        # baseline user hooks on disk
        (self.tgt / ".claude" / "settings.json").write_text(json.dumps(self.BASELINE_CLAUDE))
        (self.tgt / ".codex" / "hooks.json").write_text(json.dumps(self.BASELINE_CODEX))
        # setup must run before on
        r = _run("log-setup.sh", "--target", str(self.tgt),
                 env_extra={"LOGHOOKS_DIR": str(self.src)})
        self.assertEqual(r.returncode, 0, f"setup failed: {r.stderr}")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _managed_count(self, path: Path) -> int:
        if not path.exists():
            return 0
        data = json.loads(path.read_text())
        n = 0
        for event_entries in (data.get("hooks") or {}).values():
            for entry in event_entries:
                if isinstance(entry, dict) and entry.get(SENTINEL) is True:
                    n += 1
        return n

    def _user_event_signatures(self, path: Path, event: str) -> list[str]:
        data = json.loads(path.read_text()) if path.exists() else {}
        out = []
        for entry in (data.get("hooks") or {}).get(event, []):
            cmds = [h.get("command") for h in entry.get("hooks", [])]
            out.append(tuple(cmds))
        return out

    def test_on_merges_and_tags_managed_entries(self):
        r = _run("log-on.sh", "--target", str(self.tgt),
                 env_extra={"LOGHOOKS_DIR": str(self.src)})
        self.assertEqual(r.returncode, 0, f"on failed:\n{r.stderr}")

        claude_path = self.tgt / ".claude" / "settings.json"
        data = json.loads(claude_path.read_text())
        # managed entries should now exist for Stop + SessionEnd
        self.assertGreaterEqual(self._managed_count(claude_path), 2,
                                "managed entries missing after on")
        # user-authored hook must survive
        ups = self._user_event_signatures(claude_path, "UserPromptSubmit")
        self.assertIn(('echo user-authored',), ups,
                      "user-authored UserPromptSubmit hook was lost on on")

        # every managed entry must carry the sentinel
        for event, entries in (data.get("hooks") or {}).items():
            for entry in entries:
                if any(h.get("command", "").endswith("save_log.py --tool claude-code")
                       for h in entry.get("hooks", [])):
                    self.assertIs(entry.get(SENTINEL), True,
                                  f"managed entry in {event} missing sentinel")

    def test_on_off_round_trip_restores_baseline(self):
        # ON
        r = _run("log-on.sh", "--target", str(self.tgt),
                 env_extra={"LOGHOOKS_DIR": str(self.src)})
        self.assertEqual(r.returncode, 0, f"on failed: {r.stderr}")
        self.assertGreater(self._managed_count(self.tgt / ".claude" / "settings.json"), 0)

        # OFF
        r = _run("log-off.sh", "--target", str(self.tgt))
        self.assertEqual(r.returncode, 0, f"off failed: {r.stderr}")

        # managed entries should all be gone
        self.assertEqual(self._managed_count(self.tgt / ".claude" / "settings.json"), 0,
                         "managed entries not stripped")
        self.assertEqual(self._managed_count(self.tgt / ".codex" / "hooks.json"), 0,
                         "codex managed entries not stripped")

        # user-authored hooks must survive
        claude_path = self.tgt / ".claude" / "settings.json"
        codex_path = self.tgt / ".codex" / "hooks.json"
        ups_before = self._user_event_signatures(
            Path("/dev/null").parent if False else Path(tempfile.gettempdir()) / "never.json",
            "UserPromptSubmit")  # placeholder; not used
        # Compare against the baseline we wrote in setUp
        self.assertEqual(self._user_event_signatures(claude_path, "UserPromptSubmit"),
                         [(("echo user-authored",))],
                         "user hook lost after on/off round-trip")
        self.assertEqual(self._user_event_signatures(codex_path, "Stop"),
                         [(("echo codex-user-hook",))],
                         "codex user hook lost after on/off round-trip")

        # baseline hooks key must still exist (off does not delete the whole file)
        claude_data = json.loads(claude_path.read_text())
        self.assertIn("UserPromptSubmit", claude_data.get("hooks", {}),
                      "off stripped the hooks key entirely")

    def test_on_is_idempotent_no_duplicate_entries(self):
        for _ in range(3):
            r = _run("log-on.sh", "--target", str(self.tgt),
                     env_extra={"LOGHOOKS_DIR": str(self.src)})
            self.assertEqual(r.returncode, 0, f"on failed: {r.stderr}")
        # Each event should contain exactly one entry per source command.
        claude = json.loads((self.tgt / ".claude" / "settings.json").read_text())
        for event, entries in (claude.get("hooks") or {}).items():
            cmds = []
            for entry in entries:
                for h in entry.get("hooks", []):
                    cmds.append(h.get("command"))
            self.assertEqual(len(cmds), len(set(cmds)),
                             f"duplicate hook commands in event {event}: {cmds}")

    def test_on_refuses_when_setup_missing(self):
        # fresh target, no setup
        fresh_tmp = Path(tempfile.mkdtemp(prefix="log-test-fresh-"))
        try:
            (fresh_tmp / "target" / ".claude").mkdir(parents=True)
            (fresh_tmp / "target" / ".codex").mkdir(parents=True)
            tgt = fresh_tmp / "target"
            r = _run("log-on.sh", "--target", str(tgt),
                     env_extra={"LOGHOOKS_DIR": str(self.src)})
            self.assertNotEqual(r.returncode, 0, "on should refuse when setup missing")
            self.assertIn("setup", (r.stderr + r.stdout).lower(),
                          "error message should mention setup")
        finally:
            shutil.rmtree(fresh_tmp, ignore_errors=True)


class TestStatus(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="log-test-"))
        self.src = _make_fake_loghooks(self.tmp)
        self.tgt = _make_fake_target(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_status_reports_zero_when_off(self):
        r = _run("log-status.sh", "--target", str(self.tgt))
        self.assertEqual(r.returncode, 0, f"status failed: {r.stderr}")
        self.assertIn("managed=0", r.stdout,
                      f"status should report managed=0 when off\n{r.stdout}")
        self.assertIn("MISSING", r.stdout,
                      "status should flag missing tools/save_log.py when not set up")

    def test_status_reports_managed_count_after_on(self):
        _run("log-setup.sh", "--target", str(self.tgt),
             env_extra={"LOGHOOKS_DIR": str(self.src)})
        _run("log-on.sh", "--target", str(self.tgt),
             env_extra={"LOGHOOKS_DIR": str(self.src)})
        r = _run("log-status.sh", "--target", str(self.tgt))
        self.assertEqual(r.returncode, 0, f"status failed: {r.stderr}")
        m = re.search(r"managed=(\d+)", r.stdout)
        self.assertIsNotNone(m, f"managed= missing in status:\n{r.stdout}")
        self.assertGreater(int(m.group(1)), 0,
                           "managed count should be > 0 after on")


if __name__ == "__main__":
    unittest.main()