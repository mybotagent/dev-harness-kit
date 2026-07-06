---
paths:
  - "skills/**/SKILL.md"
---

# SKILL.md authoring rules (dev-harness-kit)

These rules apply when creating or editing any `SKILL.md` in this repo.

## File location (mandatory)

- **Flat**: `skills/<skill-name>/SKILL.md` — one level, no category subdir.
- Directory name MUST match `name:` frontmatter.

## Frontmatter (mandatory fields)

```yaml
---
name: <skill-name>            # MUST match directory name (kebab-case)
category: <category>          # MUST be one of 14 allowed values
description: <one-line English summary>
when_to_use: |
  - User types /dev-kit:<skill>
  - <other trigger 1>
  - <other trigger 2>
allowed-tools: Read Write Glob   # space-separated
disallowed-tools: Bash Edit     # space-separated (optional)
model: opus                    # default sonnet, override here
disable-model-invocation: false # true for HUMAN-USE only
user-invocable: true           # false for MODEL-USE only
---
```

### Human-use frontmatter example

```yaml
---
name: build
category: build
description: 0-arg build stage. Run per-step sub-agents via harness-runner.
disable-model-invocation: true   # prevent self-invocation
user-invocable: true             # expose as /dev-kit:build
---
```

### Model-use frontmatter example (contrast)

```yaml
---
name: build-tdd
category: build
description: Red-Green-Refactor cycle. Internal sub-skill of /dev-kit:build.
disable-model-invocation: false  # model may auto-invoke
user-invocable: false            # hidden from /dev-kit: skill list
safety:
  safety_valve: 8
  convergence: composite
  dedup_metric: identical-answer-cycle=2
---
```

## Human-use vs Model-use (mandatory classification)

| Class | `user-invocable` | `disable-model-invocation` | Slash exposed? |
|---|---|---|---|
| **Human-use** (stage commands, utilities, shortcuts) | `true` | `false` (default) or `true` | ✅ Yes |
| **Model-use** (internal building blocks) | **`false`** | `false` (default) | ❌ No |

**Current human-use skills** (14): `bootstrap`, `plan`, `build`, `review`, `security`, `audit`, `eval`, `repair`, `ship`, `status`, `onboard`, `config`, `shortcut-quick-fix`, `shortcut-tdd-fast`.

**Current model-use skills** (13): `plan-ralph`, `build-tdd`, `build-debug`, `build-engine`, `build-verify`, `build-simplify`, `build-methodology`, `build-harness-engine`, `bootstrap-sanity`, `bootstrap-codebase-map`, `bootstrap-active-hooks`, `audit-secret`, `audit-slop`.

## Body (mandatory style)

- **All text in English** (no Korean, even in code comments).
- `description:` ≤ 1 line.
- `when_to_use:` as bullet list, 2-5 items.
- Section headers `## H2`, `### H3` (no H1 — title is in frontmatter).
- Code blocks tagged with language (` ```ts `, ` ```bash `, etc.).
- First section: **what it does** in 1 paragraph.
- Last section: **next step** (which other skill to invoke).

## Forbidden patterns

- ❌ `it.only` / `it.skip` / `console.log` debugging in skill body.
- ❌ References to deleted files (`INTEGRATION.md`, `AX.md`, `commands/`).
- ❌ Hard-coded paths (use `skills/<name>/SKILL.md` style references).
- ❌ Claims without evidence ("works", "passes", "fast") — quote test counts, durations.

## Validation

- `tests/test_naming.py` enforces: `name` == directory name; `category` ∈ 14 values.
- `tests/test_smoke.py` enforces: exactly 28 skills total.
