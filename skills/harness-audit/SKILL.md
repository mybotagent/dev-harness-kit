---
name: harness-audit
category: audit
description: 0-arg cross-harness quality audit. Reads on-disk state of 6 dev-kit harnesses (lcs / hooks / eval / plan_value / research / interview) and surfaces per-harness health: alpha classification, L7 alignment, resource completeness, rubric completeness. /dev-kit:harness-audit [--json] [--html-out PATH] [--project-root DIR].
alpha: analysis
when_to_use:
  - User types /dev-kit:harness-audit
  - Reviewer wants a cross-harness dashboard before merging Phase 7.1–7.4
  - Operator needs to know which harnesses are missing after a partial Phase 0–6 merge
  - Pre-release hygiene check covering the 6 shipped harnesses
allowed-tools: Read Bash Glob Grep
disallowed-tools: Write Edit WebFetch
model: sonnet
disable-model-invocation: true
user-invocable: true
---
> [← Skills index](../../README.md)

# /dev-kit:harness-audit — Cross-harness quality audit (Phase 7, issues #387–#390)

The `harness-audit` skill runs `tools/harness_audit.py` and returns one
report covering the 6 dev-kit harnesses. The audit is **strictly
read-only** (verified by `tests/test_harness_audit.py::test_audit_is_read_only`)
— it never writes to `.dev-kit/state.json`, never mutates `state.json`,
never invokes network I/O.

## What it does

Per-harness, the audit reports:

- `alpha` classification (from SKILL.md frontmatter) — must be
  `state | enforcement | analysis` (Iron Law L6).
- `alpha_valid` — True only when the alpha is in the L6 set.
- `resource_count` / `resource_expected` — LCS resources or hook
  scripts that exist vs. expected (per the 6-harness contract).
- `rubric_count` / `rubric_expected` — eval rubrics (harness-quality,
  os-quality) present under `eval/rubrics/`.
- `shipped` — True iff the load-bearing files exist + alpha is valid.
- `findings` — short, human-readable notes; empty when healthy.

The aggregate `summary` carries `shipped / total`, total `findings`
count, and the list of harnesses with an invalid `alpha`.

## 6 harnesses audited

| Harness | What it checks | Why |
|---|---|---|
| `lcs` | `lib/lcs_server.py` + 9 LCS resources + `skills/lcs/SKILL.md` alpha | LCS is the live state substrate |
| `hooks` | 7 hook scripts in `hooks/` + `.claude/settings.json` or `.codex/hooks.json` | Hooks enforce the worktree / CI gates |
| `eval` | `lib/eval_runner.py` + `lib/llm_judge.py` + `eval/rubrics/*.yaml` + `skills/evaluate/SKILL.md` | Eval drives the agent-behavior rubric |
| `plan_value` | `lib/valuation_engine.py` + rubric + judge prompt + `skills/valuate/SKILL.md` | Plan-value is the no-go gate before build |
| `research` | `lib/research_engine.py` + `skills/research/SKILL.md` | Research is the citation enforcement layer |
| `interview` | `lib/interview_engine.py` + `skills/interview/SKILL.md` | Interview resolves plan ambiguity |

## Output formats

Three output paths cover the agentic / user-friendly split:

| Flag | Surface | Use case |
|---|---|---|
| (default) | HTML to `.dev-kit/harness-audit-report.html` | Human inspection; user surface per #389 |
| `--json` | machine-readable JSON to stdout | CI gating, scripted consumption (agent surface) |
| `--html-out PATH` | self-contained HTML to PATH | Overrides the default artifact path |
| `--text` | brief text summary to stdout | Legacy callers / CI logs |

JSON shape (the canonical contract):

```json
{
  "harnesses": [
    {"name": "lcs", "shipped": true, "alpha": "state",
     "alpha_valid": true, "resource_count": 9, "resource_expected": 9,
     "rubric_count": 0, "rubric_expected": 0, "findings": []}
  ],
  "summary": {
    "total": 6, "shipped": 6, "findings": 0,
    "alpha_invalid": [], "all_shipped": true
  },
  "read_only": true
}
```

## Behavior

1. `python3 tools/harness_audit.py [--project-root DIR]`.
2. `--json` → print JSON to stdout (machine consumer). Exit 0 when all
   harnesses shipped AND no alpha_invalid; otherwise 1.
3. `--html-out PATH` → write HTML report to PATH (no shell-side mutation
   beyond the user's chosen file). Exit 0/1 same as `--json`.
4. Default → write HTML to `.dev-kit/harness-audit-report.html` (the
   canonical audit artifact path, mirrors `eval-report.md` /
   `inspect-report.md`). Per #389, "default = HTML for humans".
5. `--text` → print a brief text summary to stdout (legacy callers).
6. The skill body does not edit any file; all data collection is read
   on disk only.

## Alpha justification (L6)

`analysis` is the L6 default for read-only, no-state-mutation skills.
The distinct user intent vs. existing `analysis` skills (`inspect`,
`prune`, `refactor`): those operate over a corpus (code, diff) to find
findings. `harness-audit` operates over the harness's own wiring to
report structural health — the question is "is the harness itself
shipped?", not "are there defects in the code?". The per-harness
resource / rubric / alpha checklist is unique to this skill and cannot
be folded into `inspect` (which is per-PR) or `prune` (which is
deletion-oriented).

## Hook integration (audit stage)

| Hook | Mode |
|---|---|
| secret-scan | ON (read-only) |
| slop-detector | OFF (audit output allowed) |
| stop-verify | ON |

## Test evidence

`tests/test_harness_audit.py` covers:

- `test_audit_covers_all_six_harnesses` — exactly 6 entries, in HARNESSES order
- `test_audit_emits_html_report` — `--html-out` writes valid HTML with 6 rows
- `test_audit_is_read_only` — no `.dev-kit/` files created, no state mutation
- `test_audit_detects_missing_alpha_field` — invalid alpha → alpha_valid=False
- `test_audit_json_output_machine_readable` — `--json` parses + has 6 entries
- `test_audit_handles_missing_harnesses` — research/interview absence → findings, not crash
- `test_audit_detects_missing_rubrics` — `eval/rubrics/` absent → finding

## Next step

After audit, hand off to:
- `/dev-kit:ship` once all 6 harnesses are shipped + no L7 violations.
- `/dev-kit:inspect` for per-PR review (different question).
- `/dev-kit:repair` if the audit reveals broken alpha / missing rubric.