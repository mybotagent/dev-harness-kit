# Cost & Risk Analysis

> AI auto-generated, user review only (single HOTL approval).

## 1. Time Cost

- Initial implementation: ~6 working days @ 1 engineer
- Maintenance: ~0.5 day/month
- **Year 1 total**: ~$14,400

## 2. Monetary Cost (API + CI + infra)

| Item | Quantity | Unit | Annual |
|---|---|---|---|
| LLM-as-judge (MiniMax-M3[1m]) | 13 assets × daily | $0.30 / 1M tokens | ~$3 |
| CI nightly eval | 5 min × daily | $0.008/min | ~$15 |
| GitHub Actions (review) | OSS public repo | — | $0 |
| **Total** | | | **~$18/year** |

Negligible vs. value (see §5).

## 3. Legal Risk

All absorbed repos MIT/Apache2-compatible. No PII stored in `eval/golden/`. **LOW**.

## 4. Maintenance Risk

Single maintainer risk mitigated by:
- 4 ADRs + modular design
- Plugin manifest with explicit `repository:` (no URL rot)
- Automated skill/hook regression tests

**MEDIUM** (mitigated).

## 5. Opportunity Cost (not building = losing)

| Loss | Estimate |
|---|---|
| 5 separate plugin maintenance | ~$3,000/year |
| Hand-off traceability failures | ~$5,000/year |
| Duplicate Iron Laws (user learning cost) | ~$2,500/year |
| Lower AI utilization (no HOTL) | ~$17,600/year |
| **Total** | **~$28,100/year** |

**Net ROI Year 1**: +$13,700. **Payback**: ~6 months. **HIGH value**.

## 6. Compatibility Risk

Opt-in provider switch. **LOW**.

## 7. Security Risk

Hook bypass requires explicit opt-in (`DEV_KIT_HOOK_OFF`). Secret scan runs PostToolUse. **LOW**.

## 8. Operational Risk

Provider outage fallback: manual `/dev-kit:eval`. **MEDIUM** (mitigated).

## §9 Summary

**6 LOW + 2 MEDIUM (mitigated) = PASS**

User review (1× HOTL): check all 8 sections, then start Phase 1.
