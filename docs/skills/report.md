> [← Skills index](README.md) · [Project README](../../README.md)

# `report`

**Category:** `audit` · **Alpha:** `analysis` · **Invocation:** `/dev-kit:report` (human-invoked)

`report` renders the two latest markdown reports produced by `/dev-kit:evaluate` and `/dev-kit:inspect` into one self-contained HTML file at `.dev-kit/report.html`. It exists as its own skill rather than an `--html` flag on either producer because "view the report in a browser" is a distinct human action with a distinct artifact — the user has to remember a flag and slash autocomplete does not surface flags, so a dedicated command is the better UX.

## When to use it

- The user types `/dev-kit:report`.
- The user wants to share eval + inspect results with non-technical reviewers.
- The user wants a pre-release dashboard view.

## How it works

1. Read `.dev-kit/eval-report.md` (if present) and `.dev-kit/inspect-report.md` (if present).
2. Hand the two strings to `lib/render_report_html.py:render(eval_md, inspect_md) -> str`, a pure function with no I/O.
3. Hand the result to `bin/dev-kit-report.py`, a tiny CLI driver that writes the file. The skill itself is read-only (`disallowed-tools: Write Edit`); the actual write is the CLI driver's job, mirroring how `/dev-kit:inspect` keeps its skill body pure.

If either source report is missing, its section renders a yellow "not found" banner naming the command to run to produce it. Re-running `/dev-kit:report` at any time re-renders from whatever is currently on disk — there is no caching.

## Usage

```bash
/dev-kit:report
```

No flags — 0-arg by design.

## Output

`.dev-kit/report.html` — a single self-contained HTML document: no `<script>` tag, no `<link rel="stylesheet">`, no external `<img>`, inline CSS only, dark-mode aware (`@media (prefers-color-scheme: dark)`). Safe to email, archive, or open from `file://`.

Sections:

- **Header** — report title + generated-at timestamp.
- **Eval** — per-dim overall score cards (OK / DRIFT / ROT / Skipped), per-dim axis bars, per-case table.
- **Inspect** — verdict chip (Critical / Major drift / Minor drift / Healthy), coverage + precision, per-dim table, HIGH/MED/LOW finding blocks with TL;DR / Scenario / Fix.
- **Footer** — generator credit.

Color rules: `OK` / `Healthy` = green, `DRIFT_WARNING` / `Major drift` = amber, `ROT` / `Critical` = red, `SKIPPED` = gray (canonical map in `lib/render_report_html.py:VERDICT_CLASS`).

## Iron Law

Defensive HTML escaping on every interpolated value: the renderer escapes titles, anchors, file paths, and free-text fields, so a finding with a script tag in its title renders as inert escaped text rather than executing in the browser. This contract is enforced by `tests/test_render_report_html.py:test_html_escapes_user_content`.

## Related

- [eval](eval.md) — source of `.dev-kit/eval-report.md`.
- [inspect](inspect.md) — source of `.dev-kit/inspect-report.md`.
- `lib/render_report_html.py` — the pure rendering function.
- `bin/dev-kit-report.py` — the CLI driver that performs the write.
- `tests/test_render_report_html.py` — 20 pure-function tests, including the HTML-escaping contract.

---
*Source: [`skills/report/SKILL.md`](../../skills/report/SKILL.md)*
