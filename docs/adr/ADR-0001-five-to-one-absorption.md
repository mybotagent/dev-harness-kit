# ADR-0001 — 5 → 1 absorption

**Status**: Accepted

## Decision
Zero external dependency. Fully absorb the 5 repos (code/skills/hooks moved as-is, only namespace changes). Old repos get `DEPRECATED.md` 1-liner + archive pointer.

## Context
- `pm-prd-fast/`, `interview-harness-skills/`, `dev-harness/`, `claude-review-plugins/`, `slop-shield/`
- Same workflow stages duplicated → 5 plugins to maintain in parallel.

## Rationale
- dev-harness's `install.sh --with-plugins` already recommended zero external deps.
- Absorption activates every stage in a single install.

## Outcome
- Old repo code preserved. `DEPRECATED.md` 1 line per repo.
- Namespace: kebab-case (ADR-0010).
