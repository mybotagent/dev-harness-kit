"""commands_register.py — Install-time commands dir registration for both
Claude Code and Codex runtime targets.

Writes (atomically):
- `.claude/settings.json`  — adds a SessionStart hook that runs
                              `bin/install-commands.sh` if it does not
                              already exist. Idempotent: re-running on
                              an already-registered file is a no-op.
- `.codex/hooks.json`      — same hook entry, targeted at the Codex
                              runtime.

This is the runtime-equivalent of "install-time" registration: every
SessionStart the target loader re-invokes `bin/install-commands.sh`,
which materializes the canonical commands/*.md into both .claude/commands
and .codex/commands target trees. Without this wiring, a fresh checkout
that has not yet run the installer would silently lack the slash commands.

Caller surface:
- `register_commands_dir(project_root: Path) -> dict`
   Mutates settings.json and hooks.json atomically; returns a small
   status dict for the caller to log/print.
- `is_registered(project_root: Path) -> dict`
   Read-only check used by `bin/install-commands.sh --verify`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
import atomic  # noqa: E402  (lib/atomic.py)

REGISTRY_MARKER = "commands_dir_registered_by_install_commands"


def _ensure_claude_hook(settings_path: Path) -> bool:
    """Add a SessionStart hook to `.claude/settings.json` if absent.

    Returns True when the file was modified, False when it was already
    registered (idempotent re-run).
    """
    if settings_path.exists():
        data: dict[str, Any] = json.loads(settings_path.read_text(encoding="utf-8"))
    else:
        data = {}
    hooks = data.setdefault("hooks", {})
    sess = hooks.get("SessionStart", [])
    target = (
        "for f in python3 python py; do "
        "if \"$f\" -c \"\" </dev/null >/dev/null 2>&1; then "
        "exec \"$f\" \"${CLAUDE_PROJECT_DIR}/bin/install-commands.sh\"; fi; done"
    )

    # Idempotency: if any SessionStart hook already runs install-commands.sh,
    # treat as registered.
    for entry in sess:
        for hook in entry.get("hooks", []):
            cmd = hook.get("command", "")
            if "install-commands.sh" in cmd:
                return False

    sess.append(
        {
            "hooks": [
                {
                    "type": "command",
                    "command": target,
                }
            ],
            "_commands_dir_registered_by_install_commands": True,
        }
    )
    hooks["SessionStart"] = sess
    data["hooks"] = hooks
    atomic.atomic_write_json(settings_path, data)
    return True


def _ensure_codex_hook(hooks_path: Path) -> bool:
    """Same idempotent registration for `.codex/hooks.json`."""
    if hooks_path.exists():
        data: dict[str, Any] = json.loads(hooks_path.read_text(encoding="utf-8"))
    else:
        data = {}
    hooks = data.setdefault("hooks", {})
    sess = hooks.get("SessionStart", [])
    target = (
        "for f in python3 python py; do "
        "if \"$f\" -c \"\" </dev/null >/dev/null 2>&1; then "
        "exec \"$f\" \"$PWD/bin/install-commands.sh\"; fi; done"
    )

    for entry in sess:
        for hook in entry.get("hooks", []):
            cmd = hook.get("command", "")
            if "install-commands.sh" in cmd:
                return False

    sess.append(
        {
            "hooks": [
                {
                    "type": "command",
                    "command": target,
                }
            ],
            "_commands_dir_registered_by_install_commands": True,
        }
    )
    hooks["SessionStart"] = sess
    data["hooks"] = hooks
    atomic.atomic_write_json(hooks_path, data)
    return True


def register_commands_dir(project_root: Path) -> dict[str, Any]:
    """Atomic registration. Returns {claude_modified, codex_modified}."""
    project_root = Path(project_root)
    claude_modified = _ensure_claude_hook(project_root / ".claude" / "settings.json")
    codex_modified = _ensure_codex_hook(project_root / ".codex" / "hooks.json")
    return {
        "claude_modified": claude_modified,
        "codex_modified": codex_modified,
    }


def is_registered(project_root: Path) -> dict[str, bool]:
    project_root = Path(project_root)
    out = {"claude": False, "codex": False}
    for kind, path in (
        ("claude", project_root / ".claude" / "settings.json"),
        ("codex", project_root / ".codex" / "hooks.json"),
    ):
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        for entry in data.get("hooks", {}).get("SessionStart", []):
            for hook in entry.get("hooks", []):
                if "install-commands.sh" in hook.get("command", ""):
                    out[kind] = True
                    break
            if out[kind]:
                break
    return out


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    print(json.dumps(register_commands_dir(root), indent=2))
