# dev-harness-kit — 문서 홈

> Claude Code나 Codex를 사용하는 모든 저장소를 위한 읽기 전용 실시간 상태 서버.

통합 하네스 플러그인 — 타입이 지정된 서브에이전트 위임, Eval-Repair 루프,
Human-on-the-Loop 감독으로 Plan, Build, Review, Ship을 수행한다. Live
Context Server (LCS)는 다른 모든 것 아래에 있다: 모든 훅, 에이전트, 운영자가
`git` / `gh` 파싱을 직접 다시 구현하지 않고 참조하는 하나의 `lcs://` 네임스페이스.

---

## TL;DR — Live Context Server (LCS)가 무엇인가?

**LCS = 하나의 작은 Python 프로그램 + 하나의 URI 네임스페이스.**

Live Context Server (LCS)는 dev-harness-kit 플러그인 안에 사는 읽기 전용 URI
라우터다. `python3 bin/dev-kit-lcs.py --get 'lcs://<resource>'`를 실행하면
요청한 실시간 상태 — 현재 브랜치 HEAD, worktree 목록, PR 상태, 토큰 소비,
가치 판정, 세션 정보 — 를 타입이 지정된 JSON 봉투로 받는다. 하네스의 모든
소비자(훅, 에이전트, 채팅 표면, MCP 클라이언트)는 각자가 `git` / `gh` 파싱을
다시 구현하는 대신 *같은* LCS에 말한다.

| 속성 | 값 |
|---|---|
| **무엇** | Python CLI + stdio JSON-RPC 서버 |
| **네임스페이스** | `lcs://<resource>` |
| **읽기 전용** | 쓰지 않음; 에러는 던지지 않고 감쌈 |
| **6개 기본 리소스** | `branches`, `pr`, `sessions`, `spend`, `valuations`, `worktrees` |
| **5초 캐시** | 같은 URI에 대한 동시 읽기는 서브프로세스 하나를 공유 |
| **MCP 와이어 호환** | 모든 MCP 클라이언트가 `--serve`로 연결 가능 |

이 페이지 아래의 모든 내용은 *LCS가 왜 필요했는지*, *60초 안에 사용하는 방법*,
*얻는 이득*, 그리고 *다른 모든 문서가 어디에 있는지*를 설명한다.

---

## 1. 왜 이 시스템이 존재하고, 왜 반드시 존재해야 하는가

> dev-harness-kit을 처음 본다면 여기서 시작하라.

### 고통 (LCS 이전)

`hooks/`과 `lib/`의 여덟 개 서로 다른 파일이 동일한 실시간 상태 조각을
필요로 했다: "현재 브랜치 슬롯 버전은 무엇인가?" 또는 "PR #447이 통과인가?"
각각이 `git` 또는 `gh`로 셸아웃하고, JSON을 인라인으로 파싱하고, 자체
모양으로 에러를 감쌌으며, 캐싱을 자체 구현했다 — 아니면 완전히 건너뛰었다.
`gh`가 없을 때, 한 훅은 충돌하고, 다른 훅은 조용히 폴백했으며, 세 번째 훅은
답을 거짓으로 보고했다. 핫 루프는 단일 babysit 세션에서 `gh`를 60번
재스폰했다.

하네스는 드리프트되었다. 각 소비자가 동일한 파싱 로직을 미묘하게 다른
모양으로, 고립되거나 전혀 테스트되지 않은 채로 재구현했다. 드리프트는
필연적이었다: `gh pr view`의 새 필드가 매일 다른 시점에 세 훅을 깨뜨렸다.

LCS가 답이다: 타입이 있는 봉투(`{status, data, missing?, error?}`)와 URI별
5초 스냅샷 캐시, 강제된 읽기 전용, 그리고 MCP 와이어 호환을 가진 단일
인-프로세스 URI 라우터. 훅과 에이전트가 `lcs://branches/main`을 요청하고 매번
같은 JSON 모양을 받는다 — 에러는 던져지지 않고 감싸진다.

**왜 반드시 존재해야 하는가**: 다중 런타임 하네스(Claude Code + Codex)에서,
상태 읽기를 재구현하는 모든 소비자는 런타임 간 교차 실패 표면을 만든다. LCS는
그 표면을 모든 소비자가 공유하는 하나의 Python 모듈로 축소한다.

---

## 2. 60초 빠른 시작

> 오늘 세 명령만 실행한다면 이것을 실행하라.

