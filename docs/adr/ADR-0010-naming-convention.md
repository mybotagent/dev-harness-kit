# ADR-0010 — Naming Convention (SSOT)

**Status**: Accepted

## Decision
All artifacts follow the convention in `docs/NAMING.md`. Exception: ADRs.

## Pattern per category
- bootstrap: `<category>-<instrument>` (exception: `ci-setup` — slash-command brevity; lives under `bootstrap` category in frontmatter but is referenced as `/dev-kit:ci-setup`, not `/dev-kit:bootstrap-ci-setup`)
- plan: `plan-<actor>` (pm-prd-fast → plan-ralph)
- design: `<category>-<instrument>` (deprecated, absorbed per MUST-50)
- build: `build-<discipline>` (engine/tdd/debug/verify/simplify/methodology)
- review: `review-<subject>` (3-dim)
- security: `security-<subject>` (10-dim OWASP)
- audit: `audit-<subject>` (slop/secret)
- shortcuts: `shortcut-<name>`
- ship: (no skill, gate only)
- config, eval, onboard, repair, status: standalone skills (post commands→skills merge)

## Regression
`tests/test_naming.py` — directory `name` = SKILL frontmatter `name`. `category` ∈ 14 allowed values (audit, bootstrap, build, config, design, eval, onboard, plan, repair, review, security, ship, shortcuts, status).
