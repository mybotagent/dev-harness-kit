# dev-harness-kit — 문서 홈

> Plan, Build, Review, Ship을 타입이 지정된 서브에이전트 위임, Eval-Repair
> 루프, Human-on-the-Loop 감독과 함께 제공하는 통합 하네스 플러그인.
> 훅, 에이전트, 운영자는 직접 서브프로세스 호출을 통해 하나의 Python
> 코드베이스를 공유한다 (별도의 인프로세스 상태 서브스트레이트 없음).

**언어:** [English](00-index.md) · 한국어

---

## TL;DR — dev-harness-kit이 무엇인가?

**dev-harness-kit = 작은 Claude Code / Codex 플러그인 + 단계별 하네스
스펙 + Eval-Repair 루프.**

이 플러그인은 고정된 스킬 집합(`/dev-kit:plan`, `/dev-kit:build`,
`/dev-kit:review`, `/dev-kit:ship` 등), 훅 기반 시행 매트릭스
(`worktree-guard`, `git-guard`, `tdd-guard`, `bash-guard`,
`secret-scan`, `slop-detector`, `stop-verify` 등 — 현재 전체 목록은
루트 [`README.md` → 시행 훅](../../README.ko.md#시행-훅-변치-않는-해자)에서
확인), 그리고 어떤 스킬이 어떤 단계를 소유하고 그 완료 기준이
무엇인지 고정하는 단계별 스펙(`docs/stages/STAGES.md`)과 함께
배포된다.

| 속성 | 값 |
|---|---|
| **무엇인가** | Claude Code + Codex 플러그인 (스킬 + 훅 + 명령) |
| **단계 스펙** | Bootstrap → Plan → Valuate → Build → Review → Security → Ship |
| **상태 서브스트레이트** | 직접 셸 + 서브프로세스; 공유되는 인프로세스 캐시 없음 |
| **와이어 포맷** | 디스크 위의 JSON 봉투 (`.dev-kit/`) |

아래 내용은 *왜 이것이 존재하는지*, *60초 안에 사용하는 법*, *어떤
가치를 얻는지*, *다른 모든 문서가 어디에 있는지*를 설명한다.

---

## 1. 왜 이 시스템이 존재하고, 왜 반드시 존재해야 하는가

> **dev-harness-kit을 처음 본다면 여기부터 시작한다.**

### 고통

`hooks/`와 `lib/`의 여러 파일이 각자 같은 실시간 상태("현재 브랜치
슬롯 버전은 무엇인가?" 또는 "PR #447은 그린인가?")를 필요로 했다.
각 파일은 `git`이나 `gh`를 셸아웃하고, JSON을 인라인으로 파싱하고,
에러를 자기만의 형태로 감싸고, 캐싱을 재구현하거나 아예 생략했다.
드리프트는 필연적이었다: `gh pr view`의 새 필드 하나가 서로 다른
날짜에 세 개의 훅을 깨뜨리곤 했다.

하네스는 엄격한 단계별 소유권(단계당 스킬 하나), 공유되는 훅 시행
(파일별 재구현 없음), 타입이 지정된 디스크 위 봉투
(`.dev-kit/hand-off/*.md`, `.dev-kit/valuations/<plan-id>.json`,
`phases/<name>/index.json`)로 이 문제에 답한다.

**왜 반드시 존재해야 하는가**: 멀티 런타임 하네스(Claude Code +
Codex)에서는 상태 읽기를 재구현하는 모든 소비자가 런타임 간 실패
표면을 만들어낸다. 훅 매트릭스는 그 표면을 모든 소비자가 공유하는
셸 스크립트 집합으로 축소한다.

---

## 2. 60초 빠른 시작

> **오늘 명령 세 개만 실행한다면, 이것들을 실행한다.**

dev-harness-kit을 사용하기 위해 나머지 문서를 다 읽을 필요는 없다.
아래 첫 세 명령이 1분 안에 실행 가능한 데모를 만들어낸다.

### 단계 1 — 새 저장소 부트스트랩

```bash
/dev-kit:bootstrap
# CLAUDE.md + AGENTS.md + .dev-kit/.active-hooks.json 작성
```

### 단계 2 — 단계별 하네스 탐색

```bash
$ open docs/stages/STAGES.md   # 단계별 스펙
```

### 단계 3 — 전체 스킬 목록 탐색

```bash
$ ls skills/   # 모든 /dev-kit:<skill> 이름과 그 SKILL.md
```

이것이 전체 표면이다. 더 구체적인 내용은 문서에 있다.

---

## 3. 실제로 얻는 가치

> **약속이 아니라 구체적인 수치.**

| 지표 | 값 | 상세 |
|---|---|---|
| 배포된 훅 | [시행 훅](../../README.ko.md#시행-훅-변치-않는-해자) 참고 | `worktree-guard`, `git-guard`, `tdd-guard`, `bash-guard`, `secret-scan`, `slop-detector`, `stop-verify` 등 — 해당 표가 현재 유지관리되는 목록 |
| 단계 소유자 | **7개** | bootstrap, plan, valuate, build, review, security, ship |
| Eval-Repair 루프 | **2차원** | harness-quality + os-quality |
| 반환 형태 | **단계당 1개** | `docs/stages/STAGES.md`에 고정된 타입 봉투 계약 |

### 세 가지 구체적 이득

1. **슬롯 범프 드리프트 탐지.** `hooks/git-guard.sh`는 푸시 전에
   `plugin.json` 범프가 `origin/main`과 일치하는지 확인한다. 상태
   서브스트레이트가 필요 없다 — 직접 `git show
   origin/main:.claude-plugin/plugin.json` + JSON 파싱.

2. **빌드 진행/중단 게이트 투명성.** `/dev-kit:valuate`는 판정 봉투
   (decision / rationale / blocking_findings)를
   `.dev-kit/valuations/<plan-id>.json`에 쓴다. 봉투 계약은
   `lib/valuation_engine.py:decision_is_canonical_envelope`에
   고정되어 있다.

3. **Pre-push 의도 점검.** `.githooks/pre-push`는 모든 푸시에서
   유지보수 게이트를 실행한다; `hooks/worktree-guard.sh`는 메인
   체크아웃의 Edit/Write를 거부한다; `hooks/git-guard.sh`는 `main`에
   대한 `git commit`을 차단한다. 세 가지 결정론적 점검, 공유 상태
   없음.

---

## 4. 문서 맵

> 자신의 역할에 맞는 것을 고른다. 처음이라면 위에서 아래로 읽는다.

### 초보자 경로 (순서대로 읽기)

- **00 — 문서 홈** (이 파일)
  > 왜 이 시스템이 존재하는지, 어떤 가치를 얻는지, 다음에 어디로
  > 가야 하는지.
- [`../../README.md`](../../README.ko.md) — 저장소 `dev-harness-kit`
  > 저장소 수준 개요: 설치, Plan/Build/Review/Ship 루프, 명령
  > 레퍼런스, 전체 스킬 목록.
- [STAGES — 단계별 하네스 스펙](../stages/STAGES.md)
  > 루프의 각 단계(bootstrap → plan → build → review → ship)에서
  > 무엇이 일어나고 어떤 스킬이 어떤 단계를 소유하는지.

### 카테고리별 그 밖의 모든 문서

루트 [`README.md` → 문서 맵](../../README.ko.md#문서-맵-분류별)이
저장소의 모든 주제 문서, ADR, 스킬 레퍼런스(아키텍처, 네이밍, CI
설치, 비용/리스크, 팀 도입, 훅 커버리지, 스킬 인덱스)를 분류한 단일
인덱스이며, 각 행마다 HTML/Markdown/한국어 버전이 링크되어 있다. 이
페이지는 Markdown 전용 랜딩 페이지로 남아 그 표를 중복하지 않는다 —
전체 맵은 위 링크를 따라간다.

### 훅과 시행

- [훅 커버리지 갭](../hooks/hook-coverage-gaps.md) — 무엇이 시행되고
  있고, 무엇이 안 되어 있으며, 다음 시행 후보는 무엇인지.