dev-harness-kit을 사용하기 위해 LCS를 이해할 필요는 없다. 아래의 처음 세
명령은 1분 이내에 실행 가능한 데모를 생성한다.

### 단계 1 — Live Context Server가 노출하는 리소스 보기

```bash
$ python3 bin/dev-kit-lcs.py --list-resources
  branches                          lcs_resources.branches.BranchesResource
  pr                                lcs_resources.pr.PRResource
  sessions                          lcs_resources.sessions.SessionsResource
  spend                             lcs_resources.spend.SpendResource
  valuations                        lcs_resources.valuations.ValuationsResource
  worktrees                         lcs_resources.worktrees.WorktreesResource
```

### 단계 2 — 단일 URI에 대한 실시간 상태 요청

```bash
$ python3 bin/dev-kit-lcs.py --get 'lcs://branches/main'
{
  "status": "ok",
  "data": {
    "name":         "main",
    "local_head":   "6bd1073bbef4b50d477aaabedfbafc4511a8d459",
    "origin_head":  "6bd1073bbef4b50d477aaabedfbafc4511a8d459",
    "ahead":        0,
    "behind":       0,
    "last_ci_run":  { "conclusion": "success", "name": "CI", "status": "completed" },
    "slot_version": "0.3.147"
  }
}
```

### 단계 3 — 전체 URI 문법 & 통합 맵 탐색

```bash
$ open docs/lcs-usage.html   # 전체 HTML 참조 (English)
$ open docs/lcs-usage.ko.html # 동일한 문서 (한국어)
```

이것이 전체 LCS 표면이다. 더 구체적인 것은 문서에 있다.

---

## 3. 실제로 얻는 가치

> 약속이 아닌 구체적 수치.

| 지표 | 값 | 세부 |
|---|---|---|
| 통합된 파일 | **8 → 1** | 8개의 독자가 재구현. 이제 1개의 라우터가 모두 서비스. |
| `lcs://` 호출 지점 | **60** | 훅, 에이전트, 엔진이 이미 네임스페이스에서 읽는다. |
| 테스트 LoC | **3,094** | 10개 테스트 파일에 걸쳐 — 유지할 정식 표면 하나. |
| 반환 모양 | **1** | 모든 읽기에 대한 `{status, data, missing?, error?}`. |

### 이전 vs 이후

| 중복되던 것 | LCS 이전 | LCS 이후 |
|---|---|---|
| `git` / `gh`로 셸아웃하고 JSON을 인라인으로 파싱하는 파일 | **8**개의 훅/스크립트, 각자 자체 파서 | **0** — `lib/lcs_resources/*.py`만 서브프로세스에 닿는다 |
| babysit-PR 세션당 서브프로세스 스폰 | ~60 (PR 상태 질의당 3개 × 20개 질의) | ~5 (5초 스냅샷 캐시 응집) |
| "실시간 상태"에 대한 서로 다른 반환 모양 | 8 (소비자당 1개) | 1 봉투 |
| MCP 호환 인트로스펙션 엔드포인트 | 없음 | `bin/dev-kit-lcs.py --serve` (stdio 위의 JSON-RPC) |

### 세 가지 구체적 이득

1. **슬롯 범프 드리프트 감지.** `hooks/git-guard.sh`는 푸시 전에 plugin.json
   범프가 `origin/main`와 일치하는지 확인한다. LCS 이전: 셸아웃, porcelain
   파싱, 버전 정규식. LCS 이후: `lcs://branches/main.data.slot_version`를
   읽는 한 줄. 같은 답, 단일 진실 원천, 드리프트 없음.

2. **빌드 노고 게이트 투명성.** Phase 4는 halt-or-proceed를 위해 `valuate`
   판정이 필요하다. LCS 이전: 게이트가 검증 계약 없이
   `.dev-kit/valuations/*.json`을 자체 파싱. LCS 이후:
   `lcs://valuations/<plan-id>`이 타입이 있는 봉투를 반환; 누락은
   `status="partial"`이 되고 → 실패-페일드. 실패-페일드 동작은 모든 소비자
   가 재구현하는 대신 핸들러에 의해 강제된다.

3. **babysit-PR 핫 루프의 비용.** LCS 이전: "PR #447이 아직 통과인가?"를
   묻기 위해 세션당 60개의 서브프로세스 스폰. LCS 이후: 5초 스냅샷 캐시 위의
   5–6 읽기. 캐시는 동시 읽기를 응집한다; bash-guard `slot_version`과 채팅
   `lcs` 스킬이 같은 순간 같은 URI를 요청해도 두 개의 서브프로세스가 아닌
   하나를 지불한다.

