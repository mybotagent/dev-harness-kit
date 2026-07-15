#!/usr/bin/env python3
"""Report the local Claude Code, Codex, and Git hook status."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def git_config(root: Path, key: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), "config", "--get", key],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def hook_events(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return sorted(data.get("hooks", {}).keys())


def codex_hooks_path(root: Path, manifest: Path) -> Path:
    """Resolve the Codex hook file relative to the plugin package root."""
    try:
        hooks_ref = json.loads(manifest.read_text(encoding="utf-8")).get("hooks", "")
    except (OSError, json.JSONDecodeError):
        return root / ".codex-plugin" / "hooks" / "hooks.json"
    return root / hooks_ref if isinstance(hooks_ref, str) and hooks_ref else root / ".codex-plugin" / "hooks" / "hooks.json"


def status(root: Path) -> dict[str, object]:
    hooks_json = root / "hooks" / "hooks.json"
    claude_manifest = root / ".claude-plugin" / "plugin.json"
    codex_manifest = root / ".codex-plugin" / "plugin.json"
    codex_hooks_json = codex_hooks_path(root, codex_manifest)
    git_hook = root / ".githooks" / "pre-push"
    configured_path = git_config(root, "core.hooksPath")
    configured_dir = Path(configured_path)
    if configured_path and not configured_dir.is_absolute():
        configured_dir = root / configured_dir
    configured_pre_push = configured_dir / "pre-push" if configured_path else None
    git_active = bool(configured_pre_push and configured_pre_push.is_file())

    codex_registered = False
    try:
        codex_registered = codex_hooks_json.is_file()
    except (OSError, json.JSONDecodeError):
        pass

    return {
        "root": str(root),
        "source_hooks": {
            "path": str(hooks_json),
            "exists": hooks_json.is_file(),
            "events": hook_events(hooks_json),
        },
        "claude": {
            "manifest": claude_manifest.is_file(),
            "hooks_registered": hooks_json.is_file(),
        },
        "codex": {
            "manifest": codex_manifest.is_file(),
            "hooks_registered": codex_registered,
            "hooks_path": str(codex_hooks_json),
            "trust": "review with /hooks if new or changed",
        },
        "git": {
            "pre_push_file": git_hook.is_file(),
            "configured_hooks_path": configured_path or None,
            "configured_pre_push": str(configured_pre_push) if configured_pre_push else None,
            "pre_push_active": git_active,
        },
        "active_hooks_matrix": (root / ".dev-kit" / ".active-hooks.json").is_file(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="project root (default: current directory)")
    parser.add_argument("--json", action="store_true", dest="as_json", help="emit machine-readable JSON")
    args = parser.parse_args()
    result = status(args.root.resolve())
    if args.as_json:
        print(json.dumps(result, indent=2))
    else:
        print(f"root: {result['root']}")
        print(f"Claude Code: {'registered' if result['claude']['hooks_registered'] else 'not registered'}")
        print(f"Codex:       {'registered' if result['codex']['hooks_registered'] else 'not registered'} (trust: {result['codex']['trust']})")
        print(f"Git pre-push: {'active' if result['git']['pre_push_active'] else 'inactive'}")
        print(f"Matrix:      {'present' if result['active_hooks_matrix'] else 'missing'} (.dev-kit/.active-hooks.json)")
        print(f"Events:      {', '.join(result['source_hooks']['events']) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
