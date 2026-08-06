> [← Skills index](README.md) · [Project README](../../README.md)

# `docs-maintenance`

**Category:** `audit` · **Alpha:** `analysis` · **Invocation:** `/dev-kit:docs-maintenance` (human-invoked)

The project README is the most important document in any repository. `docs-maintenance` treats it as such: every run **always audits and verifies the README** for false-positive (claims that don't exist) and false-negative (capabilities the README misses) drift, and **updates the README when needed** to reflect the current source of truth. A correct no-change run still produces a per-entry `kept | updated | removed` audit trail — the audit is the deliverable, not a forced edit. The skill then audits the rest of the documentation, removes or marks superseded operational guidance, and keeps volatile inventory facts (skill counts, exhaustive lists, cache versions, commit SHAs) out of prose. It is scoped to documentation changes only and must not silently change product behavior.

## When to use it

- The user types `/dev-kit:docs-maintenance`.
- The user asks to clean outdated docs, update the README, or "fix the README".
- A plugin, skill, cache-refresh workflow, or repository layout has changed.
- Documentation contains hard-coded counts, exhaustive inventories, or stale commands.

## How it works

The skill runs a four-step workflow:

1. **Build the documentation map (README first).** Open the project `README.md` (or whichever README the repo uses) and read it end-to-end before touching anything else. Every claim in it is a candidate for the validation pass in step 4. Then read the documentation index files, relevant rules, manifests, and the scripts the README names. Search for stale terms, removed paths, old commands, hard-coded inventory counts, and duplicated instructions with `rg` — starting the searches from the README's code blocks. Use `git log` and targeted `git show` to distinguish an intentional historical record from an outdated current instruction.
2. **Classify before changing.** Only **remove** a document when it is an obsolete operational document with no unique policy, rationale, or historical value. **Update** current guides whose commands, paths, or behavior no longer match the source of truth. **Preserve** ADRs and changelogs as historical records, revising only misleading present-tense claims and stating the historical scope when needed. Never create a second source of truth for generated metadata — point to the manifest, filesystem discovery, or a validation command instead.
3. **Refresh the README (mandatory).** This step is never skipped. If the README needs no changes, the run still records a `kept` audit row per entry — the audit trail is the deliverable, not a reason to skip. Keep the README answer-first and task-oriented. For cache updates, document the maintained updater script, its dry-run mode, environment overrides, the manifest/cache verification output, and the required client restart — explaining the Claude and Codex paths separately when their commands or cache locations differ. Replace exhaustive lists and fixed counts with stable concepts and discovery commands; do not add current versions, commit identifiers, skill totals, or manually maintained inventories merely to make the README look complete. For every README entry touched, record one row: `entry → kept | updated | removed` with the source-of-truth file that justified the change.
4. **Validate the result (README first).** README verification runs before the rest of the documentation check; if the README fails false-positive or false-negative, fix it and re-run before touching the rest of the docs. Then run `rg` searches for removed paths and stale commands, verify Markdown links and code examples against the filesystem, validate every changed skill with the repository's skill validator, and run the focused tests plus the full relevant suite, reporting exact commands and quoted exit codes/test counts.

The bidirectional documentation check runs in this order: a **README false-positive check** (every path, command, script, flag, env var, manifest field, link, and workflow claim from the README must exist and behave as described), a **README false-negative check** (every user-facing CLI command, script, public skill, configuration file, and recent user-facing change must be reachable from the README, directly or via a single link), then a **repo-wide false-positive check** and a **repo-wide false-negative check** (current manifests, executable scripts, user-invocable skill frontmatter, README-referenced workflows, and recent user-facing changes must each have a suitable documentation entry, without hiding a real feature to avoid a stale claim). README rows are reported first; the rest follow. Each checked claim is recorded as `documented → verified`, `documented → missing`, or `exists → undocumented`; the latter two must be resolved before completion unless explicitly explained as an intentional internal/historical exception. Evidence comes from the filesystem, manifests, executable `--help` output, tests, and recent commits — never from a prior README, a generated cache, or an unverified agent assertion.

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
