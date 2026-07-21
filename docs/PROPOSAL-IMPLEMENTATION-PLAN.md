# Implementation Plan — Multi-Harness System (Issue #280)

> Concrete file-by-file plan mapped to current code state. Generated
> 2026-07-21 alongside [the design proposal](proposals/00-index.html).
> Each Phase corresponds to **one PR**, independently shippable + revertable.

---

## §1 Current state analysis (what's already here)

| Component | File:line | Status |
|---|---|---|
| Plan loop spec (ambiguity, value, evidence, dedup_metric, safety_valve) | `skills/plan/SKILL.md:16-19,96-165` | **live** |
| Plan loop executor | (none — agent-driven) | **absent** |
| Phase JSON schema with `ambiguity_score` + `value_score` + `evidence_count` | `skills/plan/SKILL.md:209-230` | **live** |
| Step state machine (VALID_STATUSES) | `lib/execute.py:42-53` | **live** |
| `register_step()` / `update_step_status()` | `lib/execute.py:71-202` | **live** |
| State codec (state.json ↔ hand-off) | `lib/state_codec.py` (119 lines) | **live** |
| LLM judge (`call_judge`, `format_prompt`, `parse_scores_json`) | `lib/llm_judge.py` (242 lines) | **live** |
| Per-dim judge axes (review / security / **plan**) | `lib/llm_judge.py:30-49` | **live** |
| Plan judge prompt (4-axis: spec_clarity / step_atomicity / ac_executability / dependency_ordering) | `eval/prompts/judge-plan.md` | **live** |
| Eval transcripts (real `ok` / `held` examples) | `eval/transcripts/plan/plan-{01,02,03}-*.json` | **live** |
| Eval runner (`judge_case` + `RUBRIC` reading) | `lib/eval_runner.py:191-300` | **live** |
| SKILL_COUNT invariant | `tests/test_smoke.py:23,35-37` | **35** |
| Skill governance (alpha: state\|enforcement\|analysis) | `tests/test_skill_governance.py` | **live** |
| Hook wiring (PreToolUse: worktree-guard, bash-guard, git-guard) | `hooks/hooks.json` | **live** |
| `lib/render_proposal_html.py` + `bin/dev-kit-proposal.py` | this PR's earlier work | **live (this PR)** |

---

## §1.5 Twin design principle — agentic-friendly + user-friendly

**두 표면이 동일하게 잘 동작해야 한다.**

| Audience | Surface | Optimization |
|---|---|---|
| **LLM 에이전트** (M/T/L) | CLI, YAML, JSON, MCP URI, exit codes, structured logs | 파싱 가능, 결정적, 자기서술적, idempotent |
| **사람** (사용자 / 리뷰어 / 운영자) | README, HTML, `/dev-kit:` 슬래시, 상태 메시지 | 명확, 친절, 시각적, 기본값 합리적 |

### Agentic-friendly 요구사항 (모든 Phase에 적용)

1. **구조화된 출력** — 모든 CLI는 `--json` 플래그로 기계 판독 가능 출력 지원
2. **안정된 스키마** — breaking change는 `/v<n>` URI 또는 deprecation 경고
3. **예측 가능한 인터페이스** — 순수 함수, 명시적 계약 (Protocol/Type hints)
4. **멱등성** — 같은 입력에 같은 출력, 재실행 안전
5. **명시적 에러** — exit code ≠ 0 + stderr에 "원인 + 다음 행동" (`bin/atomic.py:atomic_write_text` 패턴)
6. **자기서술** — `bin/dev-kit-proposal.py --list`, `python3 lib/lcs_server.py --describe` 같은 introspection
7. **명령 일관성** — `dev-kit-<verb>.py` 패턴 통일; 플래그 명명 컨벤션
8. **결정적 정렬** — 모든 도구는 디버깅을 위해 deterministic 정렬 (예: PR 목록은 timestamp 순)

### User-friendly 요구사항 (모든 Phase에 적용)