---

## 4. 문서 맵

> 역할에 맞는 것을 골라라. 초보자는 위에서 아래로.

> **처음이신가요?** 먼저 **초보자 경로**를 읽어라 — 다른 모든 것이 의미를
> 갖기 전에 중요한 네 페이지를 안내한다. 다른 사람들은 역할에 맞는 카테고리로
> 점프하라.

### 초보자 경로 (순서대로 읽기)

- **00 — 문서 홈** (이 파일)
  > 시스템이 존재하는 이유, LCS가 하는 일, 세 가지 구체적 가치 이득, 그리고
  > 다른 모든 문서의 분류된 인덱스.
- [`../README.md`](../README.md) — 저장소 `dev-harness-kit`
  > 저장소 수준 개요: 설치, Plan/Build/Review/Ship 루프, 명령 참조, 전체
  > 스킬 표면.
- [LCS — Live Context Server 사용 참조](lcs-usage.md) / [한국어](lcs-usage.ko.md)
  > 방금 `--list-resources`로 만진 LCS 참조 — URI 문법, 모든 리소스의 계약,
  > CLI 표면, JSON-RPC 와이어 형식, 통합 맵.
- [STAGES — 단계별 하네스 명세](STAGES.md)
  > 루프의 각 단계에서 일어나는 일(bootstrap → plan → build → review →
  > ship), 그리고 어느 스킬이 어느 단계를 소유하는지.

### LCS & Live Context Server

- [lcs-usage.md](lcs-usage.md) (English) · [lcs-usage.ko.md](lcs-usage.ko.md) (한국어)
  > 전체 URI 문법, 모든 리소스 핸들러, CLI 표면, 종료 코드, JSON-RPC 와이어
  > 형식, 통합 맵, README 드리프트 노트, 그리고 문서에 인용된 모든 명령의
  > 검증 로그.

### 설계 제안 — 하네스 아키텍처

> 플러그인 뒤의 다중 하네스 제안을 다루는 13개 주제 파일 (한국어 본문).
> 대부분 200–375줄이며 주제별로 읽는다 — 질문으로 하나를 골라라.

- [proposals/harness-architecture/00-index.html](proposals/harness-architecture/00-index.html)
  > **00 — 멀티 하네스 시스템 이슈 인덱스** — 제안 폴더 안에서 이것을 먼저
  > 읽어라 — 네 가지 위험 계층, 빌드 원칙 (L7 정렬), 그리고 20분 / 60분 /
  > 주제별 진입을 위한 읽기 경로를 나열한다.
- [01 — MCP: Model Context Protocol (와이어 프로토콜 계층)](proposals/harness-architecture/protocol-layer.html)
  > 왜 우리가 직접 만들지 않고 MCP를 사용하는가: 우리가 타는 공개 표준,
  > 프리미티브, 라이프사이클, 그리고 런타임 중립성 함의.
- [02 — LCS: Live Context Server (상태 리더)](proposals/harness-architecture/live-context-server.html)
  > 서버 코어 뒤의 제안. URI 문법, 최장 일치 해석, 스냅샷 캐시, 그리고
  > 핸들러가 쓰기 없는 읽기를 MCP 와이어 모양으로 바꾸는 방법.
- [03 — 인터뷰 하네스 (모호함 해소)](proposals/harness-architecture/ambiguity-resolver.html)
  > 플랜의 공개 질문이 코드가 작성되기 전에 어떻게 닫히는가.
- [04 — 평가 하네스 (품질 심사)](proposals/harness-architecture/quality-judge.html)
  > 20-checkbox 코드-정상성 루브릭을 가진 다축 AI 산출물 채점.
- [05 — 플랜 가치 게이트 (valuate)](proposals/harness-architecture/value-gate.html)
  > `lcs://valuations/<plan-id>` 뒤의 판정 봉투: proceed / revise / hold /
  > kill, 차단 발견, 점수.
- [06 — 리서치 하네스 (Phase 0–3 에스컬레이션)](proposals/harness-architecture/external-verifier.html)
  > 캐시 → 직접 → 다중 소스 → 사람 폴백. `lcs://research/cache`를 뒷받침하는
  > 리서치 게이트.
