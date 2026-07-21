---
name: harness-proposal
category: design
description: 0-arg HTML proposal viewer for the MCP-harness / harness-types design discussion (issue #280). Renders the proposal at docs/proposals/harness-architecture.html.
alpha: analysis
when_to_use: |
  - User types /dev-kit:harness-proposal
  - User wants to see the MCP-harness design proposal
  - User wants to discuss or amend the proposal
allowed-tools: Read Bash
disallowed-tools: Write Edit
model: sonnet
user-invocable: true
---

# /dev-kit:harness-proposal -- MCP harness architecture proposal viewer

Renders the MCP-harness / harness-types design proposal as a single self-contained HTML document. The proposal is the substantive content of the design discussion for [issue #280](https://github.com/sh-ai-x/dev-harness-kit/issues/280).

**Why a separate skill, not a flag on an existing one**: the proposal is a distinct artifact (a design discussion document) tied to a specific issue. It is not a mode of `/dev-kit:plan` or `/dev-kit:inspect`. The slash is the entrypoint; the HTML is the output.

## What it does

1. Read `docs/proposals/harness-architecture.html` (single self-contained file).
2. Print a one-line summary of what the proposal covers.
3. Print the file path so the user can open it in a browser (`open docs/proposals/harness-architecture.html` on macOS, or any browser via `file://`).
4. Print a section index (the proposal's 8 sections).
5. Stop. The skill does not edit, regenerate, or write the HTML — that's the maintainer's job.

## Output (in chat)

```
## /dev-kit:harness-proposal -- issue #280 design thread

**File**: docs/proposals/harness-architecture.html (one self-contained HTML doc, ~16 KB, no JS, no external assets)
**Status**: OPEN issue · design discussion venue (corrected 2026-07-21 from earlier "deferred-with-decision" framing)

### Sections
1. TL;DR -- one-sentence summary + 4-card at-a-glance
2. When MCP harness is most needed -- validation / interview / research loops
3. MCP vs document harness -- side-by-side table
4. Hackathon principles mapped -- context / verification / scaffolding → repo surface
5. Harness types -- fit for dev-harness-kit -- command / skill / hook / doc / CLI / MCP / ACP
6. Strategic direction -- models-eat-harness thesis + defensible alpha
7. Recommendation -- minimal in-process MCP harness, three loop primitives
8. Open questions -- five questions for the #280 thread

**Open in browser**: `open docs/proposals/harness-architecture.html` (macOS)
```

## Why this is `alpha: analysis`

Per CLAUDE.md Iron Law L6, every new skill must declare an `alpha:` field. This skill renders a design discussion document — pure reasoning over a corpus. That is `analysis` by definition.

**Why we tolerate a new `analysis` skill** (L6 / L7 spirit): the user intent is distinct from existing analysis skills. The harness-proposal skill is the entrypoint for *the #280 design discussion*; it is not a competitor to `inspect` (code health), `prune` (slop removal), `review` (PR review), or `refactor` (cleanup). The distinct human action is "I want to read or amend the MCP-harness design proposal."

**Consolidation path**: if a second design-discussion proposal arises in a different area, fold both onto the same `lib/proposal_renderer.py` engine rather than forking a per-proposal renderer. Same consolidation principle as `lib/analysis-core`.

## Hand-off

Next: comment on [issue #280](https://github.com/sh-ai-x/dev-harness-kit/issues/280) with a link to the HTML and a "ready for review" note. The proposal is the discussion artifact; the issue is where consensus forms.

## Editing the proposal

The HTML at `docs/proposals/harness-architecture.html` is hand-edited, not generated. Edit it directly with `Edit` / `Write`. To keep it self-contained and safe to share, preserve these invariants:

- **No `<script>` tags.** Defensive HTML escaping is not enough — the file must not execute anything when opened from `file://`.
- **No external assets.** No `<link rel="stylesheet">`, no `<img src="https://...">`, no remote fonts. Inline CSS only.
- **Dark-mode aware.** Keep the `@media (prefers-color-scheme: dark)` block in sync when adding colors.
- **One HTML document.** Sections are `<h2>` blocks; the TOC at the top stays in sync with the body.

## Related

- [Issue #280](https://github.com/sh-ai-x/dev-harness-kit/issues/280) — design discussion thread
- `docs/ACP-DISPATCH.md` — adjacent ACP dispatch design (Agent Coordination Protocol)
- `docs/acp-harness.md` — broader ACP harness notes
- `lib/render_report_html.py` — sibling self-contained HTML renderer pattern (eval + inspect reports)
- `skills/report/SKILL.md` — sibling skill (HTML renderer for reports)
- `tools/parallel_dispatch.py` — fan-out primitive the research loop reuses
- `/dev-kit:repair` — Eval-Repair loop the validation loop extends