1. **명확한 슬래시** — `/dev-kit:<verb>` 0-arg 기본 + 옵션은 플래그
2. **시각적 리포트** — `.dev-kit/report.html`, `docs/proposals/*.html` 자동 렌더
3. **도움말 + 예시** — 모든 `--help` 출력에 사용 예시 포함
4. **에러는 친절하게** — `error: gh not installed. Install: brew install gh` 형태
5. **기본값 합리적** — `--max-phase=2`, `--n-judges=3`, `--safety-valve=8` 모두 기본값
6. **점진적 공개** — 기본은 단순, 옵션으로 고급 기능 노출
7. **README 우선** — 모든 신규 lib / bin 모듈은 `docs/<module>.md` 1-pager 동반
8. **마이그레이션 가이드** — 변경 시 `docs/MIGRATION-<version>.md` 동반

### Per-phase 두 surface 분리

| Phase | Agentic surface | User surface |
|---|---|---|
| 0 (portability) | `RuntimeAdapter` Protocol + `is_current()` introspection | `/dev-kit:runtime` 슬래시 (어떤 런타임인지 출력) |
| 1 (LCS) | MCP URI + JSON payload + `--describe` | `python3 bin/dev-kit-lcs.py --list-proposals` + HTML 캐시 뷰 |
| 2 (hooks) | exit code 0/1 + JSON stderr | 훅 통과/실패 메시지 |
| 3 (eval ext) | `--json` + 축 점수 | `/dev-kit:eval --harness-quality --os-quality` 시각 리포트 |
| 4 (plan-value) | `lcs://valuations/<id>` JSON | `/dev-kit:valuate <plan>` 결과 (proceed/revise/hold/kill) |
| 5 (research) | `verify_claim()` 순수 + `ResearchReport` dataclass | `/dev-kit:research <claim>` 인용 포함 리포트 |
| 6 (interview) | `interview_engine.py` 순수 + JSON `{value_score, ambiguity_score, evidence_count, status}` | `/dev-kit:interview <plan-file>` 대화형 |
| 7 (harness-audit) | `tools/harness_audit.py --json` | `/dev-kit:harness-audit` HTML 대시보드 |

### 스킬 본문 규칙 (`rules/skill-authoring.md` 정렬)

모든 신규 스킬은 다음을 만족:

- `description:` ≤ 1줄
- `when_to_use:` 2–5개 항목
- 첫 섹션: **what it does** (1 단락)
- 마지막 섹션: **next step** (어떤 다른 스킬/명령 호출)
- 본문 **전부 영어** (코드 주석 포함)
- 코드 블록에 언어 태그 (` ```bash `, ` ```ts `)
- `alpha:` 필드 필수 (`state` | `enforcement` | `analysis`)

### README 규약

- `docs/<module>.md` 1-pager 형식 (각 신규 lib / bin 모듈)
- 포함: 목적, 사용법 (3개 시나리오), API 요약, 결정적/비결정적 분류, 예제 출력
- `docs/PROPOSAL-IMPLEMENTATION-PLAN.md` (본 문서) — 모든 신규 모듈의 상위 참조
- `docs/proposals/*.html` — 디자인 의도 기록 (이미 구축됨)

### Acceptance criteria 보강

각 Phase의 acceptance criteria에 다음 추가:

- [ ] `--json` 출력 스키마 검증 테스트
- [ ] `--help` 출력에 예시 포함
- [ ] 결정적 부분과 비결정적 부분 명시 (테스트에 `pytest -p no:randomly` 적용 가능 여부)
- [ ] 사용자 가시 에러 메시지 (LCS 다운, gh 미설치 등)에 다음 행동 포함

---
| L7 alpha accounting (must spend on enforcement / external truth / state, not reasoning) | `CLAUDE.md §1` Iron Laws L6/L7 | **live** |
| Multi-runtime portability (.claude + .codex hooks.json) | `.claude/settings.json` + `.codex/hooks.json` | **partial** (hooks only; libs assume single-runtime) |

### Real JSON shape (ground truth)

`eval/transcripts/plan/plan-01-clear-spec.json`:
```json
"validate": {"value_score": 4.2, "ambiguity_score": 2, "evidence_count": 3, "status": "ok"}
```

`eval/transcripts/plan/plan-02-ambiguous-spec.json`:
```json
"validate": {"value_score": 0.8, "ambiguity_score": 9, "evidence_count": 0, "status": "held"}
```

