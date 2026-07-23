> [← Skills index](README.md) · [Project README](../../README.md)

# `audit`

**Category:** `audit` · **Alpha:** `state` · **Invocation:** `/dev-kit:audit` (human-invoked)

`audit` is a cross-cutting, read-only sweep that combines a secret scan, a slop scan, and an outdated-skill drift report in one call. It delegates the slop+secret sweep to `lib.analysis_core.run_analysis(dimensions=group("audit"), mode="read-only", paths=...)`, and the outdated-skill drift check to `lib.ci_setup.py:per_skill_drift` directly, so the same shared engine backs the bulk-scan modes while drift detection stays a separate, purpose-built path.

## When to use it

- The user types `/dev-kit:audit`.
- The user wants a bulk audit before a release.

## How it works

The skill enforces an Iron Law: it is strictly read-only. `Write` and `Edit` are disallowed, and Bash is limited to read-only scanners (`grep`, `git diff`, `slop-detector.sh`, `secret-scan.sh`).

It runs one of three modes, or all three combined by default:

- **Mode 1 — secret scan.** Uses the SSOT patterns in `hooks/secret-scan.sh` to detect AWS keys (`AKIA...`), Anthropic keys (`sk-*` / `sk-ant-*`), GitHub tokens (`ghp_*` / `gho_*`), Slack tokens (`xox[bpoa]-*`), PEM private keys, and credentialed `postgres://` / `mongodb+srv://` URIs. It never prints secret text — only the path and a masked value (`***`) — and tags each finding `dim: "secret"` with `fix_hint: "rotate + remove"`. Severity is CRITICAL on discovery and WARN for env-file references pending verification.
- **Mode 2 — slop scan.** Uses the phrase bank at `hooks/references/slop/phrases.md` (T1) and the structure bank at `hooks/references/slop/structures.md` (T2). For each file it runs a T1 phrase scan and a T2 structure scan, then scores the file on a 5-dim rubric, bucketing it as HIGH (any KO, or ≥3 distinct T1, or ≥1 T1 + ≥1 T2), MEDIUM (≥2 T1 or any KO structure), LOW (1 T1 or 1 T2), or clean. Findings are tagged `dim: "slop"`.
- **Mode 3 — outdated-skill audit.** Calls `lib/ci_setup.py:per_skill_drift(plugin_root) -> dict[str, str]`, which compares the installed snapshot (`~/.claude/plugins/cache/dev-kit/...` or `~/.claude/plugins/marketplaces/dev-kit/...`) against HEAD. Each skill is classified `behind`, `current`, or `no_install`, sorted behind-first. This mode writes to stdout only, no file. Exit code is 0 if all skills are current, 1 if any are `behind` or `no_install`.

## Usage

```bash
/dev-kit:audit [--secrets-only | --slop-only | --outdated]
```

| Flag | Effect |
|---|---|
| `--secrets-only` | Secret scan only (Mode 1). |
| `--slop-only` | Slop scan only (Mode 2). |
| `--outdated` | Outdated-skill drift report only (Mode 3). |
| _(default)_ | All three modes combined. |

## Output

Combined output includes a CRITICAL section (path, masked secret value, remediation hint), a HIGH-bucket slop section (file, count, matched phrases), and — for `--outdated` — a table of skill name vs. drift status with a summary line of how many skills are behind out of the total.

```
## /dev-kit:audit -- {path} -- {N} files / {M} matches

### CRITICAL
- path/to/file.py:42 AKIA*** (AWS key — REMOVE)

### HIGH (slop)
- README.md 8 (delve into x3, robust x2, ...)

=== /dev-kit:audit --outdated -- N behind of 30 skills ===
SKILL  STATUS
audit  behind
... N current ...
```

## Related

- [inspect](inspect.md) — broader semantic sweep for a deeper follow-up.
- `hooks/secret-scan.sh`, `hooks/references/slop/phrases.md`, `hooks/references/slop/structures.md` — pattern sources for Modes 1 and 2.
- `lib/ci_setup.py:per_skill_drift` — drift-detection engine for Mode 3.

---
*Source: [`skills/audit/SKILL.md`](../../skills/audit/SKILL.md)*
