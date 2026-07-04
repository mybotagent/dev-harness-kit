# ADR-0010 — Naming Convention (SSOT)

**Status**: Accepted

## Decision
All artifacts follow the convention in `docs/NAMING.md`. Exception: ADRs.

## Pattern per category
- bootstrap: `<category>-<instrument>`
- plan: `plan-<actor>` (pm-prd-fast → plan-ralph)
- design: `design-<instrument>` (deprecated, absorbed per MUST-50)
- build: `build-<discipline>` (engine/tdd/debug/verify/simplify/methodology)
- review: `review-<subject>` (3-dim)
- security: `security-<subject>` (10-dim OWASP)
- audit: `audit-<subject>` (slop/secret)
- shortcuts: `shortcut-<name>`
- ship: (no skill)

## Regression
`tests/test_naming.py` — directory `name` = SKILL frontmatter `name`. `category` ∈ allowed set.