`eval/transcripts/plan/plan-03-coupled-spec.json`:
```json
"validate": {"value_score": 3.5, "ambiguity_score": 3, "evidence_count": 3, "status": "ok"}
```

### 5-field safety contract (frontmatter, MUST-15)

```yaml
safety_valve: 8
convergence: composite (ambiguity_score <= 3 AND value_score >= 3.0)
narrowed_delta: bool
dedup_metric: identical-ambiguity-cycle=2
user_interrupt
```

---

## §2 Per-phase concrete plan

### Phase 0 — Runtime Portability (선결 조건)

**Goal**: All Phase 1+ ship runtime-neutral (Claude Code + Codex 동등).

**Files**:

| File | Action | Approx LOC |
|---|---|---|
| `lib/runtime_adapters/__init__.py` | NEW | ~20 |
| `lib/runtime_adapters/base.py` | NEW (Protocol definitions) | ~120 |
| `lib/runtime_adapters/tokens.py` | NEW (token log abstract) | ~80 |
| `lib/runtime_adapters/sessions.py` | NEW (session event abstract) | ~80 |
| `lib/runtime_adapters/hooks.py` | NEW (event name normalizer) | ~60 |
| `lib/runtime_adapters/user_input.py` | NEW | ~80 |
| `lib/runtime_adapters/workspace.py` | NEW | ~40 |
| `lib/runtime_adapters/skill_install.py` | NEW | ~60 |
| `lib/runtime_adapters/claude_code.py` | NEW | ~150 |
| `lib/runtime_adapters/codex.py` | NEW | ~150 |
| `tests/test_portability.py` | NEW | ~120 |
| `.github/workflows/test-portability.yml` | NEW (matrix: claude-code, codex) | ~50 |

**Acceptance criteria**:
1. `pytest tests/test_portability.py -v` passes
2. CI matrix green for both `claude-code` and `codex` lanes
3. Mock adapter validates RuntimeAdapter interface
4. `docs/RUNTIME-PORTABILITY.md` exists
5. Decision 8 satisfied: all adapters export same `RuntimeAdapter` interface

**Tests**:
- `test_adapter_interface_compliance` — every adapter implements Protocol
- `test_is_current_per_runtime` — adapter detects its runtime
- `test_token_log_normalization` — same input → same `TokenLog`
- `test_session_event_normalization` — same input → same `SessionEvent`
- `test_hook_event_name_normalization` — `PreToolUse` → runtime-native

**Estimated PR**: 1 PR, ~1,000 LOC, +0 SKILL_COUNT

---

### Phase 1 — LCS (Live Context Server)

**Goal**: First MCP server. Replaces 7 shell-outs with typed queries.

**Files**:

| File | Action | Approx LOC |
|---|---|---|
| `lib/lcs_server.py` | NEW (pure function: parse URI → payload) | ~250 |
| `bin/dev-kit-lcs.py` | NEW (CLI driver, lifecycle) | ~120 |
| `lib/lcs_resources/__init__.py` | NEW | ~10 |
| `lib/lcs_resources/worktrees.py` | NEW | ~80 |
| `lib/lcs_resources/pr.py` | NEW (wraps `gh pr view`) | ~80 |
| `lib/lcs_resources/spend.py` | NEW (wraps `tools/token_efficiency_analyzer.py`) | ~80 |
| `lib/lcs_resources/hooks_coverage.py` | NEW | ~60 |
| `lib/lcs_resources/branches.py` | NEW | ~70 |
| `lib/lcs_resources/sessions.py` | NEW (uses `runtime_adapters/sessions.py`) | ~80 |
| `lib/lcs_resources/interview.py` | NEW (read-only v1; v2 uses tools channel) | ~60 |
| `lib/lcs_resources/research_cache.py` | NEW (Phase 5 cache; stub in v1) | ~50 |
| `skills/lcs/SKILL.md` | NEW (alpha: state) | ~80 |
| `tests/test_lcs_server.py` | NEW | ~150 |
| `tests/test_lcs_resources.py` | NEW | ~200 |
| `tests/test_smoke.py` | MOD (SKILL_COUNT 35 → 36) | ~1 |

