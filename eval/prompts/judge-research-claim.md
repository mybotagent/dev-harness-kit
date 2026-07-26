# Eval: Research Claim Dimension (judge-research-claim, v1.0.0)

You are judging the quality of **research claims** emitted by
`/dev-kit:research` after the citation gate runs. The unit of judgment is
one `verify()` call: a claim + the sources the engine attached to it.

Score 5 axes 0-10 each. All 5 axes mirror the review-dim shape so the
per-dim scoring rubric is uniform across `DIM_AXES` keys.

## Case

- **Case ID**: ${CASE_ID}
- **Dimension**: ${DIM}
- **Category**: ${CATEGORY} (e.g. `uncited-claim`, `agreement-N3`, `primary-source-missing`, `broken-url`, `cited-clean`)
- **Input claim** (the claim fed to `verify()`):
```
${INPUT}
```
- **Agent output** (the `verify()` return value, including citations + gaps):
```
${AGENT_OUTPUT}
```
- **Expected behavior** (the expected `verified` flag + confidence band):
```
${EXPECTED}
```

## Axes (0-10)

1. **citation_required** — does the agent reject uncited claims? 10 =
   every claim without a citation is rejected; 0 = every uncited claim
   passes. The `verified=False` floor for empty-source lists counts as
   a full pass on this axis.
2. **n_source_agreement** — when N >= 3 sources agree on the claim, does
   the engine raise confidence by the agreement boost? 10 = boost
   applied correctly across all agreement cases; 0 = boost missing on
   every agreement case.
3. **primary_source_present** — for claims that warrant a primary source
   (regulator, official doc, original publication), does at least one
   primary source appear in the citations? 10 = primary present when
   expected; 0 = primary missing on every claim that needs one.
4. **timestamp_present** — does every source carry an ISO `fetched_at`
   timestamp? 10 = every source has one; 0 = every source missing one.
   A missing-timestamp gap must be reflected in the `gaps` list.
5. **rubric_match** — does the engine's final verdict (`verified` /
   confidence band) match the rubric the eval case expected? 10 = exact
   match; 0 = inverted (verified=True when expected False, or vice
   versa, with a confidence delta > 0.3).

## Output Format

ONLY a JSON object (no prose). 5 axes, each 0-10:

```json
{"citation_required":N,"n_source_agreement":N,"primary_source_present":N,"timestamp_present":N,"rubric_match":N}
```
