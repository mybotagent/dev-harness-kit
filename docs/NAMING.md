# NAMING — dev-harness-kit naming convention (ADR-0010 SSOT)

> Single source of truth: this file + `tests/test_naming.py` regression tests.

## Skill directory / file

- **Format**: `<category>-<verb-or-noun>.md` (kebab-case, English)
- **Directory**: `skills/<skill-name>/SKILL.md` (one level — Claude Code plugin scan rule; category kept in frontmatter)
- **Frontmatter `name:`** = directory last segment
- **Frontmatter `category:`** ∈ {`bootstrap`, `plan`, `design`, `build`, `review`, `security`, `audit`, `shortcuts`, `ship`, `config`, `eval`, `onboard`, `repair`, `status`}

### Naming pattern per category

| Category | Pattern | Examples |
|---|---|---|
| `bootstrap` | `<category>-<instrument>` | `bootstrap-sanity`, `bootstrap-codebase-map`, `bootstrap-active-hooks`, `ci-setup` (slash brevity; see note) |
| `plan` | (none — `plan` is standalone) | — |
| `design` | `design-<instrument>` | (deprecated — merged into plan) |
| `build` | `build-<discipline>` | `build-engine`, `build-tdd`, `build-debug`, `build-verify`, `build-simplify`, `build-methodology` |
| `review` | `review-<subject>` | (none — `review` is standalone) |
| `security` | `security-<subject>` | (none — `security` is standalone) |
| `audit` | `audit-<subject>` | `audit-slop`, `audit-secret` |
| `shortcuts` | `shortcut-<name>` | `shortcut-tdd-fast`, `shortcut-quick-fix` |
| `ship` | (no skill, gate only) | — |

## Slash command

- **Prefix**: `/dev-kit:`
- **0-arg**: All main commands take no arguments.
- **Format**: `/dev-kit:<stage>` (shortcut: `/dev-kit:<shortcut>`)

## Markdown docs / hand-off

- `docs/{STAGES,NAMING,COST-ANALYSIS,PRE-IMPL-CHECK}.md` (PascalCase or kebab-case singular)
- ADR: `docs/adr/ADR-NNNN-kebab-slug.md` (zero-padded)
- Hand-off: `hand-off/<from>→<to>.md` (Unicode arrow →; debug retry uses ↔)
- Loop log: `.dev-kit/loop-log.json` (singular)
- Examples: `examples/sample-<descriptor>.md`

## Code (Python)

- File: `snake_case.py`
- Function: `snake_case()`
- Class: `PascalCase`
- Constant: `UPPER_SNAKE_CASE`
- Private: `_leading_underscore()`

## Bash

- File: `kebab-case.sh` (action suffix)
- Function: `snake_case()`
- Environment variable: `UPPER_SNAKE`
- Local variable: `lower_snake`

## JSON

- File: `kebab-case.json` (`marketplace.json`, `.active-hooks.json`)
- Key: `snake_case`

## Hook script

- `hooks/<verb>-<noun>.sh` (e.g., `tdd-guard.sh`, `slop-detector.sh`)
- Shebang: `#!/usr/bin/env bash`

## Regression verification

`tests/test_naming.py` — `name` in SKILL.md frontmatter = directory name. `category:` ∈ allowed set. Etc.
