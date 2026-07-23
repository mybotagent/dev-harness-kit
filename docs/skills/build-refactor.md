> [← Skills index](README.md) · [Project README](../../README.md)

# `build-refactor`

**Category:** `build` · **Alpha:** `enforcement` · **Invocation:** Model-invoked sub-skill of `/dev-kit:refactor` — not exposed in slash autocomplete, never typed directly

`build-refactor` (previously named `build-simplify`, renamed to match its parent `/dev-kit:refactor` skill) is the mutation phase of the refactor pipeline: a 4-pass cleanup that rewrites, extracts, and renames code without changing its behavior. It exists as a distinct skill because cleanup work is dangerous without a hard gate — its Iron Law is that no cleanup happens without a regression test, and each pass must leave the affected tests green before the next pass starts. For actual code *deletion* (slop, dead features, orphan code) the sibling skill is `/dev-kit:prune`, whose 3-pass deletion sweep is inlined into `skills/prune/SKILL.md` as "Phase 2" — `build-refactor` explicitly does not delete whole files or features.

## When to use it

- The user's language matches "cleanup" / "refactor" / "simplify".
- It runs as the internal sub-skill invoked by `/dev-kit:refactor`.

## How it works

The skill runs four passes, each a separate call:

1. **DEAD CODE** — remove unused exports, dead branches, and commented-out blocks. `Grep` is used with permission to find all references first. Requires a green regression test before the next pass.
2. **DUPLICATION** — find the same logic repeated in two or more places and extract a helper or module. Requires a green regression test before the next pass.
3. **NAMING** — make variable, function, file, and module names clear. Requires a green regression test before the next pass.
4. **COVERAGE** — boost weak tests, targeting the hot path and edge cases. Requires the full test suite to be green.

Rules enforced: the 4 passes must not be bundled into one cycle (MUST-NO-LOOP); one pass covers one kind of change, and a regression test pass is confirmed after each; measurements come first (e.g. `coverage report --include=src/lib`) rather than guessing. Because this skill refactors rather than deletes, whole-unused-module deletion is explicitly out of scope — that dispatches to `/dev-kit:prune`.

The build stage's hooks are active during this skill's passes; `tdd-guard` passes as long as test changes accompany the edit (which helps with renames).

## Invoked automatically

`build-refactor` is a model-invoked sub-skill — it has no direct slash command and does not appear in slash autocomplete. It runs as part of `/dev-kit:refactor`'s phase 2.

## Output

No standalone report file — the skill's deliverable is the 4 passes themselves, each confirmed by a quoted regression-test pass, ending in a full green test suite.

## Red flags

| Thought | Reality |
|---|---|
| "Do all 4 passes at once" | Can't tell which pass caused regression |
| "Leave tests as-is" | L1 violation |
| "Comment out to disable" | L4 violation |
| "Verify later" | L3 violation |
| "Delete the whole unused module" | Out of scope. Use `/dev-kit:prune` (its Phase 2 3-pass sweep). |

## Related

- [refactor](refactor.md) — the parent pipeline skill; phase 1 (`/dev-kit:inspect`) is read first to prioritize which passes to run, and phase 3 (`/dev-kit:review`) follows after all 4 passes are green.
- [prune](prune.md) — the sibling deletion skill; whole-file or whole-feature deletion candidates surfaced during a pass are handed off here instead of continued in `build-refactor`.

---
*Source: [`skills/build-refactor/SKILL.md`](../../skills/build-refactor/SKILL.md)*
