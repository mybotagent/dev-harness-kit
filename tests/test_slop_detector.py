#!/usr/bin/env python3
"""test_slop_detector.py — regression for the v2 hook.

Verifies hooks/slop-detector.sh across tiers:

    - clean input -> exit 0, empty stderr
    - HIGH EN phrase cluster -> HIGH bucket
    - HIGH KO structure -> HIGH bucket
    - T2 structure catch (binary contrast) -> at least MEDIUM
    - T2 structure catch (Wh-starter) -> LOW bucket on a single finding
    - lockfile path skip -> exit 0, no scan
    - missing bank files -> falls back to v1 inline bank, prints WARN to stderr
    - sample-with-slop.md (regression fixture) -> HIGH
    - sample-clean.md (regression fixture)   -> 0 findings

We drive the script as a black box, the same way Claude Code does:
    stdin  : PostToolUse payload JSON
    stdout : empty (advisory)
    stderr : advisory text

No mocks. jq must be available on $PATH (same constraint as the hook itself).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
HOOK = REPO_ROOT / "hooks" / "slop-detector.sh"
PHRASES_BANK = REPO_ROOT / "hooks" / "references" / "slop" / "phrases.md"
STRUCTURES_BANK = REPO_ROOT / "hooks" / "references" / "slop" / "structures.md"
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "slop"


def _require_jq() -> None:
    if shutil.which("jq") is None:
        raise unittest.SkipTest("jq is required on $PATH for slop-detector tests")


def _payload(file_path: str, content: str) -> str:
    return json.dumps({"tool_input": {"file_path": file_path, "content": content}})


def run_hook(content: str, *, file_path: str = "test.md", env_extra: dict | None = None) -> subprocess.CompletedProcess:
    """Invoke the hook with a PostToolUse payload and capture output."""
    _require_jq()
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = str(REPO_ROOT)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [str(HOOK)],
        input=_payload(file_path, content),
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )


def severity_of(stderr: str) -> str:
    for sev in ("HIGH", "MEDIUM", "LOW"):
        if f"[slop-detector] {sev}" in stderr:
            return sev
    return "OK"


class CleanBaseline(unittest.TestCase):
    def test_clean_md_passes(self) -> None:
        proc = run_hook(
            "We shipped HMAC signing for webhooks. "
            "Secret lives in env, SDK wraps it, verify endpoint rejects in 2 ms. "
            "PR is up; review by EOD."
        )
        self.assertEqual(proc.returncode, 0, msg=f"exit={proc.returncode} stderr={proc.stderr}")
        self.assertEqual(proc.stdout, "")
        self.assertEqual(severity_of(proc.stderr), "OK")


class HighEnglishCluster(unittest.TestCase):
    def test_phrase_flood_triggers_high(self) -> None:
        content = (
            "In today's fast-paced landscape, we need to lean into uncertainty "
            "and navigate these complexities with a holistic approach. "
            "Its worth noting that robust and comprehensive changes are seamless "
            "and empower stakeholders."
        )
        proc = run_hook(content)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertEqual(severity_of(proc.stderr), "HIGH")
        # unique T1 phrase markers we expect to surface
        for marker in ("lean into", "robust", "comprehensive", "empower", "landscape"):
            self.assertIn(marker, proc.stderr.lower())


class HighKoreanStructure(unittest.TestCase):
    def test_ko_cluster_triggers_high(self) -> None:
        content = (
            "오늘날의 빠르게 변하는 시대에 우리는 종합적인 분석을 통해 강력한 기능을 도입했습니다. "
            "다양한 이점들이 있습니다. 핵심적으로 성능이 향상되었습니다."
        )
        proc = run_hook(content)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(severity_of(proc.stderr), "HIGH")
        # KO markers present
        for marker in ("오늘날의", "종합적인", "강력한"):
            self.assertIn(marker, proc.stderr)

    def test_ko_structure_alone_triggers_high(self) -> None:
        """A sentence that only carries KO structural crutches (no KO T1 phrases)
        must still escalate to HIGH via the KO-T2 branch. Plain ASCII characters
        would NOT trigger this path; the KO structure is the whole signal."""
        content = "이것 때문에 우리는 잘못된 결정을 내렸습니다. 반드시 기억하시기 바랍니다."
        proc = run_hook(content)
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertEqual(
            severity_of(proc.stderr), "HIGH",
            msg=f"KO structure alone should be HIGH; stderr={proc.stderr}",
        )


class StructureShapes(unittest.TestCase):
    def test_binary_contrast_is_at_least_medium(self) -> None:
        content = "The answer is not A. It's B. It feels like X. It's actually Y."
        proc = run_hook(content)
        self.assertEqual(proc.returncode, 0)
        sev = severity_of(proc.stderr)
        self.assertIn(sev, {"MEDIUM", "HIGH"}, msg=f"got {sev}; stderr={proc.stderr}")

    def test_wh_starter_yields_low_or_higher(self) -> None:
        content = "What makes this hard is the constraint. When in doubt, we ship."
        proc = run_hook(content)
        self.assertEqual(proc.returncode, 0)
        # Wh-starter at sentence start is a T1 hit -> at least LOW
        sev = severity_of(proc.stderr)
        self.assertIn(sev, {"LOW", "MEDIUM", "HIGH"})


class Scoping(unittest.TestCase):
    def test_lockfile_path_is_skipped(self) -> None:
        proc = run_hook("any content", file_path="package-lock.json")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr.strip(), "")
        self.assertEqual(proc.stdout.strip(), "")

    def test_minified_path_is_skipped(self) -> None:
        proc = run_hook("any content", file_path="app.min.js")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stderr.strip(), "")


class StrictMode(unittest.TestCase):
    def test_high_with_slop_strict_exits_2(self) -> None:
        content = (
            "In today's fast-paced landscape, we need to lean into uncertainty "
            "and navigate these complexities with a holistic approach. "
            "Its worth noting that robust and comprehensive changes are seamless "
            "and empower stakeholders."
        )
        proc = run_hook(content, env_extra={"SLOP_STRICT": "1"})
        # Strict mode exits 2 on HIGH
        self.assertEqual(proc.returncode, 2, msg=f"exit={proc.returncode} stderr={proc.stderr}")
        self.assertEqual(severity_of(proc.stderr), "HIGH")


class BankFallback(unittest.TestCase):
    def test_inline_fallback_when_banks_missing(self) -> None:
        # Defensive: if the references/ bank is ever removed, hook must still fire on
        # legacy v1 phrases (e.g. "Certainly!"). We simulate by pointing CLAUDE_PLUGIN_ROOT
        # at a temp dir without references/, with the hook exposed there.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            tmp_hook = tmp_path / "slop-detector.sh"
            shutil.copy(str(HOOK), str(tmp_hook))
            # slop-detector.sh now sources ${BASH_SOURCE[0]%/*}/lib/payload-parse.sh;
            # the test fixture copies both the hook AND its lib/ sibling so the
            # `require_jq`/`read_stdin_json`/`extract_content` helpers are
            # available. The fallback we exercise is the missing-`references/slop/`
            # path (v1 inline bank), NOT a broken-payload path.
            shutil.copytree(
                REPO_ROOT / "hooks" / "lib",
                tmp_path / "lib",
                symlinks=True,
            )
            # no references/ dir — fallback path
            content = "Certainly! This is a robust and comprehensive solution."
            payload = json.dumps({"tool_input": {"file_path": "test.md", "content": content}})
            proc = subprocess.run(
                [str(tmp_hook)],
                input=payload,
                capture_output=True,
                text=True,
                env={**os.environ, "CLAUDE_PLUGIN_ROOT": tmp, "PATH": os.environ["PATH"]},
                timeout=10,
            )
            self.assertEqual(proc.returncode, 0, msg=proc.stderr)
            self.assertIn("WARN", proc.stderr)
            self.assertIn("[slop-detector]", proc.stderr)
            # v1 inline bank still catches "robust" / "comprehensive"
            self.assertTrue(
                any(tok in proc.stderr for tok in ("robust", "comprehensive")),
                msg=f"fallback did not flag legacy phrases: {proc.stderr}",
            )


class RegressionFixtures(unittest.TestCase):
    """The fixtures referenced by skills/audit-slop/SKILL.md and the bank README."""

    def test_sample_with_slop_is_high(self) -> None:
        path = FIXTURE_DIR / "sample-with-slop.md"
        self.assertTrue(path.exists(), f"missing fixture: {path}")
        text = path.read_text(encoding="utf-8")
        proc = run_hook(text, file_path=str(path.name))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(severity_of(proc.stderr), "HIGH")

    def test_sample_clean_is_silent(self) -> None:
        path = FIXTURE_DIR / "sample-clean.md"
        self.assertTrue(path.exists(), f"missing fixture: {path}")
        text = path.read_text(encoding="utf-8")
        proc = run_hook(text, file_path=str(path.name))
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout.strip(), "")
        self.assertEqual(proc.stderr.strip(), "")


class BankFileInvariants(unittest.TestCase):
    """The bank files are loaded by `grep -oE -f <(... filter ...)`. They must:
       - be readable,
       - contain at least 20 non-comment, non-blank lines,
       - contain no POSIX-unfriendly escape (\\b, \\m, \\s, \\d, \\w)
         because BSD grep / ugrep on macOS reject these in ERE mode.
    """

    def _assert_bank_loadable(self, path: Path, *, min_lines: int) -> None:
        self.assertTrue(path.exists(), f"missing bank file: {path}")
        text = path.read_text(encoding="utf-8")
        loadable_lines = [
            line for line in text.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertGreaterEqual(
            len(loadable_lines), min_lines,
            msg=f"{path.name}: only {len(loadable_lines)} loadable lines (>= {min_lines} required)",
        )

        # Portable ERE: only allow POSIX character classes & standard escapes.
        bad = []
        for line in loadable_lines:
            # Look for bare \\X escapes that aren't POSIX classes or \\./\\- etc.
            for tok in line.split():
                if tok.startswith("\\") and len(tok) > 1 and tok[1].isalpha():
                    if tok[1] not in (":", ):
                        bad.append((tok, line))
        self.assertEqual(bad, [], msg=f"non-portable escapes in {path.name}: {bad}")

    def test_phrases_bank(self) -> None:
        # Floor at 80% of the current loadable line count so accidental
        # halves of the bank during edits get caught.
        self._assert_bank_loadable(PHRASES_BANK, min_lines=50)

    def test_structures_bank(self) -> None:
        self._assert_bank_loadable(STRUCTURES_BANK, min_lines=30)


if __name__ == "__main__":
    unittest.main()
