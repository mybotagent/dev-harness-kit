# Maintenance Judge (judge-maintenance, v1.0.0)

Used by `.github/workflows/maintenance.yml` (the dedicated CI
maintenance gate) via the `claude-code-action` running
`/dev-kit:maintenance --diff <PR>`. Judges the PR diff on three
axes and feeds the CI gate's verdict derivation (`code_sanity_score`
≥ 8 → OK, ≥ 5 → DRIFT_WARNING, else ROT).

The judge prompt wraps the canonical 20-checkbox rubric at
`eval/prompts/judge-code-sanity.md` and asks the model to emit three
composite axes that downstream callers (the CI gate + the docs-updated
sub-gate) can use directly.

## Inputs

- `${PR_DIFF}` — `gh pr diff` output for the PR under review (truncated
  to ~16 KB by the agent).
- `${PR_BODY}` — the PR description, used to surface stated purpose,
  linked issues, and "docs not required" justifications.
- `${RUBRIC}` — the full content of `judge-code-sanity.md`, embedded so
  the judge has the SSOT for CC-1..8 / OE-1..8 / VM-1..4 in front of
  it. The judge must reference the rubric items when scoring; this is
  the deterministic-vs-modeled split required by Iron Law L6.

## Axes (each 0-10; aggregate = mean, then verdict_from_score)

- `code_sanity_score` — Composite of the 20-checkbox rubric. Apply each
  item ONLY when the relevant pattern is present in the PR_DIFF.
  Sub-score = `(items_flagged / items_present_in_input) * 10` for
  each of clean-code (8), over-engineering (8), value/meaning (4). If
  a sub-rubric has no applicable items, score it 10 (vacuously clean).
  Composite =
  `0.4 * clean + 0.4 * over_eng + 0.2 * value`.

- `docs_coverage_score` — Does the PR touch a `docs/` file that
  corresponds to the code it changes? Mirrors the CI gate's
  docs-updated sub-gate: if any changed file lives under `lib/`,
  `tools/`, `hooks/`, `skills/`, or `.githooks/`, the PR must also
  touch at least one file under `docs/` (excluding
  `docs/STAGES.md` / `docs/REPOSITORY-MAP.md` which are auto-managed)
  OR the PR body must explicitly justify "docs not required" with a
  quoted link to a pre-existing doc that covers the change.
  Score = 10 when docs are present or justified; 0 when neither.

- `scope_discipline_score` — Direct mirror of VM-3 + VM-4 from
  `judge-code-sanity.md`. Does the diff match the PR's stated
  purpose? No unrelated drive-by edits, no bundling. Score = 10 for
  clean scope; scaled down for churn/cosmetic noise.

## Output format

Respond ONLY with a single JSON object:

```json
{
  "code_sanity_score": <0-10>,
  "docs_coverage_score": <0-10>,
  "scope_discipline_score": <0-10>,
  "reason": "<one short sentence naming the worst axis>",
  "items_flagged": ["CC-2", "OE-1", "VM-3"]
}
```

`items_flagged` is a list of rubric IDs the model actually flagged in
this PR (subset of CC-1..8 / OE-1..8 / VM-1..4). Empty list when no
rubric items were flagged.

No prose before or after. The `reason` string is what the CI gate
posts as a PR comment when the verdict is not OK.