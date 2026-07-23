---
name: skill-usage
category: shortcuts
description: Run the skill usage telemetry CLI and inspect turns, invocations, and per-project usage.
alpha: analysis
user-invocable: true
---

## Invocation

Arguments: `$ARGUMENTS` — pass any supported `tools/skill_usage.py` options.

## Behavior

Run the usage report from the repository root:

```bash
python3 tools/skill_usage.py $ARGUMENTS
```

Useful examples:

```text
/dev-kit:skill-usage
/dev-kit:skill-usage --top 0
/dev-kit:skill-usage --days 0 --json --per-cwd
/dev-kit:skill-usage --cwd /path/to/project
```

The CLI reports `turns` and `invocations` separately. Use
`python3 tools/skill_usage.py --help` for the complete option list.
