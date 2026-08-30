"""Regression tests for _safe_env_for_telemetry (A02-2 / A03-1 secret exclusion).

The whitelist in conftest.py is the last line of defence before telemetry
subprocess env leaks into `.dev-kit/trace/events.jsonl` (committed + shipped
with PR artifacts).  These tests verify:

1. Whitelisted keys (PATH, CI, GITHUB_*, RUNNER_*, DEV_KIT_*) pass through.
2. Secret keys (ANTHROPIC_API_KEY, OPENAI_API_KEY, GH_TOKEN, AWS_*, …) are
   dropped — the subprocess never sees them.
3. Keys not on the whitelist AND not starting with DEV_KIT_ are dropped.
4. DEV_KIT_AGENT is defaulted to ``pytest`` when not already set.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "tests"))

import conftest as contract_hook  # noqa: E402


class TestSafeEnvForTelemetry:
    # ------------------------------------------------------------------
    # Whitelist passthrough
    # ------------------------------------------------------------------
    def test_whitelisted_keys_pass_through(self, monkeypatch):
        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("HOME", "/home/test")
        monkeypatch.setenv("CI", "true")
        monkeypatch.setenv("GITHUB_ACTIONS", "true")
        monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
        monkeypatch.setenv("RUNNER_TEMP", "/tmp/runner")
        monkeypatch.setenv("RUNNER_OS", "Linux")
        monkeypatch.setenv("RUNNER_ARCH", "X64")
        monkeypatch.delenv("DEV_KIT_AGENT", raising=False)
        env = contract_hook._safe_env_for_telemetry()
        assert env.get("PATH") == "/usr/bin"
        assert env.get("HOME") == "/home/test"
        assert env.get("CI") == "true"
        assert env.get("GITHUB_ACTIONS") == "true"
        assert env.get("GITHUB_REPOSITORY") == "owner/repo"
        assert env.get("RUNNER_TEMP") == "/tmp/runner"
        assert env.get("RUNNER_OS") == "Linux"
        assert env.get("RUNNER_ARCH") == "X64"

    def test_dev_kit_prefix_keys_pass_through(self, monkeypatch):
        monkeypatch.delenv("DEV_KIT_AGENT", raising=False)
        monkeypatch.setenv("DEV_KIT_RUN_ID", "run-123")
        monkeypatch.setenv("DEV_KIT_PROVIDER", "github")
        monkeypatch.setenv("DEV_KIT_MODEL", "claude-3-5")
        env = contract_hook._safe_env_for_telemetry()
        assert env.get("DEV_KIT_RUN_ID") == "run-123"
        assert env.get("DEV_KIT_PROVIDER") == "github"
        assert env.get("DEV_KIT_MODEL") == "claude-3-5"

    def test_dev_kit_agent_defaults_to_pytest(self, monkeypatch):
        monkeypatch.delenv("DEV_KIT_AGENT", raising=False)
        env = contract_hook._safe_env_for_telemetry()
        assert env.get("DEV_KIT_AGENT") == "pytest"

    def test_dev_kit_agent_explicit_value_wins(self, monkeypatch):
        monkeypatch.setenv("DEV_KIT_AGENT", "my-custom-agent")
        env = contract_hook._safe_env_for_telemetry()
        assert env.get("DEV_KIT_AGENT") == "my-custom-agent"

    # ------------------------------------------------------------------
    # Secret exclusion (A02-2 / A03-1)
    # ------------------------------------------------------------------
    def test_anthropic_api_key_is_excluded(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-xxxxx")
        env = contract_hook._safe_env_for_telemetry()
        assert "ANTHROPIC_API_KEY" not in env

    def test_openai_api_key_is_excluded(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-xxxxx")
        env = contract_hook._safe_env_for_telemetry()
        assert "OPENAI_API_KEY" not in env

    def test_github_token_is_excluded(self, monkeypatch):
        monkeypatch.setenv("GH_TOKEN", "ghp_xxxxx")
        monkeypatch.setenv("GITHUB_TOKEN", "gho_xxxxx")
        env = contract_hook._safe_env_for_telemetry()
        assert "GH_TOKEN" not in env
        assert "GITHUB_TOKEN" not in env

    def test_aws_credentials_are_excluded(self, monkeypatch):
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAxxxxx")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "wJalxxxxx")
        monkeypatch.setenv("AWS_SESSION_TOKEN", "Fwoxxx")
        env = contract_hook._safe_env_for_telemetry()
        assert "AWS_ACCESS_KEY_ID" not in env
        assert "AWS_SECRET_ACCESS_KEY" not in env
        assert "AWS_SESSION_TOKEN" not in env

    def test_deepsseek_api_key_is_excluded(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-dsxxxxx")
        env = contract_hook._safe_env_for_telemetry()
        assert "DEEPSEEK_API_KEY" not in env

    def test_arbitrary_unknown_key_is_excluded(self, monkeypatch):
        monkeypatch.setenv("MY_SECRET_TOKEN", "tok_xxxxx")
        monkeypatch.setenv("DATABASE_URL", "postgres://user:pass@host/db")
        monkeypatch.setenv("SECRET_xyz", "should-be-hidden")
        env = contract_hook._safe_env_for_telemetry()
        assert "MY_SECRET_TOKEN" not in env
        assert "DATABASE_URL" not in env
        assert "SECRET_xyz" not in env

    def test_returned_dict_is_independent_of_os_environ(self, monkeypatch):
        """The returned dict must be a fresh copy, not a view of os.environ."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-xxxxx")
        env = contract_hook._safe_env_for_telemetry()
        # env must not contain the secret
        assert "ANTHROPIC_API_KEY" not in env
        # os.environ still has the secret (monkeypatch set it)
        assert os.environ.get("ANTHROPIC_API_KEY") == "sk-ant-xxxxx"
        # Mutating the returned dict must not affect os.environ
        env["ANTHROPIC_API_KEY"] = "hacked"
        assert os.environ.get("ANTHROPIC_API_KEY") == "sk-ant-xxxxx"
