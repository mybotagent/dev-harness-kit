---
name: hook-doctor
category: audit
description: Diagnose failed Claude Code or Codex hooks, repair safe cache and registration drift, and report the exact restart step.
alpha: enforcement
when_to_use: |
  - A hook reports `exited with code 127` or another non-zero status
  - SessionStart, UserPromptSubmit, PostToolUse, or Stop hooks fail
  - A plugin reload leaves hook manifests and cached files out of sync
  - The user asks why a dev-kit hook is failing
allowed-tools: Read Bash
disallowed-tools: Write Edit
model: haiku
disable-model-invocation: false
user-invocable: false
---
> [← Skills index](../../README.md)

When a hook failure is visible in the conversation, run the deterministic doctor
before proposing code changes. It checks the runtime provider, plugin root,
manifest paths, executable dependencies, and cache/version alignment. It may
refresh a stale provider cache through the existing updater, but it never edits
project files or disables a failing enforcement hook.

## Triage workflow

1. Capture the event name and exit code from the failure. Treat `127` as a
   missing command or path until the doctor proves otherwise.
2. Run the bundled checker from the repository root:

   ```bash
   bash skills/hook-doctor/scripts/doctor.sh
   ```

3. If the report identifies a stale dev-kit cache, run only the matching safe
   updater:

   - Codex: `bash skills/codex-cache-update/scripts/update.sh`
   - Claude Code: `bash bin/devkit-refresh.sh`

   Do not run both unless both providers are reported stale.
4. Re-run the checker. If all checks pass, tell the user to restart the
   affected client because plugin hooks are loaded at session start. Do not
   claim the live session is repaired before the restart.

## Failure handling

- Missing `PLUGIN_ROOT` or `CLAUDE_PLUGIN_ROOT`: report the client and reload or
  restart requirement; do not guess a cache path.
- Missing hook file or manifest path: identify the exact path and refresh the
  provider cache if the matching updater is available.
- Missing `bash`, `jq`, `python3`, or `rsync`: report the install prerequisite;
  do not silently bypass the hook.
- Any non-zero hook result other than an infrastructure failure: preserve the
  hook's denial or warning and hand the event to the relevant skill.

The hook error itself should cause the model to invoke this skill when the
conversation contains `hook exited with code`, `hook failed`, `SessionStart`,
`UserPromptSubmit`, `PostToolUse`, or `Stop` failure text. This is model-use
automation, not a hook recursively spawning another model.

## Output contract

Return one compact report containing:

- provider and event
- failing exit code and evidence
- doctor result (`PASS`, `REPAIRABLE`, or `BLOCKED`)
- repair command run, if any
- exact restart or missing-prerequisite instruction

## Next step

After a successful restart, run `/dev-kit:status` if the failure interrupted a
stage, or return to the skill that originally triggered the failed hook.
