---
name: docs-maintenance
category: audit
description: Audit repository documentation, remove superseded guidance, and refresh the README without recording volatile inventory facts.
alpha: analysis
when_to_use: |
  - User types /dev-kit:docs-maintenance
  - User asks to clean outdated docs or bring the README up to date
  - A plugin, skill, cache-refresh workflow, or repository layout has changed
  - Documentation contains hard-coded counts, exhaustive inventories, or stale commands
allowed-tools: Read Write Edit Glob Bash
disallowed-tools: WebFetch Agent
model: sonnet
disable-model-invocation: false
user-invocable: true
---

## What it does

Audits documentation against the repository's current source of truth, removes or marks superseded operational guidance, updates the README's user-facing workflows, and keeps volatile inventory details out of prose. It is intended for documentation changes only; it must not silently change product behavior.

## Reusable meta prompt

Use this prompt when delegating the same maintenance task to another agent:

```text
Audit this repository's documentation against the current implementation.

1. Find documents that are superseded, contradictory, or refer to removed files and remove them only when they have no historical or policy value. Preserve ADRs and historical records, but correct current-state claims or label them as historical.
2. Update the README and directly related operational docs to describe the current commands, paths, cache-refresh workflow, installation flow, and verification steps. Prefer the repository's scripts, manifests, tests, and recent commits as sources of truth.
3. Do not record volatile inventory facts in prose: skill counts, exhaustive skill lists, generated cache versions, commit SHAs, or other values that change whenever the repository evolves. Describe how to discover them instead.

Check both directions: every documented path/command/feature must exist (false-positive check), and every current user-facing capability must be represented where needed (false-negative check). Record `documented → verified`, `documented → missing`, and `exists → undocumented` evidence, resolving the latter two or explaining an intentional internal/historical exception. Run the narrow documentation/skill validation plus the relevant test suite. Report deleted files, updated files, validation commands, and quoted exit codes or test counts.
```

## Workflow

### 1. Build the documentation map

- Read the README, documentation index files, relevant rules, manifests, and the scripts named by the docs.
- Search for stale terms, removed paths, old commands, hard-coded inventory counts, and duplicated instructions with `rg`.
- Use recent history (`git log` and targeted `git show`) to distinguish an intentional historical record from an outdated current instruction.

### 2. Classify before changing

- **Remove** a document only when it is an obsolete operational document with no unique policy, rationale, or historical value.
- **Update** current guides when their commands, paths, or behavior no longer match the source of truth.
- **Preserve** ADRs and changelogs as historical records; revise only misleading present-tense claims and state the historical scope when needed.
- Do not create a second source of truth for generated metadata. Point to the manifest, filesystem discovery, or validation command instead.

### 3. Refresh the README

Keep the README answer-first and task-oriented. For cache updates, document the maintained updater script, its dry-run mode, environment overrides, the manifest/cache verification output, and the required client restart. Explain Claude and Codex paths separately when their commands or cache locations differ.

Replace exhaustive lists and fixed counts with stable concepts and discovery commands. Do not add current versions, commit identifiers, skill totals, or manually maintained inventories merely to make the README look complete.

### 4. Validate the result

Run `rg` searches for removed paths and stale commands, verify Markdown links and code examples against the filesystem, validate every changed skill with the repository's skill validator, and run the focused tests plus the full relevant suite. Report the exact commands and quoted exit codes/test counts.

Perform a bidirectional documentation check before declaring success:

- **False positive check:** extract every documented path, command, skill name,
  script, flag, manifest field, and workflow claim, then confirm that it exists
  and behaves as described. A document must not claim a file or command that is
  absent from the repository or unavailable in the stated client.
- **False negative check:** inspect current manifests, executable scripts,
  user-invocable skill frontmatter, README-referenced workflows, and recent
  user-facing changes, then confirm that each required current capability has a
  suitable documentation entry. Do not hide a real feature merely to avoid a
  stale claim.
- **Evidence rule:** record each checked claim as `documented → verified`,
  `documented → missing`, or `exists → undocumented`. Resolve the latter two
  before completion, except for intentionally internal or historical items;
  explain those exceptions in the report.

Use the filesystem, manifests, executable `--help` output, tests, and recent
commits as evidence. Do not treat a prior README, a generated cache, or an
unverified agent assertion as proof that a documented item exists.

## Next step

After this skill completes, invoke `/dev-kit:review` for a change review, or `/dev-kit:ship` once the repository's normal review and CI gates are satisfied.