**Acceptance criteria**:
1. `pytest tests/test_lcs_server.py tests/test_lcs_resources.py -v` passes (≥20 tests)
2. LCS starts in <500ms, reads served in <10ms p99 (latency test)
3. URI schema stable: 8 resources, payload shapes versioned (additive OK, breaking → `/v<n>` URI)
4. `gh pr view` data matches `lcs://pr/<n>` payload (integration test)
5. Data source failure → `status: "partial"` (not crash)

**Tests** (focused on resource correctness):
- `test_worktrees_uri_routing` — `lcs://worktrees` → list
- `test_pr_uri_with_gh_failure` — `lcs://pr/999999` → partial
- `test_spend_uri_window_filtering` — `lcs://spend/today` filters correctly
- `test_snapshot_consistency` — concurrent reads return same list
- `test_uri_schema_versioning` — additive fields OK, breaking changes rejected

**Estimated PR**: 1 PR, ~1,400 LOC, +1 SKILL_COUNT (35→36)

---

### Phase 2 — Hooks Read LCS

**Goal**: Hooks switch from shell-out to LCS read, with shell-out fallback.

**Files**:

| File | Action | Approx LOC |
|---|---|---|
| `hooks/worktree-guard.sh` | MOD (read `lcs://worktrees` instead of `git worktree list`) | +20 / -10 |
| `hooks/git-guard.sh` | MOD (read `lcs://branches/<name>/slot` instead of `bin/version-slot compute`) | +15 / -10 |
| `lib/runtime_adapters/hooks.py` | NEW in Phase 0, USED here | (already counted) |
| `tests/test_lcs_hook_integration.py` | NEW | ~120 |

**Acceptance criteria**:
1. `worktree-guard.sh` passes tests with LCS running AND with LCS down (fallback)
2. `git-guard.sh` slot check matches `bin/version-slot compute` output
3. Both hooks wire in both `.claude/settings.json` and `.codex/hooks.json`
4. Latency: LCS read path <50ms shell-out overhead

**Tests**:
- `test_worktree_guard_with_lcs` — happy path
- `test_worktree_guard_without_lcs` — fallback to git shell-out
- `test_git_guard_slot_check_matches_compute` — parity test
- `test_both_runtimes_wire_both_hooks` — `.claude` + `.codex`

**Estimated PR**: 1 PR, ~150 LOC net, +0 SKILL_COUNT

---

### Phase 3 — Evaluation Extension (RUBRIC_REGISTRY + harness/OS dims)

**Goal**: Existing `/dev-kit:eval` learns harness-quality + OS-quality dimensions.

**Files**:

| File | Action | Approx LOC |
|---|---|---|
| `lib/eval_runner.py` | MOD (add `RUBRIC_REGISTRY` class) | +80 / -10 |
| `lib/analysis-core/cross_validate.py` | NEW (adversarial cross-check helper) | ~100 |
| `skills/evaluate/SKILL.md` | NEW (alpha: enforcement) | ~100 |
| `eval/rubrics/harness-quality.yaml` | NEW | ~30 |
| `eval/rubrics/os-quality.yaml` | NEW | ~30 |
| `eval/prompts/judge-harness-quality.md` | NEW | ~50 |
| `eval/prompts/judge-os-quality.md` | NEW | ~50 |
| `lib/llm_judge.py` | MOD (extend `DIM_AXES` with `harness` + `os`) | +10 |
| `tests/test_evaluate_extended.py` | NEW | ~150 |
| `tests/test_evaluation_rubrics.py` | NEW | ~80 |
| `tests/test_smoke.py` | MOD (SKILL_COUNT 36 → 37) | ~1 |

**Acceptance criteria**:
1. `pytest tests/test_evaluate_extended.py -v` passes (≥10 tests)
2. `/dev-kit:eval --harness-quality --os-quality` opt-in works (backward-compat: no flags = existing behavior)
3. New judge prompts return valid JSON matching `DIM_AXES['harness']` / `['os']`
4. Adversarial cross-check: 3-judge variance > 0.5 → escalate

**Tests**:
- `test_rubric_registry_register_lookup` — round-trip
- `test_harness_quality_judge_returns_valid_axes` — JSON parse
- `test_os_quality_judge_returns_valid_axes`
- `test_variance_gate_escalates` — 3 judges diverge → additional judge called
- `test_backward_compat_no_new_dims` — existing eval calls unchanged

