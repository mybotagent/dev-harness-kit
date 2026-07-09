---
name: bootstrap-active-hooks
category: bootstrap
description: stage-aware hook matrix initialization. Reads `.claude-plugin/plugin/hooks/hooks.json` and writes `.dev-kit/.active-hooks.json` with stage-aware defaults.
version: 0.1.0
when_to_use: |
  - When `/dev-kit:bootstrap` after codebase-map
  - When stage transition (Plan → Design → Build, etc.)
allowed-tools: Read Write Glob
disallowed-tools: Bash WebFetch Agent
model: haiku
user-invocable: false
---

# bootstrap-active-hooks — Stage-Aware Hook Matrix (SSOT)

## Iron Law
**All hook active states are decided in one place: `.dev-kit/.active-hooks.json`.** `hooks/hooks.json` only registers the matrix reader.

## Output format

```json
{
  "schema_version": "1.0.0",
  "updated_at": "2026-07-04T15:30:00Z",
  "matrix": {
    "bootstrap": {
      "tdd-guard": false,
      "bash-guard": false,
      "secret-scan": "read-only",
      "slop-detector": false,
      "stop-verify": false
    },
    "plan":       { "tdd-guard": false, "bash-guard": false, "secret-scan": false, "slop-detector": false, "stop-verify": true },
    "design":     { "tdd-guard": false, "bash-guard": false, "secret-scan": false, "slop-detector": false, "stop-verify": true },
    "build":      { "tdd-guard": true,  "bash-guard": true,  "secret-scan": true,  "slop-detector": true,  "stop-verify": true },
    "review":     { "tdd-guard": false, "bash-guard": false, "secret-scan": true,  "slop-detector": true,  "stop-verify": true },
    "security":   { "tdd-guard": false, "bash-guard": false, "secret-scan": true,  "slop-detector": true,  "stop-verify": true },
    "ship":       { "tdd-guard": false, "bash-guard": false, "secret-scan": false, "slop-detector": false, "stop-verify": true }
  },
  "override": {
    "disabled_hooks": [],
    "strict_mode": false
  }
}
```

## Hook shell (reference)

| Hook | Stage ON | Note |
|---|---|---|
| `tdd-guard` | build | active only when lib/methodology/tdd.py is loaded (MUST-48) |
| `bash-guard` | build | patterns like `rm -rf`, `git push --force main` |
| `secret-scan` | build / review / security | PostToolUse: credential pattern grep |
| `slop-detector` | build / review / security | KO+EN banned phrases |
| `stop-verify` | plan / design / build / review / security / ship | Stop event: AC claim verification |

## Rules

- **All hooks default `exit 0`** (MUST-12). Hard-block (`exit 2`) is `--strict` mode only.
- **`--strict` flag**: activates `exit 2` for all hooks. User opt-in.
- **`DEV_KIT_HOOK_OFF=<hook1>,<hook2>` env**: temporarily OFF (override).

## Stage transition auto-update

On `/dev-kit:<stage>` call, `lib/state_codec.py` auto-updates `current_stage` field in `.active-hooks.json` + hook shell calls `read` to consult the matrix.