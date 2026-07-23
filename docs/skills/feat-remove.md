> [← Skills index](README.md) · [Project README](../../README.md)

# `feat-remove`

**Category:** `build` · **Alpha:** `state` · **Invocation:** `/dev-kit:feat-remove` (human-invoked)

`feat-remove` safely removes one named feature end to end: it discovers every reference to it (callers, tests, docs, plan artifacts), produces a deletion report, blocks on any dependent feature the user hasn't acknowledged, and verifies the full suite stays green after the deletion. It exists as its own skill because deleting a feature safely is a discovery-and-verification problem, not just a `rm` command — orphaned tests or docs left behind fail the build later, and undeclared dependents break silently if the cascade isn't surfaced first. The skill never deletes files itself; it emits the exact commands and waits for the user to run them, mirroring the `build-debug` write-prevention pattern.

## When to use it

- The user types `/dev-kit:feat-remove <feature>`.
- The feature is deprecated, replaced, or out of scope.
- The user wants confidence that no orphan callers, tests, or docs remain.

## How it works

Pre-flight: the `<feature>` argument is required and an empty one is refused. The feature must be locatable in the codebase — an implementation plus at least one test, or an explicit user override. If dependents exist, the skill lists them and refuses to proceed until the user acknowledges the cascade.

The skill then runs four phases:

```
[1/4] SWEEP       → grep + glob for: impl paths, test paths, doc paths, plan artifacts
       (must return 0 matches after deletion — orphan check)
       ↓
[2/4] DEPENDENTS  → list every other feature that imports / calls / extends <feature>
       (block if any exist; user must ack or reroute to /dev-kit:plan)
       ↓
[3/4] REPORT      → write .dev-kit/hand-off/feat-remove-report.md
       (paths to delete + exact rm / git rm commands for the user to run)
       ↓
[4/4] VERIFY      → after user runs the deletes, run the full suite
       (must stay green; if red, /dev-kit:build-debug the regression)
```

Rules enforced: MUST-L3 requires a quoted post-delete full-suite run before completion is declared; MUST-L4 forbids leaving a stub for an import — every reference is either deleted or migrated, never stubbed; dependents block by default with no silent cascade; and the skill itself never calls `rm` or `git rm` — the user runs the commands from the report.

The hook matrix during this skill: `bash-guard` ON (blocks destructive `rm -rf` etc. anyway; the skill still surfaces the commands for the user), `secret-scan` ON (PostToolUse), `slop-detector` ON, `stop-verify` ON (a quoted full-suite green run is required before declaring done).

## Usage

```bash
/dev-kit:feat-remove <feature>
```

## Output

- `.dev-kit/hand-off/feat-remove-report.md` listing every path to delete, the exact commands, and the dependents list.
- After the user runs the deletes: a quoted full-suite run (test count + exit code + duration).
- An updated `phases/<name>/index.json` marking the step `unimplemented` — the phase is closed, not deleted; git history remains the audit trail.

## Red flags

| Thought | Reality |
|---|---|
| "Just delete the main file, the rest is noise" | Sweep first. Orphan tests fail the build later. |
| "I'll keep it commented out for reference" | L4 violation. Commented-out code is stub. |
| "The dependents can be fixed later" | Block, do not cascade. Surface the list. |
| "Suite still passes after delete" | L3 violation. Quote the count. |

## Related

- [build](build.md) — where the user hands off to re-verify after deletion.
- [prune](prune.md) — its `--target <feat>` mode narrows a project-wide deletion sweep to one named feature, replacing this skill's slash per `prune`'s own documentation.
- `/dev-kit:review` — the deletion diff review hand-off mentioned as an alternative next step.

---
*Source: [`skills/feat-remove/SKILL.md`](../../skills/feat-remove/SKILL.md)*