- [07 — 런타임 중립성 (결정 8)](proposals/harness-architecture/runtime-portability.html)
  > Claude Code + Codex가 하나의 플러그인에서 동일한 동작을 얻는 방법 —
  > 어댑터 계층.
- [08 — 외부 참조 (insane-search / hermes / AEGIS)](proposals/harness-architecture/external-references.html)
  > 주변 문헌에서 우리가 차용한 것과 의도적으로 기각한 것.
- [09 — 통합 아키텍처 (6 하네스 + 어댑터 + 게이트)](proposals/harness-architecture/consolidated-architecture.html)
  > 큰 그림 — 하네스와 어댑터 계층이 어떻게 맞물려 도는가. 02 / 04 / 06
  > 이후에 읽어라.
- [10 — 결정 기록 (8개 잠금)](proposals/harness-architecture/decision-record.html)
  > 잠긴 여덟 결정과 그 이유; 각 제약이 차단하는 것.
- [11 — 마이그레이션 단계 (Phase 0–7)](proposals/harness-architecture/migration-phases.html)
  > 어떤 PR이 어떤 순서로 출시되는가; 릴리스 태그 뒤의 빌드 순서.
- [12 — 공개 질문 (issue #280 스레드)](proposals/harness-architecture/open-questions.html)
  > 여전히 컨센서스가 필요한 결정 — 유지자들이 피드백을 원하는 불로된 질문들.

### 방법론 & 런북 (Markdown)

- [ci-setup.md — Dev-Kit의 CI 템플릿 설치](ci-setup.md)
  > 모든 소비자 저장소에 dev-kit CI 모양 (branch-policy + validate + test +
  > auto-fix)을 세워라.
- [maintenance-gate.md — 오버 엔지니어링 + 클린 코드 + 가치 게이트](maintenance-gate.md)
  > 20-checkbox PR 전용 게이트 (`.github/workflows/maintenance.yml`). 각
  > 체크박스가 차단하는 것; 채점 방법.
- [RUNTIME-PORTABILITY.md — Claude Code ↔ Codex 어댑터 규칙](RUNTIME-PORTABILITY.md)
  > plugin.json + hooks.json이 어느 쪽에서든 같은 것을 의미하도록 두 런타임이
  > 모두 준수해야 하는 계약.
- [STAGES.md — 단계별 하네스 명세](STAGES.md)
  > 각 단계가 소유하는 것: bootstrap, plan, design, build, review, security,
  > ship.
- [COST-ANALYSIS.md](COST-ANALYSIS.md)
  > 버킷당 토큰 소비, 하드 상한, 그리고 lint가 요구하는 비용 게이트 트레일러
  > 형식.
- [team-adoption.md](team-adoption.md)
  > 단일 유지자와 20명 팀이 하네스를 다르게 채택하는 이유.
- [NAMING.md — 명명 규칙 (ADR-0010 SSOT)](NAMING.md)
  > 훅이 `bash-guard.sh`이고 `bashHook.sh`가 아닌 이유; 스킬/훅 레이블의 진실
  > 원천.
- [PRE-IMPL-CHECK.md](PRE-IMPL-CHECK.md)
  > 코드를 작성하기 전에 답해야 할 9개 질문 체크리스트.
- [ACP-DISPATCH.md — M-tier 아키텍처](ACP-DISPATCH.md)
  > Model-tier 에이전트가 Capability-tier 스킬을 찾고 디스패치하는 방법.
- [acp-harness.md — 에이전트 조정 프로토콜](acp-harness.md)
  > 에이전트 간 대화에서 ACP가 사용하는 와이어 형식; LCS와 어떻게 다른가.
- [hook-coverage-gaps.md — P4 버킷 B 감사](hook-coverage-gaps.md)
  > 런타임별로 어떤 훅 이벤트가 연결되어 있고 어떤 것이 연결되지 않았는지.
- [PROPOSAL-IMPLEMENTATION-PLAN.md — Issue #280](PROPOSAL-IMPLEMENTATION-PLAN.md)
  > 13개 제안 파일 뒤의 상위 수준 계획. 하나의 메가 문서만 읽을 시간이
  > 있다면 유용.
- [REPOSITORY-MAP.md](REPOSITORY-MAP.md)
  > 트리에서 각 컴포넌트가 어디에 살고 있는지. grep이 답을 표면화하지 않을
  > 때 이것을 사용해라.

### 아키텍처 결정 기록

- [ADR-0001 — 5 → 1 흡수](adr/ADR-0001-five-to-one-absorption.md)
- [ADR-0010 — 명명 규칙 (SSOT)](adr/ADR-0010-naming-convention.md) (companion to `NAMING.md`)
- [ADR-0020 — 방법론 확장성 (TDD/SDD/DDD/BDD/FDD)](adr/ADR-0020-methodology-extensibility.md)
- [ADR-0021 — Human Review를 동반한 Eval-Repair 루프](adr/ADR-0021-eval-repair-loop.md)
- [ADR-0022 — eval을 자산 신선도에서 에이전트 동작으로 리팩토링](adr/ADR-0022-eval-agent-behavior.md)

### 스킬 참조

- [skills/README.md](skills/README.md)
  > 카테고리별로 모든 35개 스킬을 탐색 (audit / ship / bootstrap / build /
  > docs / harness / integration / lifecycle / quality / research / runtime /
  > skill-mgmt / state). 전체 명세를 위해 스킬의 `SKILL.md`로 진입하라.

---

## 5. 역할별 읽기 경로

> 여기 온 목적에 맞는 경로를 골라라.

### 초보자 — 방금 dev-harness-kit을 발견했다

1. [`../README.md`](../README.md) — 빠른 시작 + 계층 표
2. **이 페이지** (`docs/00-index.ko.md`) — 왜 + 가치
3. [LCS 참조](lcs-usage.ko.md)
4. [STAGES](STAGES.md) — 각 단계가 소유하는 것
5. 저장소에서 `/dev-kit:bootstrap-full` 실행

### 통합자 — 다른 저장소에 연결하고 있다

1. [런타임 이식성](RUNTIME-PORTABILITY.md)
2. [CI 설정](ci-setup.md)
3. [LCS 제안](proposals/harness-architecture/live-context-server.html)
4. [훅 커버리지 갭](hook-coverage-gaps.md)

### 기여자 — 스킬을 추가하거나 하네스를 바꾸고 싶다

1. [결정 기록](proposals/harness-architecture/decision-record.html)
2. [ADR-0001](adr/ADR-0001-five-to-one-absorption.md)부터 ADR-0022까지
3. [마이그레이션 단계](proposals/harness-architecture/migration-phases.html)
4. [공개 질문](proposals/harness-architecture/open-questions.html)

### 리뷰어 — PR을 읽고 무엇이 잠겼는지 알아야 한다

1. [결정 기록](proposals/harness-architecture/decision-record.html)
2. [공개 질문](proposals/harness-architecture/open-questions.html)
3. [Maintenance 게이트](maintenance-gate.md)
4. [명명 규칙](NAMING.md)

---

## 6. 용어집

| 용어 | 정의 |
|---|---|
| **LCS** | Live Context Server — 모든 훅/에이전트/운영자가 읽는 `lcs://` 아래의 읽기 전용 URI 라우터. |
| **핸들러** | `lib/lcs_resources/<name>.py`에서 `Resource` 프로토콜을 구현하는 하나의 Python 클래스. 각각 단일 명명된 URI를 노출한다. |
| **URI 봉투** | 모든 LCS 읽기가 반환하는 `{status, data, missing?, error?}` dict. |
| **스냅샷 캐시** | URI별 5초 TTL. 윈도우 내 같은 URI에 대한 동시 읽기가 하나의 서브프로세스로 응집된다. |
| **MCP** | Model Context Protocol — LCS가 `--serve` 모드에서 말하는 공개 와이어 표준. |
| **단계** | bootstrap / plan / design / build / review / security / ship 중 하나 — `STAGES.md` 참조. |
| **스킬** | `skills/<name>` 아래의 슬래시 명령 + SKILL.md 번들. 전체 35개 탐색: `skills/README.md`. |
| **훅** | `hooks/` 아래의 bash 스크립트로 Claude Code나 Codex가 라이프사이클 이벤트에서 실행한다. |
| **ADR** | 아키텍처 결정 기록 — `docs/adr/` 아래의 잠긴 결정. |
| **워크트리** | 하나의 작업을 위해 체크아웃된 git 워크트리 (워크트리당 한 브랜치). 하네스가 강제하는 패턴. |

---

워크트리 `.worktrees/lcs-usage-html`의 `docs/00-index.ko.md`에서 작성,
`origin/main @ 6bd1073`에서 분기. 영어 원본: [`docs/00-index.md`](00-index.md).
HTML 버전: [`docs/00-index.html`](00-index.html). [`../README.md`](../README.md)로 돌아가기.