**Estimated PR**: 1 PR, ~700 LOC, +1 SKILL_COUNT (36→37)

---

### Phase 4 — Plan-Value Evaluation (no-go gate)

**Goal**: New `/dev-kit:valuate` skill; `/dev-kit:build` blocks on non-PROCEED.

**Files**:

| File | Action | Approx LOC |
|---|---|---|
| `lib/valuation_engine.py` | NEW (pure: plan + rubric → decision) | ~250 |
| `lib/valuation_rubrics/default.yaml` | NEW | ~50 |
| `eval/prompts/judge-plan-value.md` | NEW | ~80 |
| `lib/llm_judge.py` | MOD (extend `DIM_AXES` with `plan_value`) | +10 |
| `skills/valuate/SKILL.md` | NEW (alpha: enforcement) | ~120 |
| `skills/build/SKILL.md` | MOD (read `lcs://valuations/<plan-id>`; refuse on non-PROCEED) | +40 / -5 |
| `docs/STAGES.md` | MOD (add "valuate" stage row) | +10 |
| `tests/test_valuation_engine.py` | NEW | ~180 |
| `tests/test_smoke.py` | MOD (SKILL_COUNT 37 → 38) | ~1 |

**Acceptance criteria**:
1. `pytest tests/test_valuation_engine.py -v` passes (≥15 tests)
2. Threshold logic: avg≥4 → proceed, <3 → kill, risk<2 → kill regardless
3. `--skip-valuation` flag in `/dev-kit:build` for backward compat
4. Decision logged to `lcs://valuations/<plan-id>`

**Tests**:
- `test_proceed_path` — avg≥4 + no risk<2 → PROCEED
- `test_kill_path_risk_floor` — risk<2 → KILL regardless of avg
- `test_revise_path` — 1+ dim <3 → REVISE
- `test_hold_path` — avg 3-4 → HOLD
- `test_build_respects_decision` — build refuses non-PROCEED
- `test_skip_valuation_backward_compat`

**Estimated PR**: 1 PR, ~750 LOC, +1 SKILL_COUNT (37→38)

---

### Phase 5 — Research Enhancement (Phase 0–3 escalation + verification gate)

**Goal**: `/dev-kit:research <claim>` does rubric-first verification with escalation.

**Files**:

| File | Action | Approx LOC |
|---|---|---|
| `lib/research_engine.py` | NEW (Phase 0–3 escalation + verification gate) | ~400 |
| `lib/lcs_resources/research_cache.py` | USED (built in Phase 1; now consumed) | (already counted) |
| `eval/prompts/judge-research-source.md` | NEW | ~60 |
| `eval/prompts/judge-research-claim.md` | NEW | ~60 |
| `lib/llm_judge.py` | MOD (extend `DIM_AXES` with `research_source` + `research_claim`) | +10 |
| `skills/research/SKILL.md` | NEW (alpha: enforcement) | ~150 |
| `tests/test_research_engine.py` | NEW | ~200 |
| `tests/test_smoke.py` | MOD (SKILL_COUNT 38 → 39) | ~1 |

**Acceptance criteria**:
1. `pytest tests/test_research_engine.py -v` passes (≥20 tests)
2. Phase 0 (cache lookup) returns in <50ms when hit
3. Phase 1 (HTTP + OGP/JSON-LD) parses title + summary
4. Phase 2 (`requests-html`) handles JS-rendered pages
5. Phase 3 (Playwright) **optional** in v1 (gated by `max_phase=4`)
6. Verification gate: any uncited claim → reject
7. N-source agreement: 3/3 → confidence up; 1/3 → confidence down + warn

**Tests**:
- `test_phase_0_cache_hit` — skip remaining phases
- `test_phase_1_parses_ogp` — known fixture URL → title/summary
- `test_phase_2_handles_js`
- `test_phase_3_stops_at_auth` — paywall → abort
- `test_citation_required_rejects` — uncited claim → fail
- `test_n_source_agreement_scoring` — 3 same → high; 1 different → low

**Estimated PR**: 1 PR, ~880 LOC, +1 SKILL_COUNT (38→39)

---

