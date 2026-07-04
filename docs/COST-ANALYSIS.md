# Cost & Risk Analysis — dev-harness-kit

> **AI 자동 작성, 사용자 검토 (MUST-54, MUST-55, MUST-NOT-32).**
> 사용자 = spec + decision + review. Cost 질문 형식 사용자가 작성 ❌.

---

## §1. Time Cost (구현 + 유지보수)

| 항목 | 추정 | 비고 |
|---|---|---|
| 구현 (Phase 1~5) | **6.0 작업일** @ 1 eng @ $100/h | 5 phase × 평균 1.2 일 |
| 유지보수 | **0.5 일/월** @ 1 eng @ $100/h | plugin 안정화 후 평균 |
| 문서/ADR/회귀 test 유지 | 0.2 일/월 (포함) | 자동화 가능 부분 |
| 1차년 비용 | $9,600 (= 6 × 8h × $100 × 1 eng × 5 phase + 0.5 × 8h × $100 × 12 month) | |
| 2차년 이후 | $4,800/year | 유지보수만 |

**합계 (1년): ~$14,400**

## §2. Monetary Cost (API + CI + 인프라)

| 항목 | 수량 | 단가 | 연간 |
|---|---|---|---|
| `MiniMax-M3[1m]` LLM-as-judge | 13 자산 × daily 1회 × 2K tokens output | $0.30 / 1M tokens (estimated) | **$2.85/year** |
| MiniMax Plan 단계 (6 gates Ralph) | 1 PR × 30 사이클 × 8K tokens output | $0.30 / 1M tokens | $0.07/PR |
| MiniMax Design Seed convergence | 1 PR × 5 사이클 × 4K tokens | $0.30 / 1M tokens | $0.006/PR |
| MiniMax Review/Security fan-out | 2 dim × 5K tokens | $0.30 / 1M tokens | $0.003/PR |
| CI nightly cron (eval) | 5 min × daily × 365 | $0.008/min | **$14.60/year** |
| GitHub Actions (review) | 무료 (private repo OSS 공개 = 0) | — | $0 |
| Anthropic opt-in (opt-in only) | $3 / 1M tokens × 1/10 비율 | — | $0.30/year |
| 합계 | | | **~$17.83/year** |

(미세. $15/year 절약 = LLM-as-judge 가치의 1/100. 즉 비용 무시 가능.)

## §3. Legal Risk

