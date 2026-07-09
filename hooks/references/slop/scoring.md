# slop-detector v2 — 5-dim scoring rubric (1-10, total 50)

Rate 1-10 on each dimension. Below 35/50 → revise (per hardikpandya/stop-slop).

| Dimension | Question |
|-----------|----------|
| Directness | Statements or announcements? |
| Rhythm | Varied or metronomic? |
| Trust | Respects reader intelligence? |
| Authenticity | Sounds human? |
| Density | Anything cuttable? |

## Severity ladder

The audit-slop skill applies this ladder to translate raw match counts into a HIGH / MEDIUM / LOW bucket.

| Match count (T1+T2) | Bucket | Action |
|---|---|---|
| ≥ 6 unique patterns OR any KO structure | **HIGH** | block advisory + show fix hints |
| 3-5 unique patterns | **MEDIUM** | block advisory, no fix hints |
| 1-2 unique patterns | **LOW** | log only |

## Per-pattern weights (advanced)

When more precision is wanted, weight each tier separately instead of stacking:

| Tier | What it catches | Weight |
|---|---|---|
| T1 PHRASE | throat-clearing + emphasis + jargon + adverbs + meta | 3 |
| T2 STRUCTURE | binary contrast + false agency + Wh-starters + lazy extremes + KO structure | 2 |
| T3 RHYTHM | em-dash density + three-item lists + dramatic fragmentation | 1 |

Weighted total ≥ 12 → HIGH. 6-11 → MEDIUM. <6 → LOW.

## Default behavior

The post-write hook uses **bucket mode**: any single T1 (phrase) match → advisory stderr at severity LOW+; ≥2 unique T1 OR ≥1 T2 → MEDIUM; ≥3 unique OR ≥1 KO structure → HIGH. T3 (rhythm) is off by default to avoid noise in code commits — opt in via `SLOP_LEVEL=3`.