### Phase 6 — Interview (5-field safety contract, plan-pattern)

**Goal**: `/dev-kit:interview <plan-file>` resolves ambiguity before build.

**Files**:

| File | Action | Approx LOC |
|---|---|---|
| `lib/interview_engine.py` | NEW (5-field safety contract: safety_valve, convergence, narrowed_delta, dedup_metric, user_interrupt) | ~350 |
| `lib/interview_rubrics/default.yaml` | NEW | ~50 |
| `eval/prompts/judge-interview-ambiguity.md` | NEW | ~80 |
| `lib/llm_judge.py` | MOD (extend `DIM_AXES` with `interview_ambiguity`) | +10 |
| `skills/interview/SKILL.md` | NEW (alpha: state) — frontmatter declares 5-field contract | ~150 |
| `skills/plan/SKILL.md` | MOD (consume `lcs://interview/<session>` before plan emission) | +30 / -5 |
| `lib/runtime_adapters/user_input.py` | USED (built in Phase 0) | (already counted) |
| `tests/test_interview_engine.py` | NEW (narrowed_delta + dedup_metric regression) | ~200 |
| `tests/test_smoke.py` | MOD (SKILL_COUNT 39 → 40) | ~1 |

**Acceptance criteria**:
1. `pytest tests/test_interview_engine.py -v` passes (≥15 tests)
2. JSON output matches plan shape: `{value_score, ambiguity_score, evidence_count, status: ok|held}`
3. Convergence: `ambiguity_score <= 3` AND `evidence_count >= 3` AND `value_score >= 3.0`
4. safety_valve=8: cap → `status: "held"`, surface remaining gap
5. dedup_metric: 2 identical scores in a row → break out
6. `--skip-interview` flag in `/dev-kit:plan` for backward compat
7. Interview output persists to `lcs://interview/<session>`

**Tests**:
- `test_convergence_path` — scores drop to ≤3 → ok
- `test_held_path` — safety_valve exhausted → held
- `test_narrowed_delta_enforced` — score increase → raise
- `test_dedup_metric_breaks_loop` — 2 same scores → break
- `test_user_interrupt_short_circuits` — explicit signoff → done
- `test_json_shape_matches_plan_transcript` — parity with `plan-01-clear-spec.json`

**Estimated PR**: 1 PR, ~870 LOC, +1 SKILL_COUNT (39→40)

---

### Phase 7 — Harness Audit (cross-harness dashboard)

**Goal**: `/dev-kit:harness-audit` produces a cross-harness quality report.

**Files**:

| File | Action | Approx LOC |
|---|---|---|
| `tools/harness_audit.py` | NEW (CLI: collects metrics from all 6 harnesses) | ~200 |
| `skills/harness-audit/SKILL.md` | NEW (alpha: analysis — read-only) | ~100 |
| `lib/render_report_html.py` | USED (reuses existing renderer) | (already exists) |
| `tests/test_harness_audit.py` | NEW | ~120 |
| `tests/test_smoke.py` | MOD (SKILL_COUNT 40 → 41) | ~1 |

**Acceptance criteria**:
1. `pytest tests/test_harness_audit.py -v` passes (≥10 tests)
2. `python3 tools/harness_audit.py` produces HTML report
3. Report covers all 6 harnesses: per-harness score, alpha classification, L7 alignment
4. **Strictly read-only** — no state writes (enforced by lint)
5. Audit reveals: missing rubrics, missing cache, unused adapters

**Tests**:
- `test_audit_covers_all_six_harnesses`
- `test_audit_emits_html_report` — valid HTML
- `test_audit_is_read_only` — no state.json mutation
- `test_audit_detects_missing_alpha_field`

**Estimated PR**: 1 PR, ~420 LOC, +1 SKILL_COUNT (40→41)

---

## §3 Cross-phase dependencies

```
Phase 0 (portability)
  └─► Phase 1 (LCS)         — uses runtime_adapters/sessions.py, tokens.py
       └─► Phase 2 (hooks)   — LCS-driven hooks
       └─► Phase 5 (research) — uses lcs://research/cache
       └─► Phase 6 (interview) — uses lcs://interview/<session>
  
  └─► Phase 3 (eval ext)    — independent; uses llm_judge directly
  └─► Phase 4 (plan-value)   — independent; pure function
  └─► Phase 7 (harness-audit) — requires all 6 harnesses shipped
```

