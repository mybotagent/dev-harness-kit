---
name: report
category: audit
description: 0-arg HTML renderer for the latest eval + inspect markdown reports. One self-contained .dev-kit/report.html. No options, no JS, no external assets.
when_to_use: |
  - User types /dev-kit:report
  - User wants to share eval + inspect results with non-technical reviewers
  - Pre-release dashboard view
allowed-tools: Read Bash
disallowed-tools: Write Edit
model: haiku
user-invocable: true
---

# /dev-kit:report -- HTML report viewer

Read the two latest markdown reports from `.dev-kit/` and write one
self-contained HTML file at `.dev-kit/report.html`. Distinct human
action ("view the report in a browser") with a distinct artifact.

**Why a separate skill, not an `--html` flag on `/dev-kit:eval` or
`/dev-kit:inspect`**: the user has to remember the flag and slash
autocomplete does not surface flags. The HTML rendering is a separate
action with a separate output, not a mode variation of eval or
inspect.

## What it does

1. Read `.dev-kit/eval-report.md` (if present) and
   `.dev-kit/inspect-report.md` (if present).
2. Hand the two strings to
   `lib/render_report_html.py:render(eval_md, inspect_md) -> str`
   (a pure function, no I/O).
3. Hand the result to `bin/dev-kit-report.py` -- a tiny CLI driver
   that writes the file. The skill itself is read-only
   (`disallowed-tools: Write Edit`); the write is the CLI driver's
   job, mirroring how `/dev-kit:inspect` keeps the skill body pure.

## Output

`.dev-kit/report.html` -- single self-contained HTML document. No
`<script>` tag, no `<link rel="stylesheet">`, no external `<img>`.
Inline CSS only. Dark-mode aware (`@media (prefers-color-scheme:
dark)`). Safe to email, archive, or open from `file://`.

Sections:

- **Header**: report title + generated-at timestamp
- **Eval**: per-dim overall score cards (OK / DRIFT / ROT / Skipped),
  per-dim axis bars, per-case table
- **Inspect**: verdict chip (Critical / Major drift / Minor drift /
  Healthy), coverage + precision, per-dim table, HIGH/MED/LOW finding
  blocks with TL;DR / Scenario / Fix
- **Footer**: generator credit

Color rules: OK / Healthy = green, DRIFT_WARNING / Major drift = amber,
ROT / Critical = red, SKIPPED = gray. See
`lib/render_report_html.py:VERDICT_CLASS` for the canonical map.

## Iron Law

**Defensive HTML escaping on every interpolated value.** The renderer
escapes titles, anchors, file paths, and free-text fields. A finding
with `<script>` in the title renders as `&lt;script&gt;...` -- the
browser never executes it. The contract is enforced by
`tests/test_render_report_html.py:test_html_escapes_user_content`.

## Hand-off

Previous: `/dev-kit:eval` (writes `eval-report.md`),
`/dev-kit:inspect` (writes `inspect-report.md`).

If either report is missing, the corresponding section renders a
yellow "not found" banner with the command to run. The user can run
`/dev-kit:report` at any time -- it re-renders from the current
artifacts on disk, no caching.

## Related

- `/dev-kit:eval` -- source of `eval-report.md`
- `/dev-kit:inspect` -- source of `inspect-report.md`
- `lib/render_report_html.py` -- pure function that does the work
- `bin/dev-kit-report.py` -- CLI driver that writes the file
- `tests/test_render_report_html.py` -- 20 pure-function tests

Next: open `.dev-kit/report.html` in a browser, or share the file.
