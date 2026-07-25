#!/usr/bin/env python3
"""test_dev_kit_lcs_cli.py — Phase 1.2 (issue #347) CLI driver regression.

Pins the CLI surface: --list-resources, --describe, --get, --serve
(JSON-RPC over stdio). The CLI is invoked as a subprocess so exit
codes, stdout/stderr framing, and signal handling are exercised
end-to-end. The CLI registers the five production resources at startup. The
``DEV_KIT_LCS_DEMO=1`` env-var hook adds a deterministic ``demo`` resource
for wire-format tests without replacing the production registry.

The LCS server contract itself is covered by ``tests/test_lcs_server.py``.
These tests focus on the CLI wrapper: argument parsing, exit codes,
output framing, JSON-RPC wire format.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
CLI = REPO_ROOT / "bin" / "dev-kit-lcs.py"


def _run_cli(*args: str, stdin: str | None = None, with_demo: bool = False,
             timeout: float = 5.0) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        str(REPO_ROOT / "lib") + os.pathsep + env.get("PYTHONPATH", "")
    )
    if with_demo:
        env["DEV_KIT_LCS_DEMO"] = "1"
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
        check=False,
    )


# ──────────────────────────────────────────────────────────────────
# User surface
# ──────────────────────────────────────────────────────────────────

class TestListResources(unittest.TestCase):
    def test_default_registry_lists_production_resources(self):
        cp = _run_cli("--list-resources")
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        for resource in ("worktrees", "branches", "pr", "sessions", "spend"):
            self.assertIn(resource, cp.stdout)

    def test_list_resources_with_demo_resource(self):
        cp = _run_cli("--list-resources", with_demo=True)
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        self.assertIn("demo", cp.stdout)


class TestDescribe(unittest.TestCase):
    def test_describe_unknown_resource_returns_2(self):
        cp = _run_cli("--describe", "nope")
        self.assertEqual(cp.returncode, 2, cp.stdout + cp.stderr)
        self.assertIn("unknown resource", cp.stderr)

    def test_describe_known_resource_returns_json(self):
        cp = _run_cli("--describe", "demo", with_demo=True)
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertEqual(payload["name"], "demo")


# ──────────────────────────────────────────────────────────────────
# Agent surface
# ──────────────────────────────────────────────────────────────────

class TestGet(unittest.TestCase):
    def test_get_unknown_resource_returns_2(self):
        cp = _run_cli("--get", "lcs://nope")
        self.assertEqual(cp.returncode, 2, cp.stdout + cp.stderr)
        payload = json.loads(cp.stderr.strip().splitlines()[-1])
        self.assertEqual(payload["status"], "error")

    def test_get_malformed_uri_returns_2(self):
        cp = _run_cli("--get", "not-an-lcs-uri")
        self.assertEqual(cp.returncode, 2, cp.stdout + cp.stderr)

    def test_get_ok_resource_returns_0(self):
        cp = _run_cli("--get", "lcs://demo", with_demo=True)
        self.assertEqual(cp.returncode, 0, cp.stdout + cp.stderr)
        payload = json.loads(cp.stdout)
        self.assertEqual(payload["status"], "ok")


# ──────────────────────────────────────────────────────────────────
# JSON-RPC serve mode
# ──────────────────────────────────────────────────────────────────

class TestServe(unittest.TestCase):
    def _serve(self, requests: list) -> list[dict]:
        stdin_text = "\n".join(
            r if isinstance(r, str) else json.dumps(r) for r in requests
        ) + "\n"
        cp = _run_cli("--serve", stdin=stdin_text, with_demo=True)
        return [json.loads(line) for line in cp.stdout.splitlines() if line.strip()]

    def test_get_request_round_trip(self):
        responses = self._serve([
            {"id": 1, "method": "lcs.get", "params": {"uri": "lcs://demo"}},
        ])
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["id"], 1)
        self.assertEqual(responses[0]["result"]["status"], "ok")

    def test_list_request_returns_resource_names(self):
        responses = self._serve([
            {"id": 2, "method": "lcs.list", "params": {}},
        ])
        self.assertEqual(responses[0]["id"], 2)
        self.assertIn("demo", responses[0]["result"])

    def test_describe_request_returns_class_info(self):
        responses = self._serve([
            {"id": 3, "method": "lcs.describe", "params": {"name": "demo"}},
        ])
        self.assertEqual(responses[0]["id"], 3)
        self.assertEqual(responses[0]["result"]["name"], "demo")

    def test_unknown_method_returns_error(self):
        responses = self._serve([
            {"id": 4, "method": "lcs.nope", "params": {}},
        ])
        self.assertEqual(len(responses), 1)
        self.assertEqual(responses[0]["id"], 4)
        self.assertIn("error", responses[0])

    def test_parse_error_does_not_crash_server(self):
        # Malformed JSON line should not kill the loop — the next
        # request still gets a response.
        responses = self._serve([
            "this is not json",
            {"id": 5, "method": "lcs.list", "params": {}},
        ])
        ids = [r.get("id") for r in responses]
        self.assertIn(5, ids, f"server died after parse error. responses={responses}")


if __name__ == "__main__":
    unittest.main()
