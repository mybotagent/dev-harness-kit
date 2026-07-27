# Eval: Research Source Dimension (judge-research-source, v1.0.0)

You are judging the quality of **research sources** surfaced by `/dev-kit:research`'s
`escalate()` engine (Phase 0-3) for one case fixture.

Score 5 axes 0-10 each. All 5 axes mirror the review-dim shape so the per-dim
scoring rubric is uniform across `DIM_AXES` keys.

## Case

- **Case ID**: ${CASE_ID}
- **Dimension**: ${DIM}
- **Category**: ${CATEGORY} (e.g. `cache-hit`, `multi-source`, `needs-human`, `primary-heavy`, `low-authority`)
- **Input query** (the query given to `escalate()`):
```
${INPUT}
```
- **Agent output** (the `escalate()` return value, including phase + sources):
```
${AGENT_OUTPUT}
```
- **Expected behavior** (the expected phase + source-quality floor):
```
${EXPECTED}
```

## Axes (0-10)

1. **authority_score** — for each source the agent surfaced, does the
   domain authority match what a careful researcher would assign? 10 =
   every source at the right authority tier (standards bodies / primary
   hosts > aggregators / tertiary blogs); 0 = wildly mis-ranked
   authority. Calibrate per-source; average.
2. **recency_score** — is each source recent enough for the topic? Hard
   news (last 30 days) vs evergreen docs (any time) is the calibration
   axis. 10 = every source at correct freshness; 0 = stale throughout.
3. **primary_vs_secondary** — does the source mix favor primary sources
   (original publication, regulator filing, official docs) over secondary
   (news coverage of the primary, third-party analysis)? 10 = primary-
   heavy when available; 0 = all secondary when a primary exists.
4. **url_validity** — for each source URL, does a HEAD request resolve?
   10 = every URL currently reachable; 0 = every URL broken. Partial
   credit per-URL.
5. **citation_completeness** — does each source carry all three required
   fields: `url`, `fetched_at`, `source_type`? 10 = every source has
   all three; 0 = every source missing one or more.

## Output Format

ONLY a JSON object (no prose). 5 axes, each 0-10:

```json
{"authority_score":N,"recency_score":N,"primary_vs_secondary":N,"url_validity":N,"citation_completeness":N}
```
