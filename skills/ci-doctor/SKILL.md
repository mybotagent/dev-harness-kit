---
name: ci-doctor
category: audit
description: Read-only CI readiness audit. Prints one PASS/FAIL summary across files, marker, provider file, secrets, and gh auth. Hand-off answer to "would CI succeed on my next PR?"
when_to_use:
  - User types /dev-kit:ci-doctor
  - User asks "is my CI set up correctly?" / "would the next PR be green?"
  - After /dev-kit:ci-setup or /dev-kit:bootstrap-full to verify readiness
  - Pre-PR sanity check before opening the first dev-kit PR
allowed-tools: Read Glob Bash
disallowed-tools: Edit Write Agent WebFetch
model: sonnet
disable-model-invocation: false
user-invocable: true
---

# /dev-kit:ci-doctor — CI Readiness Audit

## Iron Law

**0-arg. Read-only. Never mutates target files; never writes secrets; never opens PRs.** Issue #212-D1: a consumer who just ran `/dev-kit:bootstrap-full` has no way to ask "is my CI ready?" until the next PR turns red. This skill answers that question in one call.

## What it does

Runs `lib/ci_doctor.py:audit()` against the current working directory (or `--target DIR`) and prints a flat PASS/FAIL summary across:

| Check | Why |
|---|---|
| `file present: .github/workflows/{ci,review,auto-fix-pr}.yml` | Three runners must land; missing any = no CI |
| `file present: .github/ci-review-provider.txt` | `review.yml` reads the provider from this file (issue #212-A1) |
| `file present: .dev-kit/ci-config.json` | Build pre-flight marker (`/dev-kit:build` refuses to start without it) |
| `marker parseable` / `marker non-empty` / `marker records provider file` | Round-trip JSON, no zero-byte corruption |
| `provider file content` | `.github/ci-review-provider.txt` holds a valid provider name |
| `gh auth` | `gh secret list` requires `gh auth status` to pass |
| `secret set: DEV_KIT_GITHUB_TOKEN` | Consumer-install precondition (issue #212-B1) |
| `secret set: <provider-API-key>` | Provider-matching secret (B2). Default `minimax` ⇒ `MINIMAX_API_KEY` |

Every FAIL row prints the exact remediation (`run: gh secret set NAME --repo OWNER/REPO`, etc.) so the discover path is `audit → paste commands → re-audit` rather than the current `push PR → CI red → read log → grep for the secret name`.

## Body

1. Parse `--target DIR` (default `$PWD`).
2. Delegate to `lib/ci_doctor.py:audit(target_dir)`.
3. Print `DoctorReport.summary_lines()`. The verdict line is `ci-doctor verdict: PASS` or `ci-doctor verdict: FAIL`.
4. Exit code: 0 on PASS, 1 on FAIL. SKIP rows never flip the verdict (no `gh` locally = honest "can't verify", not "broken").

When a FAIL row is present, also print a one-line "next step" pointing the user at `/dev-kit:ci-setup --force` for re-install or `gh secret set NAME --repo OWNER/REPO` for missing secrets.

## Rules

- **Read-only**: no Edit / Write / Agent tools. Even mutations to the user's `.env` are off-limits; the audit answers questions, it doesn't fix them.
- **Single hand-off**: succeeds → exit 0. Fails → exit 1 + remediation hints. No automated fixing.
- **No secrets in output**: secrets are read via `gh secret list` (returns names, not values). The audit NEVER prints a secret value, even when present.
- **`/dev-kit:bootstrap-full` should run this skill next**: it is the canonical post-install verification (issue #212-D1 / D2).

## Files installed

This skill ships:

| Path | Purpose |
|---|---|
| `skills/ci-doctor/SKILL.md` | This file |
| `lib/ci_doctor.py` | The audit engine — pure stdlib, no external deps. Re-exported as the `ci-doctor` symlink by `/dev-kit:ci-setup --force` (markers know about it but the templates tree is the source). |

## Iron Law (repeated, for emphasis)

**Read-only. Verdict only. No writes, no PRs, no secrets printed.**
