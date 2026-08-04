# 스킬 문서 인덱스

**언어:** [English](README.md) · 한국어

`dev-kit` 플러그인이 배포하는 모든 스킬에 대한 상세하고 사람이 읽기
쉬운 문서 레이어다 — `docs/skills/` 아래 스킬당 한 페이지이며, 각각
간결한 `skills/<name>/SKILL.md` 소스를 확장해 생성된다. 기계용 요약
표(`SKILL.md` 프런트매터가 직접 구동하는 것)는
[`skills/README.md`](../../skills/README.md)를, 저장소 루트에서의
한 줄 포인터는 메인
[`README.md`](../../README.ko.md#스킬-대상-구분)를 참고한다.

모든 스킬은 탐색에 중요한 두 개의 프런트매터 필드를 선언한다:

- **`user-invocable`** — `true`면 `/dev-kit:<name>`을 직접 입력한다;
  `false`면 부모 스킬의 흐름 안에서 모델이 자동으로 호출하는 내부
  서브스킬이며 슬래시 자동완성에 절대 나타나지 않는다.
- **`alpha`** — `state`(하네스 상태 머신을 구동), `enforcement`(사용자가
  말로 피해갈 수 없는 결정론적 가드), `analysis`(코퍼스에 대한 순수
  추론) 중 하나. 전체 근거는 `CLAUDE.md` §1(L6/L7)과
  `rules/skill-authoring.md`를 참고한다.

현재 개수는 변동적이다(플러그인이 진화하면서 스킬이 추가되고
제거된다). 다음으로 확인한다:

```bash
find skills -mindepth 2 -maxdepth 2 -name SKILL.md | wc -l
grep -lE '^user-invocable: false' skills/*/SKILL.md | wc -l   # 모델 호출 서브스킬
```

---

## 사용자 호출 스킬 (`/dev-kit:<name>` 입력)

### 설정 / 부트스트랩

| 스킬 | Alpha | 요약 |
|---|---|---|
| [`bootstrap`](bootstrap.md) | `state` | 최초 진입 — 새 저장소에 최소 `CLAUDE.md` + `AGENTS.md` + `active-hooks.json`을 생성. |
| [`bootstrap-full`](bootstrap-full.md) | `state` | `bootstrap` + `ci-setup` 원샷 — 신규 프로젝트 기본값. |
| [`ci-setup`](ci-setup.md) | `enforcement` | dev-kit의 재사용 가능한 CI 워크플로 템플릿을 대상 프로젝트에 설치. |
| [`config`](config.md) | `state` | 스킬 / MCP / 훅 / 방법론 선택기. |

### Plan → Build

| 스킬 | Alpha | 요약 |
|---|---|---|
| [`plan`](plan.md) | `state` | 아이디어 → 5-게이트 루프를 거쳐 `PRD.md` + `phases/<name>/`. |
| [`build`](build.md) | `state` | TDD + 자동 수정 루프가 통합된 스텝별 서브에이전트 위임. |

### Review → Ship

| 스킬 | Alpha | 요약 |
|---|---|---|
| [`review`](review.md) | `analysis` | 오탐 필터가 있는 병렬 정확성 + 보안 + 아키텍처 리뷰. |
| [`security`](security.md) | `enforcement` | 검증 패스가 있는 OWASP Top 10 2025 (A01–A10) 전체 팬아웃. |
| [`audit`](audit.md) | `state` | 0-인자 횡단 일괄 슬롭 + 시크릿 감사 (읽기 전용). |
| [`inspect`](inspect.md) | `analysis` | 8차원 읽기 전용 코드 건강 감사. |
| [`refactor`](refactor.md) | `analysis` | 3단계 정리 체인: `inspect → build-refactor → review`. |
| [`prune`](prune.md) | `analysis` | 4단계 삭제 스윕: sweep → dependents → report → verify. |
| [`babysit-pr`](babysit-pr.md) | `state` | PR 베이비시터 루프: CI 폴링, 수정, 커밋, 그린 Approve까지 반복. |
| [`ship`](ship.md) | `state` | 릴리스 태그 발행; 게이트 확인만. |
| [`bump`](bump.md) | `state` | 명시적 `plugin.json` 버전 범프 + 푸시. |

### 평가 / 비용 / 리포팅

| 스킬 | Alpha | 요약 |
|---|---|---|
| [`token-analyzer`](token-analyzer.md) | `analysis` | 세션 로그 트랜스크립트에서 렌더링되는 토큰 효율 대시보드. |
| [`cost-gate`](cost-gate.md) | `enforcement` | 실시간 읽기 전용 비용 원장 + PR 비용 플래그 트레일러. |
| [`status`](status.md) | `state` | HOTL 시각화: 루프 진행 + 사이클 + 핸드오프 체인 + 평가 점수. |
| [`ci-doctor`](ci-doctor.md) | `enforcement` | CI 준비 상태에 대한 읽기 전용 PASS/FAIL 감사. |
| [`docs-maintenance`](docs-maintenance.md) | `analysis` | 오래된 문서를 감사하고 변동성 있는 사실을 기록하지 않으면서 README를 새로고침. |
| [`prune-propose`](prune-propose.md) | `state` | 사용량 원격 측정 덤프 + 스킬별 삭제 제안, 사용자 승인. |
| [`evaluate`](evaluate.md) | `enforcement` | 같은 러너에 `harness-quality`와 `os-quality` 차원을 추가하는 평가 확장. |

### 단축 명령 / 유지보수

| 스킬 | Alpha | 요약 |
|---|---|---|
| [`log`](log.md) | `state` | 프로젝트별 세션 loghook 토글(`setup`/`on`/`off`/`status`). |
| [`codex-cache-update`](codex-cache-update.md) | `analysis` | Codex 마켓플레이스 체크아웃 + 버전 플러그인 캐시를 새로고침. |
| [`llm-refresh`](llm-refresh.md) | `analysis` | 각 벤더 가격 페이지에서 `docs/llm-info/<provider>.json`을 새로고침. |

### 설계

| 스킬 | Alpha | 요약 |
|---|---|---|
| [`proposal`](proposal.md) | `state` | `docs/proposals/<main>/<sub>.yaml`을 자체 완결 리뷰 HTML로 렌더링. |
| [`interview`](interview.md) | `enforcement` | plan 발행을 게이트하는 5필드 안전 계약 인터뷰. |
| [`research`](research.md) | `enforcement` | 0-인자 리서치 게이트: cache/direct/multi/human 에스컬레이션 + 인용 시행. |
| [`valuate`](valuate.md) | `enforcement` | 계획을 6개 축으로 채점하고 proceed/revise/hold/kill을 반환하는 plan-value 게이트. |

---

## 모델 호출 서브스킬 (내부 — 슬래시 자동완성에 없음)

이들은 `user-invocable: false`다. 부모 스킬 흐름 안에서 모델이
자동으로 호출한다; 직접 입력하는 일은 없다.

| 스킬 | Alpha | 부모 | 요약 |
|---|---|---|---|
| [`build-tdd`](build-tdd.md) | `enforcement` | `/dev-kit:build` | Red-Green-Refactor 사이클; `tdd-guard` 훅이 실패하는 테스트 없이는 프로덕션 코드를 막는다. |
| [`build-debug`](build-debug.md) | `enforcement` | `/dev-kit:build` | 4단계 체계적 디버깅; Phase 1(재현) 완료 전에는 수정하지 않는다. |
| [`build-verify`](build-verify.md) | `enforcement` | `/dev-kit:build` | 완료 전 검증; 인용된 종료 코드 + 테스트 수 없이는 "완료"라고 하지 않는다. |
| [`build-refactor`](build-refactor.md) | `enforcement` | `/dev-kit:refactor`, `/dev-kit:prune` | 4단계 정리(dead → dup → naming → coverage); 회귀 테스트 없이는 정리하지 않는다. |
| [`hook-doctor`](hook-doctor.md) | `enforcement` | 자동 (훅 실패가 보일 때) | 실패한 Claude Code / Codex 훅을 진단하고 안전한 캐시 + 등록 드리프트를 복구한다. |

---

## 알파벳순 (전체 스킬)

| 스킬 | 카테고리 | Alpha | 호출 방식 |
|---|---|---|---|
| [`audit`](audit.md) | `audit` | `state` | 사용자 |
| [`babysit-pr`](babysit-pr.md) | `ship` | `state` | 사용자 |
| [`bootstrap`](bootstrap.md) | `bootstrap` | `state` | 사용자 |
| [`bootstrap-full`](bootstrap-full.md) | `bootstrap` | `state` | 사용자 |
| [`build`](build.md) | `build` | `state` | 사용자 |
| [`build-debug`](build-debug.md) | `build` | `enforcement` | 모델 |
| [`build-refactor`](build-refactor.md) | `build` | `enforcement` | 모델 |
| [`build-tdd`](build-tdd.md) | `build` | `enforcement` | 모델 |
| [`build-verify`](build-verify.md) | `build` | `enforcement` | 모델 |
| [`bump`](bump.md) | `ship` | `state` | 사용자 |
| [`ci-doctor`](ci-doctor.md) | `audit` | `enforcement` | 사용자 |
| [`ci-setup`](ci-setup.md) | `bootstrap` | `enforcement` | 사용자 |
| [`codex-cache-update`](codex-cache-update.md) | `shortcuts` | `analysis` | 사용자 |
| [`config`](config.md) | `config` | `state` | 사용자 |
| [`cost-gate`](cost-gate.md) | `audit` | `enforcement` | 사용자 |
| [`docs-maintenance`](docs-maintenance.md) | `audit` | `analysis` | 사용자 |
| [`evaluate`](evaluate.md) | `eval` | `enforcement` | 사용자 |
| [`hook-doctor`](hook-doctor.md) | `audit` | `enforcement` | 모델 |
| [`inspect`](inspect.md) | `audit` | `analysis` | 사용자 |
| [`interview`](interview.md) | `design` | `enforcement` | 사용자 |
| [`llm-refresh`](llm-refresh.md) | `shortcuts` | `analysis` | 사용자 |
| [`log`](log.md) | `shortcuts` | `state` | 사용자 |
| [`plan`](plan.md) | `plan` | `state` | 사용자 |
| [`proposal`](proposal.md) | `design` | `state` | 사용자 |
| [`prune`](prune.md) | `build` | `analysis` | 사용자 |
| [`prune-propose`](prune-propose.md) | `audit` | `state` | 사용자 |
| [`refactor`](refactor.md) | `build` | `analysis` | 사용자 |
| [`research`](research.md) | `design` | `enforcement` | 사용자 |
| [`review`](review.md) | `review` | `analysis` | 사용자 |
| [`security`](security.md) | `security` | `enforcement` | 사용자 |
| [`ship`](ship.md) | `ship` | `state` | 사용자 |
| [`status`](status.md) | `status` | `state` | 사용자 |
| [`token-analyzer`](token-analyzer.md) | `audit` | `analysis` | 사용자 |
| [`valuate`](valuate.md) | `design` | `enforcement` | 사용자 |

스킬 상세 페이지(`docs/skills/<name>.md`)는 사용자용 스킬에 대해
점진적으로 생성된다; 위의 스킬별 행은 페이지가 배포되면 그것에
링크되며, 어느 쪽이든 프런트매터(`name:`, `description:`, `alpha:`,
`user-invocable:`)가 진실 공급원이다. 현재 무엇이 살아있는지는 이
파일 위쪽의 확인 명령을 사용한다.
