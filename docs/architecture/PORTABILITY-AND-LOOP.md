# Portability and long-running loop contract

The live contract is intentionally small:

```text
python3 tools/portability_check.py --json
python3 tools/loop_engine.py iterate --feature-list feature_list.json
python3 tools/loop_engine.py verify --feature-list feature_list.json
```

`portability_check.py` is read-only. It compares the Claude and Codex
manifest identity, normalizes their plugin-root variables, compares every
hook event/matcher/command, and parses every top-level shell hook with
`bash -n`. Exit `0` means the portable contract holds; exit `1` contains
actionable findings.

`loop_engine.py iterate` deterministically selects the lexicographically first
eligible `failing` feature, runs its declared `test_path`, and atomically writes
`.dev-kit/loop-checkpoint.json`. A failed test is still recorded. The feature
list is never silently changed: only a human or an agent with explicit evidence
may mark a feature `passing`. This prevents a green command from becoming a
false completion claim.

The checkpoint is the cold-context hand-off: it contains the iteration number,
feature id, exact command, exit code, and bounded output tails. Re-running is
safe and continues from the same feature until its status is deliberately
updated. `ci-setup` ships both tools to consumers, so the loop does not depend
on the plugin checkout path or on Claude-specific environment variables.

The older `RUNTIME-PORTABILITY.md` describes a deleted adapter experiment and
is retained as history; it is not the current runtime contract.
