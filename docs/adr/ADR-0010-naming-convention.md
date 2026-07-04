# ADR-0010 — Naming Convention (SSOT)

**Status**: Accepted

## 결정
모든 산출물은 `docs/NAMING.md` 명명 규약 따른다. 예외 = ADR.

## 카테고리별 패턴
- bootstrap: `<category>-<instrument>`
- plan: `plan-<actor>` (pm-prd-fast → plan-ralph)
- design: `design-<instrument>` (deprecated, MUST-50 흡수)
- build: `build-<discipline>` (engine/tdd/debug/verify/simplify/methodology)
- review: `review-<subject>` (3-dim)
- security: `security-<subject>` (10-dim OWASP)
- audit: `audit-<subject>` (slop/secret)
- shortcuts: `shortcut-<name>`
- ship: (no skill)

## 회귀
`tests/test_naming.py` — directory `name` = SKILL frontmatter `name`. category ∈ 9.
