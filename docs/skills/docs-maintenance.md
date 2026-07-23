> [← Skills index](README.md) · [Project README](../../README.md)

# `docs-maintenance`

**Category:** `audit` · **Alpha:** `analysis` · **Invocation:** `/dev-kit:docs-maintenance` (human-invoked)

`docs-maintenance` audits repository documentation against the current implementation, removes or marks superseded operational guidance, and refreshes the README's user-facing workflows — while deliberately keeping volatile inventory facts (skill counts, exhaustive lists, cache versions, commit SHAs) out of prose. It is scoped to documentation changes only and must not silently change product behavior.

## When to use it

- The user types `/dev-kit:docs-maintenance`.
- The user asks to clean outdated docs or bring the README up to date.
- A plugin, skill, cache-refresh workflow, or repository layout has changed.
- Documentation contains hard-coded counts, exhaustive inventories, or stale commands.

## How it works

The skill runs a four-step workflow:

1. **Build the documentation map.** Read the README, documentation index files, relevant rules, manifests, and the scripts the docs name. Search for stale terms, removed paths, old commands, hard-coded inventory counts, and duplicated instructions with `rg`. Use `git log` and targeted `git show` to distinguish an intentional historical record from an outdated current instruction.
2. **Classify before changing.** Only **remove** a document when it is an obsolete operational document with no unique policy, rationale, or historical value. **Update** current guides whose commands, paths, or behavior no longer match the source of truth. **Preserve** ADRs and changelogs as historical records, revising only misleading present-tense claims and stating the historical scope when needed. Never create a second source of truth for generated metadata — point to the manifest, filesystem discovery, or a validation command instead.
3. **Refresh the README.** Keep it answer-first and task-oriented. For cache updates, document the maintained updater script, its dry-run mode, environment overrides, the manifest/cache verification output, and the required client restart — explaining the Claude and Codex paths separately when their commands or cache locations differ. Replace exhaustive lists and fixed counts with stable concepts and discovery commands; do not add current versions, commit identifiers, skill totals, or manually maintained inventories merely to make the README look complete.
4. **Validate the result.** Run `rg` searches for removed paths and stale commands, verify Markdown links and code examples against the filesystem, validate every changed skill with the repository's skill validator, and run the focused tests plus the full relevant suite, reporting exact commands and quoted exit codes/test counts.

Before declaring success, the skill performs a bidirectional documentation check: a **false-positive check** (every documented path, command, skill name, script, flag, manifest field, and workflow claim must exist and behave as described), and a **false-negative check** (current manifests, executable scripts, user-invocable skill frontmatter, README-referenced workflows, and recent user-facing changes must each have a suitable documentation entry, without hiding a real feature to avoid a stale claim). Each checked claim is recorded as `documented → verified`, `documented → missing`, or `exists → undocumented`; the latter two must be resolved before completion unless explicitly explained as an intentional internal/historical exception. Evidence comes from the filesystem, manifests, executable `--help` output, tests, and recent commits — never from a prior README, a generated cache, or an unverified agent assertion.

## Usage

```bash
/dev-kit:docs-maintenance
```

This skill takes no flags; it is a 0-arg audit-and-refresh pass over the whole documentation set. `allowed-tools` is `Read Write Edit Glob Bash`; `WebFetch` and `Agent` are disallowed.

## Output

Updated or removed documentation files (README and related operational docs), plus a report listing deleted files, updated files, the validation commands run, and their quoted exit codes or test counts, alongside the `documented → verified` / `documented → missing` / `exists → undocumented` evidence table.

## Related

- [audit](audit.md) — read-only slop/secret/drift sweep, a narrower cousin of this documentation audit.
- [inspect](inspect.md) — code-health sweep that can surface stale documentation-adjacent findings (`tokenbudget`, `slop`).
- `/dev-kit:review` — next step for a change review after this skill completes.
- `/dev-kit:ship` — next step once review and CI gates are satisfied.

---
*Source: [`skills/docs-maintenance/SKILL.md`](../../skills/docs-maintenance/SKILL.md)*
