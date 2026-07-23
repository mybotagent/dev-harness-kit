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

The current human-use and model-use inventories are defined by each skill's
`user-invocable` frontmatter. Do not duplicate those inventories or their
counts in this rule; inspect `skills/*/SKILL.md` when needed.

> Note: `simplify` → `refactor` rename (this PR) and `build-simplify` → `build-refactor` rename. The verb `simplify` still appears in the human-facing description of `refactor` (e.g., "refactor everything" is a common user phrase) but the skill name is `refactor`. For the deletion counterpart, see `/dev-kit:prune`.

> Note: `plan-ralph` was merged into `plan` (issue #58) — the plan skill is
> now self-contained and does not delegate to a non-invocable sub-skill.

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
- ❌ References to deleted files (`INTEGRATION.md`, `AX.md`).
- ❌ Hard-coded paths (use `skills/<name>/SKILL.md` style references).
- ❌ Claims without evidence ("works", "passes", "fast") — quote test counts, durations.

## Validation

- `tests/test_naming.py` enforces: `name` == directory name; `category` ∈ 14 values.
- `tests/test_smoke.py` enforces the repository's internal skill-layout invariant. Update its test fixture when adding a skill, but do not copy the resulting count into documentation.

## L6 skill gate — the alpha must be enforceable

**L6 rule.** Every `SKILL.md` added to `skills/<name>/` MUST declare an
`alpha:` frontmatter field. The value MUST be one of:

| `alpha:` | Meaning | Example skills |
|---|---|---|
| `state` | Drives the harness state machine — moves between stages, persists progress, gates transitions. | `plan`, `build`, `bootstrap`, `ship`, `onboard`, `shortcut-tdd-fast` |
| `enforcement` | Deterministic guard — runs hooks, scanners, validators, gates. The user can't talk their way past it. | `audit`, `repair`, `eval`, `security-when-guard` |
| `analysis` | Pure reasoning over a corpus — review, inspect, prune, refactor. **Tolerated** only because distinct human intents drive distinct slash entrypoints. | `review`, `inspect`, `prune`, `refactor` |

`analysis` is the *easy* one to write and the easiest for next-gen models to
absorb (Noam Brown / Logan Kilpatrick thesis: harness functionality gets
sucked into the model). New `analysis` skills therefore require a
justification: what distinct user intent does this slash serve that the
existing `analysis` set doesn't? Consolidate onto the shared
`lib/analysis-core` engine (#261) wherever possible; do not fork a new
analysis engine per slash.

### Why this gate exists

The repo's 39 skills over-invested in stateless reasoning surfaces that
next-gen models will absorb. Codifying the rule stops re-accumulating new
wrappers without forcing every existing skill through a migration sweep —
the gate applies only to skills added *after* `origin/main`. See
`CLAUDE.md` §1 L6 + L7.

### Lint: `tests/test_skill_governance.py`

- Computes the baseline from `origin/main`'s `skills/` tree
  (`git ls-tree -d --name-only origin/main skills/`).
- For any skill directory present locally but NOT in the baseline (i.e.
  added by the current PR), asserts the SKILL.md's frontmatter has
  `alpha:` ∈ {`state`, `enforcement`, `analysis`}.
- Fails with the offending skill name when violated.
- Falls back to the local `main` branch, then to `git log
  --diff-filter=A --name-only main -- skills/`, if `origin/main` is
  unreachable (offline CI, fresh clone). The source label is surfaced in
  the failure message so a reviewer can see which tier was used.
- Passes vacuously on a clean branch (zero added skills).

Run: `python3 -m pytest tests/test_skill_governance.py -v`.

### Skill-creator / plugin-creator interview (forward spec)

The future `skill-creator` and `plugin-creator` interviews MUST ask the
following question *before* emitting SKILL.md frontmatter, and the
answer MUST be reflected in the `alpha:` field:

> **(a)** Does this skill drive a stage of the harness state machine,
> enforce a deterministic guard, or run pure analysis over a corpus?
>
> **(b)** If the answer is *analysis*: what distinct user intent does this
> slash serve that the existing `analysis` set doesn't, and why does it
> need its own entrypoint instead of being a flag on an existing one?
> *(no `analysis` skill ships without a written justification in its PR body.)*

Neither creator exists in this repo today. This spec is pinned in the rule
so when they land they inherit the gate by construction, not by retrofit.

### Out of scope (honest failure modes)

- **Renames / moves**: the lint compares directory *names*, so a skill
  renamed `foo` → `bar` in the same PR appears as a removed skill + a
  new skill (the new one must declare `alpha:`). This is intentional —
  the gate should not bless a rename that silently rotates the alpha.
- **Sub-skill splits**: when a skill is split into `foo` + `foo-sub`,
  both new directories must declare `alpha:` independently. Sub-skills
  inherit no alpha from their parent.
- **Documentation-only**: a SKILL.md whose frontmatter contains no
  `alpha:` because the directory is "just docs" is still a violation. The
  gate does not distinguish skill-shaped docs from real skills; the
  latter are the only kind allowed under `skills/`.
- **Existing 39 skills**: out of the gate's scope. Migration is a
  separate effort and is intentionally not bundled into this PR.
