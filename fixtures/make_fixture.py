#!/usr/bin/env python3
"""Fixture generator for token_efficiency_analyzer.py.

Creates six synthetic Claude Code JSONL sessions, one per warning trigger,
all with cwd under /tmp/fixture-repo so the --repo filter matches.
"""
import json
import os
import tempfile
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "logs" / "claude-code"
FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

# Use the platform tempdir rather than hardcoded /tmp so the fixture
# generator works on:
#   * macOS where /tmp is a symlink to /private/tmp (avoids macOS clears)
#   * CI runners where /tmp is mounted noexec
#   * sandboxed mac apps with a private /tmp mount
#   * Windows where /tmp does not exist
# The cwd basename (`fixture-repo`) is what tests filter by via
# `--repo fixture-repo`; changing the prefix does not break them.
CWD = os.path.join(tempfile.gettempdir(), "fixture-repo")
NOW = "2026-07-09T10:00:00.000Z"

def make_assistant(session_id, idx, *, model, in_tok, out_tok, cache_write, cache_read,
                   tools=None, ephemeral_5m=0, ephemeral_1h=0):
    content = []
    for t in (tools or []):
        if t["name"] == "Read":
            content.append({
                "type": "tool_use",
                "name": "Read",
                "input": {"file_path": t["file"]},
            })
        else:
            content.append({
                "type": "tool_use",
                "name": t["name"],
                "input": {},
            })
    if not content:
        content = [{"type": "text", "text": f"assistant turn {idx}"}]
    return {
        "parentUuid": f"parent-{session_id}-{idx}",
        "isSidechain": False,
        "message": {
            "id": f"msg-{session_id}-{idx}",
            "type": "message",
            "role": "assistant",
            "content": content,
            "model": model,
            "stop_reason": "end_turn",
            "usage": {
                "input_tokens": in_tok,
                "cache_creation_input_tokens": cache_write,
                "cache_read_input_tokens": cache_read,
                "output_tokens": out_tok,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": ephemeral_5m,
                    "ephemeral_1h_input_tokens": ephemeral_1h,
                },
            },
        },
        "type": "assistant",
        "uuid": f"uuid-{session_id}-{idx}",
        "timestamp": NOW,
        "sessionId": session_id,
        "cwd": CWD,
        "userType": "external",
        "entrypoint": "cli",
        "version": "test",
        "gitBranch": "main",
    }


def make_user(session_id, idx, text):
    return {
        "parentUuid": f"parent-{session_id}-{idx}",
        "isSidechain": False,
        "message": {"role": "user", "content": text},
        "type": "user",
        "uuid": f"uuid-{session_id}-{idx}",
        "timestamp": NOW,
        "sessionId": session_id,
        "cwd": CWD,
        "userType": "external",
        "entrypoint": "cli",
        "version": "test",
        "gitBranch": "main",
    }


def write_session(session_id, records):
    path = FIXTURE_DIR / f"{session_id}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    print(f"wrote {path} ({len(records)} records)")


# Session A: low cache hit (<50%) — fires CACHE_HIT_LOW
write_session("aaaa-low-cache", [
    make_user("aaaa-low-cache", 0, "fix the login bug"),
    make_assistant("aaaa-low-cache", 1,
        model="claude-opus-4-7",
        in_tok=80_000, out_tok=500,
        cache_write=20_000, cache_read=10_000),  # hit = 10/(80+10) = 11%
    make_assistant("aaaa-low-cache", 2,
        model="claude-opus-4-7",
        in_tok=90_000, out_tok=400,
        cache_write=20_000, cache_read=10_000),
])

# Session B: Read-heavy (40%+ of tool cost is Read) — fires READ_HEAVY
write_session("bbbb-read-heavy", [
    make_user("bbbb-read-heavy", 0, "explain this codebase"),
    make_assistant("bbbb-read-heavy", 1,
        model="claude-sonnet-5",
        in_tok=5_000, out_tok=300,
        cache_write=50_000, cache_read=10_000,
        tools=[
            {"name": "Read", "file": "/repo/src/big_file.py"},
            {"name": "Read", "file": "/repo/src/big_file.py"},
            {"name": "Read", "file": "/repo/src/big_file.py"},
            {"name": "Read", "file": "/repo/src/big_file.py"},
            {"name": "Read", "file": "/repo/src/big_file.py"},
            {"name": "Read", "file": "/repo/src/big_file.py"},
            {"name": "Read", "file": "/repo/src/other.py"},
            {"name": "Bash", "file": None},
        ]),
])

# Session C: heavy context (>500K) — fires HEAVY_CONTEXT
write_session("cccc-heavy-ctx", [
    make_user("cccc-heavy-ctx", 0, "analyze this whole repo"),
    make_assistant("cccc-heavy-ctx", 1,
        model="claude-sonnet-5",
        in_tok=400_000, out_tok=2_000,
        cache_write=100_000, cache_read=200_000),  # total_in = 600K
])

# Session D: Opus on simple typo work (low density) — fires MODEL_OVERSPEC
write_session("dddd-opus-typo", [
    make_user("dddd-opus-typo", 0, "fix typo in README"),
    make_assistant("dddd-opus-typo", 1,
        model="claude-opus-4-7",
        in_tok=30_000, out_tok=100,  # density ~ 0.3% -> score < 20
        cache_write=20_000, cache_read=60_000),
])

# Session E: write-not-reused — fires WRITE_NOT_REUSED
write_session("eeee-write-not-reused", [
    make_user("eeee-write-not-reused", 0, "one-off query"),
    make_assistant("eeee-write-not-reused", 1,
        model="claude-opus-4-7",
        in_tok=10_000, out_tok=500,
        cache_write=200_000, cache_read=10_000),  # writes=200K, reads=10K < 2x writes
])

# Session F: repeated user message — fires REPEATED_USER_MSG
repeat_text = "please continue, I think there is a bug in the loop above, fix it"
write_session("ffff-repeated-msg", [
    make_user("ffff-repeated-msg", 0, repeat_text),
    make_assistant("ffff-repeated-msg", 1,
        model="claude-sonnet-5",
        in_tok=10_000, out_tok=500,
        cache_write=30_000, cache_read=50_000),
    make_user("ffff-repeated-msg", 2, repeat_text),
    make_assistant("ffff-repeated-msg", 3,
        model="claude-sonnet-5",
        in_tok=10_000, out_tok=500,
        cache_write=30_000, cache_read=50_000),
    make_user("ffff-repeated-msg", 4, repeat_text),
    make_assistant("ffff-repeated-msg", 5,
        model="claude-sonnet-5",
        in_tok=10_000, out_tok=500,
        cache_write=30_000, cache_read=50_000),
])

print(f"\nfixture repo (basename of cwd): {os.path.basename(CWD)}")
