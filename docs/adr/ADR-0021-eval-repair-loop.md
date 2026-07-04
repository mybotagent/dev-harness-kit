# ADR-0021 — Eval-Repair Loop with Human Review

**Status**: Accepted

## 결정
자산 drift 감지 → 자동 repair 루프. 마지막 단계 = 사용자가 diff 1회 approve.

## 8단계
```
[1] golden_set
[2] LLM as Judge (4축: semantic_drift / completeness / correctness / consistency)
[3] 실패 점수화 + root cause
[4] Specialized Fixer (9개 category 전문)
[5] Fix candidate → 재평가 (loop max 3)
[6] A/B Validation Regression (golden 불변)
[7] Diff 초안 자동 작성
[8] Human Review ← 동기 STOP, 사용자 approve|reject|defer
```

## 금지
- Auto commit diff ❌ (MUST-NOT-31).
- 자동 reject ❌ (사용자 결정).

## Specialized Fixers
9개 (bootstrap/plan/build/review/security/audit/iron_law/hooks/a2a). 각 category 5필드 frontmatter, hooks, scripts 정확히 알고 자가 수정.
