---
name: proposal
category: design
description: 0-arg HTML renderer for design proposals / plans. Renders any docs/proposals/<name>.yaml to docs/proposals/<name>.html for pre-implementation review.
alpha: state
when_to_use: |
  - User types /dev-kit:proposal
  - User wants to share a draft proposal/plan with reviewers before implementation
  - User wants to view an existing proposal as a single self-contained HTML doc
allowed-tools: Read Bash
disallowed-tools: Write Edit
model: sonnet
user-invocable: true
---

# /dev-kit:proposal -- design proposal HTML viewer

Renders any `docs/proposals/<name>.yaml` proposal to a single self-contained HTML document at `docs/proposals/<name>.html`. The skill is generic across proposals; the MCP harness content (issue #280) is one example input, not the skill's purpose.

**Why a separate skill, not a flag on `/dev-kit:report` or `/dev-kit:plan`**: the user has to remember the flag and slash autocomplete does not surface flags. Proposals are a distinct artifact (pre-implementation plans) with a distinct lifecycle (designed → reviewed → accepted/rejected → implemented). The slash is the entrypoint; the YAML→HTML render is the work.

## What it does

1. List available proposals: `python3 bin/dev-kit-proposal.py --list`
2. Render one: `python3 bin/dev-kit-proposal.py <name>` writes `docs/proposals/<name>.html`
3. Print the file path so the user can open it in a browser (`open docs/proposals/<name>.html` on macOS, or any browser via `file://`).
4. Stop. The skill does not edit or write the YAML — the user authors the proposal; this skill renders.

## Output (in chat)

```
## /dev-kit:proposal -- <name>

**Source**: docs/proposals/<name>.yaml
**Output**: docs/proposals/<name>.html (one self-contained HTML doc, inline CSS only, no JS, dark-mode aware)
**Status**: <status from YAML frontmatter>
**Sections**: <count>

**Open in browser**: `open docs/proposals/<name>.html` (macOS)
```

## Authoring a proposal

Create `docs/proposals/<name>.yaml` with this shape:

```yaml
title: <one-line title>
status: draft | design-discussion | ready-for-review | accepted | rejected | superseded
issue: <issue number, optional>
date: YYYY-MM-DD
tags: [<tag1>, <tag2>]
sections:
  - title: <section 1>
    body: |
      Markdown-lite body. Supports:

      - # ## ### headings
      - paragraphs
      - **bold**, *italic*, `code`
      - [link text](https://...)
      - unordered (- ) and ordered (1. ) lists
      - | GFM tables |
      - ``` fenced code blocks ```
      - > blockquotes
      - --- horizontal rules
  - title: <section 2>
    body: |
      ...
```

Then run `/dev-kit:proposal <name>` to render.

## Why this is `alpha: state`

Per CLAUDE.md Iron Law L6, every new skill must declare an `alpha:` field. The proposal artifact has **stateful lifecycle**: a YAML source on disk, a derived HTML rendered from it, a status tag (draft → design-discussion → ready-for-review → accepted/rejected/superseded) that the maintainer advances over time. That is `state` by definition — the skill persists a proposal artifact and gates its progression, distinct from analysis (reasoning over a corpus) and enforcement (deterministic guards).

**L7 fit**: the deterministic render + status-tag + HTML-escape contract is exactly the part next-gen models can't self-impose. The model can reason about *whether* a proposal should be accepted; the skill owns *how* the artifact is rendered, versioned, and surfaced for review.

## Iron Law

**Defensive HTML escaping on every interpolated value.** The renderer escapes titles, anchors, free-text fields, and link URLs. A title with `<script>` in it renders as `&lt;script&gt;` -- the browser never executes it. The contract is enforced by `tests/test_proposal_skill.py:test_html_escapes_user_content`.

**No `<script>` tag, no external assets, inline CSS only.** The output is safe to email, archive, or open from `file://`. Mirrors the `/dev-kit:report` invariant.

## Hand-off

Next: open `docs/proposals/<name>.html` in a browser, share the file with reviewers, then update the YAML's `status:` field as the proposal progresses through review.

After a proposal is `accepted:`, the implementation work follows `/dev-kit:plan` → `/dev-kit:build`. The proposal itself is the design record that closes the issue.

## Editing the proposal

The YAML is hand-edited, not generated. Re-run `/dev-kit:proposal <name>` to refresh the HTML.

## Related

- `lib/render_proposal_html.py` -- pure function: `parse_proposal_yaml` + `render`
- `bin/dev-kit-proposal.py` -- CLI driver
- `lib/render_report_html.py` -- sibling renderer (eval + inspect reports)
- `bin/dev-kit-report.py` -- sibling CLI driver
- `skills/report/SKILL.md` -- sibling skill pattern (read-only skill + bin CLI driver)
- `docs/proposals/` -- proposal source/output directory (YAML in, HTML out)
- Issue #280 -- the MCP harness analysis is the first proposal authored against this skill