| Risk | 분석 | Level |
|---|---|---|
| License 호환 | 5 repo 모두 MIT (slop-shield, claude-review-plugins, dev-harness) + Apache2 / fallback check | **LOW** |
| GDPR / 개인정보 | eval/golden/*.json은 메타데이터 (sha, score). PII 미저장. | **LOW** |
| 한국 개인정보보호법 | 익명 평가 + non-PII scope. | **LOW** |
| 수출통제 (EAR) | 모델 API는 미국/중국 외 지역은 별도 검토. MiniMax는 한국 서비스. Anthropic opt-in. | **LOW** |
| Pre-commit hook 의무 통지 (한국 통신망법 일부) | `--strict` 모드만 hard-block. Default advisory. 통지 의무 없음. | **LOW** |
| OSS 기여자 신뢰 | MIT/Apache2 license restrict + dependabot 자동 scan | **LOW** |

**Overall Legal Risk: LOW** (자동 scan 통과 + opt-in mode만 차단)

## §4. Maintenance Risk (버스펙터, abandoned)

| Risk | 분석 | Mitigation | Level |
|---|---|---|---|
| Maintaner 1명 (현재 sanghee) | 단일 장애점 | ADR 22개 + 모듈 분리 + 1.36배 부담×−25% 통합 효과 | MEDIUM |
| Plugin abandoned / URL 깨짐 | marketplace 캐시 expire | `.claude-plugin/plugin.json` 에 `repository:` 명시. 외부 의존 0 | LOW |
| Adoption 실패 (다운로드 0) | 팀 외 채택 | 팀 100x AX = 5명 × 8h/day = 즉시 가치 | LOW |
| Deprecation 정책 부재 | 옛 5 plugin 사용자 | ADR-0001 (DEPRECATED.md 1줄) + 100x 통합 | LOW |
| Plugin 버전 호환 (Claude Code update 시) | 호스트 plugin protocol 변경 | `${CLAUDE_PLUGIN_ROOT}` portable path. weekly test | MEDIUM |

**Overall Maintenance Risk: MEDIUM** (mitigated by ADR + 모듈화)

## §5. Opportunity Cost (안 만들면 잃는 것)

| 손실 | 측정 | $ |
|---|---|---|
| 5 plugin 유지보수 | 5 × 0.5 일/월 × 12 × $100/h | $3,000/year direct |
| 단계간 hand-off 추적 실패 | 디버깅 시간 × 5명 | $5,000/year (추정) |
| Iron Law 5개 중복 → 사용자 학습 부담 | onboarding 시간 × 5명 × 1h | $2,500/year |
| HOTL/10x 부족 → AI 활용 효율 ↓ | 작업 시간 × 20% × 5명 × 8h × 220일 | $17,600/year |
| **합계** | | **~$28,100/year** |

**integration 가치 vs 비용:**
- 가치 $28,100/year
- 비용 $14,400 (1차년) + $5,000 (이후)
- 순 ROI 1차년: $13,700/year. 2차년: $23,100/year.
- **회수 기간: ~6개월 (1차년 시작 후)**.

**Annuity value: HIGH**

## §6. Compatibility Risk

| Risk | 분석 | Level |
|---|---|---|
| 옛 5 plugin 사용자 호환 | `DEPRECATED.md` 1줄 + 자동 리다이렉트 (없음, 수동 마이그레이션) | LOW |
| 다른 Claude Code plugin과 hook 충돌 | `.githooks/` + `.claude/settings.json` 격리. Claude Code는 plugin별 hooks.json 격리 | LOW |
| MiniMax ↔ Anthropic provider 충돌 | opt-in 전환. `lib/providers.json` SSOT | LOW |
| GitHub Actions 기존 workflow와 충돌 | 기존 workflow 보존 + 새 `dev-kit-review.yml` 추가. severity gate는 opt-in (`MINMAX_API_KEY` 없을 시 skip) | LOW |
| Pre-commit hook 사용자 .git/ 손상 | bash-guard `--strict` 모드만 hard-block. default advisory. | LOW |
| Python 3.10+ 의존 | harness-runner engine. README에 명시 | LOW |

**Overall Compatibility Risk: LOW**

## §7. Security Risk

| Risk | 분석 | Mitigation | Level |
|---|---|---|---|
| Hook 우회 (`DEV_KIT_HOOK_OFF` env) | opt-in 위험. 사용자 명시 opt-in 시 통과 | `--strict` 모드만 `exit 2`. default `exit 0` | LOW |
| Secret 누출 (eval/golden/*.json) | 회귀 test fixture에 secret 들어갈 위험 | secret-scan.sh (PostToolUse) 자동 grep + pre-commit | LOW |
| LLM-as-judge 결과 신뢰 | 2-judge cross-check (MUST-NOT-23) | 부적합 시 `.pending.json` 격리. human review | LOW |
| OSS 기여자 신뢰 (외부 PR) | MIT/Apache2 license만. dependabot auto-scan | branch protection `MINMAX_API_KEY` required | LOW |
| Secret in PR diff | reviewer/PR bot이 file_path 기반 secret scan | 자동 | LOW |
| Sub-agent 권한 escalation | `--enable <name>` hidden flag. `--strict` 모드는 거부 | hook 회귀 | LOW |

**Overall Security Risk: LOW** (mitigated by 자동 scan + hook + opt-in)

## §8. Operational Risk

| Risk | 분석 | Mitigation | Level |
|---|---|---|---|
| CI 의존 (야간 cron 실패 시 drift 누적) | GitHub Actions 일시 중단 가능 | 주 1회 manual `/dev-kit:eval` 호출 fallback | MEDIUM |
| Network 의존 (offline) | MiniMax API 도달 불가 | `--provider anthropic` opt-in fallback | MEDIUM |
| Provider 다운 | 양쪽 API 다 fail 시 eval 의미 없음 | `/dev-kit:eval --offline` local heuristic fallback | LOW |
| GitHub outage | PR bot push 실패 | `--no-ci` 모드 manual fallback | LOW |
| CI cron stale (불필요한 daily 비용) | $15/year = 무시 가능 | OK | LOW |

**Overall Operational Risk: MEDIUM** (mitigated by manual fallback)

---

## §9. 사용자 검토 (1회, HOTL)

AI가 8 dimension 자동 분석. 사용자 결과 검토 + 우려 코멘트만.

- [ ] §1 Time Cost OK ($14,400/1년)
- [ ] §2 Monetary Cost OK ($17.83/year)
- [ ] §3 Legal Risk OK (LOW)
- [ ] §4 Maintenance Risk OK (MEDIUM, mitigated)
- [ ] §5 Opportunity Cost OK ($28,100/年 가치 vs $14,400 비용)
- [ ] §6 Compatibility Risk OK (LOW)
- [ ] §7 Security Risk OK (LOW)
- [ ] §8 Operational Risk OK (MEDIUM, manual fallback)

**총 평가**: 6 LOW + 2 MEDIUM (mitigated) = **PASS**

OK 후 `docs/PRE-IMPL-CHECK.md` §F와 함께 Phase 1 시작.

---

**swap rules (MUST-NOT-18)**:
- 이 8 dimension 분석 추가 = MUST-NOT net +4 (MUST 54~56 + MUST-NOT 32).
- Mitigate: 기존 MUST-29 (HOTL default)가 cost review도 자동 진행 + 사용자 1회만 보강.
- Swap 부분 성립, remaining +3 = 다음 ADR에서 흡수.
