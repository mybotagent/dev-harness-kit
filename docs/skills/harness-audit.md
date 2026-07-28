> [← Skills index](README.md) · [Project README](../../README.md)

# `harness-audit`

**Category:** `audit` · **Alpha:** `analysis` · **Invocation:** `/dev-kit:harness-audit` (human-invoked)

`harness-audit` runs `tools/harness_audit.py` over the 6 dev-kit harnesses (`lcs` / `hooks` / `eval` / `plan_value` / `research` / `interview`) and reports per-harness `alpha` (from SKILL.md frontmatter), L7 alignment, resource completeness, and rubric completeness. The audit is strictly read-only — never writes to `.dev-kit/state.json`, never mutates `state.json`, never invokes network I/O. Source: [`skills/harness-audit/SKILL.md`](../../skills/harness-audit/SKILL.md).

## When to use it

- The user types `/dev-kit:harness-audit`.
- A reviewer wants the cross-harness dashboard before merging Phase 7.1–7.4.
- An operator needs to know which harnesses are missing after a partial Phase 0–6 merge.
- A pre-release hygiene check covers the 6 shipped harnesses.

## Invocation

```bash
/dev-kit:harness-audit                  # HTML to .dev-kit/harness-audit-report.html
/dev-kit:harness-audit --json          # machine-readable JSON to stdout
/dev-kit:harness-audit --html-out PATH # self-contained HTML to PATH
/dev-kit:harness-audit --text          # brief text summary to stdout (CI logs)
```

Exit 0 on clean / minor; exit 1 on missing harnesses or L7 violations.