**Critical**: Phase 0 must land first; all other phases depend on
`lib/runtime_adapters/` existing.

---

## §4 Cumulative metrics (after Phase 7)

| Metric | Before | After |
|---|---|---|
| SKILL_COUNT | 35 | 41 (+6) |
| New skills | — | lcs, interview, valuate, evaluate, research, harness-audit |
| New lib modules | — | lcs_server, lcs_resources/*, runtime_adapters/*, interview_engine, valuation_engine, research_engine |
| LOC added | — | ~5,000 (8 PRs, all back-compat) |
| Rewrites | — | 0 |
| Backward-compat flags | — | `--skip-interview`, `--skip-valuation` |

---

## §5 Backward compatibility matrix

| Existing surface | New behavior | Backward-compat |
|---|---|---|
| `/dev-kit:plan` | Reads `lcs://interview/<session>` first | `--skip-interview` |
| `/dev-kit:build` | Reads `lcs://valuations/<plan-id>` | `--skip-valuation` |
| `/dev-kit:eval` | Same axes by default; new opt-in | `--harness-quality --os-quality` |
| `/dev-kit:review` | Existing dims + new dims as one judge | n/a (automatic) |
| `hooks/worktree-guard.sh` | LCS-first, shell-out fallback | automatic |
| `hooks/git-guard.sh` | LCS-first, shell-out fallback | automatic |
| `tools/parallel_dispatch.py` | Same API; new `with_rubric` option | backward-compat default |

---

## §6 Test strategy

- **Per-phase PR must include**: ≥10 new tests; existing test suite passes
- **SKILL_COUNT invariant**: bump `tests/test_smoke.py:23` per phase
- **Skill governance**: `tests/test_skill_governance.py` enforces `alpha:`
  field on every new skill
- **Portability**: `tests/test_portability.py` (Phase 0) + CI matrix
- **Plan-alignment parity**: `tests/test_interview_engine.py` (Phase 6)
  JSON shape must match `eval/transcripts/plan/plan-01-clear-spec.json`

---

## §7 Risk register (per-phase)

| Phase | Risk | Mitigation |
|---|---|---|
| 0 | CI matrix cost (two runtimes) | mock adapters; real binary only for adapter self-test |
| 1 | LCS resource URI drift | additive = no bump; breaking = `/v<n>` URI |
| 2 | Hook regression on LCS outage | shell-out fallback retained |
| 3 | Judge prompt drift | freeze judge axes in `lib/llm_judge.py:DIM_AXES` |
| 4 | False-negative kills | `--skip-valuation` flag + audit (Phase 7) |
| 5 | Playwright cost | `max_phase=4` parameter; v1 maxes at Phase 2 |
| 6 | Interview re-score inconsistency | dedup_metric + narrowed_delta + adversarial variance gate |
| 7 | Audit becomes self-eval | alpha: analysis (not enforcement) + read-only lint |

---

## §8 Open questions (deferred to issue comments)

1. Phase 0 어댑터 동시 출시 vs 순차 (Q3 in proposal)
2. Phase 5 max_phase 기본값 (Q1)
3. LLM judge 인프라 재사용 범위 (Q9)
4. 프로세스: 단일 PR vs N개 (Q10)

---

## §9 Related

- [Design proposal](proposals/00-index.html) — 13-file topic structure
- [`docs/proposals/03-ambiguity-resolver.html`](proposals/03-ambiguity-resolver.html) — Interview design with plan-alignment
- [`docs/proposals/10-decision-record.html`](proposals/10-decision-record.html) — 8 locked decisions
- [`docs/proposals/11-migration-phases.html`](proposals/11-migration-phases.html) — Phase 0–7 detail
- `skills/plan/SKILL.md` — Plan loop precedent (5-field safety contract)
- `lib/llm_judge.py` — LLM judge infrastructure
- `lib/execute.py` — Step state machine
- `lib/state_codec.py` — State codec
- `eval/transcripts/plan/` — Real JSON shape precedents
- Issue #280 — Design discussion venue (closes when Phase 0 lands)