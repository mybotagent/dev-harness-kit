# 워크플로 시나리오 — 흐름이 일직선으로 흐르지 않을 때

**언어:** [English](WORKFLOW-SCENARIOS.md) · 한국어

정상 경로는 직선이다: `bootstrap → plan → build → review → ship`. 실제
일은 그 라인에 머물지 않는다. 빌드 중에 랩탑을 닫는다. 계획을 시작했는데
틀렸다고 드러난다. 오늘 필요 없는 단계를 건너뛰고 싶다.

이 페이지는 그 경우들을 하나씩, 각각에 대한 구체적 예시와 함께 다룬다.
여기서 모든 것은 플러그인에 오늘 존재하는 명령과 파일을 사용한다 — 만들어진
플래그 없음.

짧은 버전만 원한다면 README의 ["흐름이 일직선으로 흐르지 않을 때"](../../README.ko.md#흐름이-일직선으로-흐르지-않을-때)
섹션에 각 경우에 대한 2-4문장 포인터가 있다.

---

## 빠른 참조

| 상황 | 할 일 | 자세한 곳 |
|---|---|---|
| 빌드가 중간에 멈춤 (터미널을 닫음, 에러 발생, 일시 중지) | `/dev-kit:build` 재실행 — 미완료 첫 단계부터 재개 | [Case 1](#case-1-빌드가-중간에-멈춤) |
| 빌드 단계 실행 중에 계획이 틀렸음을 발견 | `/dev-kit:adapt`, 작은 패치를 하나 승인, 빌드 계속 | [Case 2](#case-2-빌드-중에-계획이-틀렸음) |
| 다른 날 또는 다른 터미널로 돌아왔고 어디까지 했는지 잃음 | `python3 tools/session_monitor.py`가 세션을 찾고 재개 명령을 출력 | [Case 3](#case-3-다른-터미널또는-날에서-돌아옴) |
| Valuate 단계를 실행하고 싶지 않음 | 그냥 건너뛰기 — 권고일 뿐, 빌드를 막는 것은 없음 | [Case 4](#case-4-valuate-단계-건너뛰기) |
| 전체 계획 없이 Build로 직행하고 싶음 | Plan을 좁게 범위화하거나, 한 단계 phase 파일을 직접 시드 — 우회 플래그 없음 | [Case 5](#case-5-전체-계획-없이-build로-직행) |

---

## 배경: Build가 어디까지 했는지 추적하는 방식

Build는 진행 상황을 메모리에 들고 있지 않는다. 디스크에 쓰므로 닫힌
터미널, 크래시, 일주일의 부재를 견딘다.

`/dev-kit:plan`이 실행되면 `phases/<name>/` 폴더를 생성한다:

- `index.json` — 단계 목록과 각 단계의 **상태**.
- `step1.md`, `step2.md`, … — 단계당 한 파일 (읽을 것, 할 일, 인수
  기준, 하지 말 것).

`index.json`의 모든 단계는 이 라이프사이클을 거친다:

```
unimplemented  →  pending  →  in_progress  →  completed
```

런타임 문제를 위한 두 상태가 추가: `error`(단계 실패)와 `blocked`(예:
`/dev-kit:adapt`로 의도적으로 일시 중지).

`/dev-kit:build`는 항상 **`completed`가 아닌 첫 단계**에서 시작한다. 그
단 하나의 사실이 아래의 모든 "중단됨" 경우를 그냥 동작하게 만든다.

---

## Case 1: 빌드가 중간에 멈춤

**예시.** 4단계 피처에 대해 `/dev-kit:plan`을 실행. `/dev-kit:build`를
시작. 1단계와 2단계가 완료. 3단계 도중에 밤에 랩탑을 닫음.

다음 날 아침, 같은 워크트리에서 실행:

```bash
/dev-kit:build
```

일어나는 일: Build가 `phases/<name>/index.json`을 읽고, 1단계와 2단계가
`completed`임을 보고, 완료되지 않은 첫 단계인 3단계에서 픽업. 1단계와
2단계는 반복되지 않는다. 재계획하지 않으며, "resume" 플래그도 전달하지
않는다; 같은 명령을 다시 실행하는 것이 곧 재개다.

빌드가 어떻게 끝났는지 — 정상 일시 중지, 단계의 에러, 또는 프로세스
킬 — 에 관계없이 그렇다. Build는 어떻게 끝났는지가 아니라 상태를 본다.

**단계가 `error`로 표시된 경우.** 실행 중 실패한 단계는 `index.json`에
`error`로 남는다. `/dev-kit:build`를 재실행하면 재시도. 같은 이유로
계속 실패하면 문제는 보통 단계 자체 또는 그 단계가 의존하는 코드이지
재개 메커니즘이 아니다. 단계 파일(`phases/<name>/step<N>.md`)과 단계의
출력(`phases/<name>/step<N>-output.json`)을 읽어 인수 검사가 실제로
보고한 것을 본다.

**아무것도 실행하지 않고 어디 있는지 확인하는 방법:**

```bash
cat phases/<name>/index.json      # 각 단계의 "status"를 본다
/dev-kit:status                   # 루프 진행도의 렌더링된 뷰
```

---

## Case 2: 빌드 중에 계획이 틀렸음

때때로 빌드를 시작한 *후에야* 계획이 틀렸음을 발견한다. 3단계는 존재하지
않는 API 형태를 가정하거나, 인수 기준이 2단계가 실제로 산출한 것과
모순된다. 1단계와 2단계를 버리고 처음부터 재계획하기를 원하지 않는다 —
작은 수정을 원하고 계속 진행하기를 원한다.

이것이 `/dev-kit:adapt`의 용도다.

**예시.** `/dev-kit:plan`을 실행한 다음 `/dev-kit:build`를 실행. 1단계와
2단계가 완료. 3단계가 `in_progress`이며, 작업 중에 계획이 그 단계에
이전 단계가 절대 만들지 않은 함수를 호출하라고 지시했음을 깨달음. 단계는
쓰여진 대로 인수 검사를 통과할 수 없다.

실행:

```bash
/dev-kit:adapt
```

(`commands/adapt.md`에서) 순서대로 하는 일:

1. **일시 중지.** `index.json`에서 진행 중인 단계를 `blocked`로 표시해
   빌드가 더 이상 건드리지 않게.
2. **Diff.** 정확한 모순을 보여준다 — 계획된 인수 기준 또는 명세 줄과
   단계가 실제로 산출한 것(`phases/<name>/step<N>-output.json`)의
   대비.
3. **제안.** `PRD.md` 및/또는 단계 파일에 대해 **하나의** 최소 패치를
   제안 — 그 특정 모순을 해결하는 가장 작은 변경. 새로운 범위 또는
   "이왕 하는 김에" 개선을 추가하지 않는다.
4. **적용.** 명시적 승인 후에만 패치를 쓰고, 단계를 `blocked`에서
   `pending`으로 다시 뒤집고, `/dev-kit:build`로 핸드백하며, 그
   단계에서 재개.

**올바르게 사용하기 위한 중요한 한계:**

- 빌드 단계가 실제로 진행 중일 때만 작동한다(`step<N>-output.json`이
  `in_progress` 또는 `error` 상태로 존재). 실행 중인 빌드가 없으면
  `adapt`가 거부하고 `/dev-kit:plan`을 가리킨다 — 어떤 빌드도 시작되지
  *않기 전에* 계획을 고치는 것은 일반 재계획이지 adapt가 아니기 때문.
- 호출당 하나의 패치. 두 가지가 잘못되었으면 첫 번째를 고치고, 빌드가
  계속되도록 한 뒤, 두 번째에 대해 `/dev-kit:adapt`를 다시 호출.
- 같은 단계에 대해 세 번 `adapt`를 호출한다면, 멈춰라. 그것은 계획
  자체가 불안정한 신호 — `/dev-kit:plan`으로 돌아가 제대로 다시 한다.

**한 줄의 Adapt vs. 재계획:** `adapt` = 진행 중인 빌드를 계속 움직이게
하는 작은 수정; `/dev-kit:plan` = 계획이 근본적으로 틀렸고 새 것을 원함.

---

## Case 3: 다른 터미널/또는 날에서 돌아옴

어제 빌드를 일시 중지. 오늘 새 터미널을 열고 빌드가 어느 워크트리에
있었는지, 또는 세션 id가 무엇이었는지 확신이 없다.

세션 모니터를 사용:

```bash
python3 tools/session_monitor.py
```

`/dev-kit:log` 훅이 캡처한 세션 트랜스크립트(`logs/claude-code/`와
`logs/codex/` 아래)를 읽고, 이 저장소의 워크트리 전반의 최근 모든
Claude Code와 Codex 세션을 나열하며, 화살표 키로 하나를 고를 수 있게
한다. Enter에서 그 세션의 워크트리로 변경해 대화를 다시 열어준다
(Claude Code의 경우 `claude --resume <sid>`, Codex의 경우 `codex resume <sid>`).

인터랙티브 터미널 없는 평범한 셸(SSH, 스크립트)에 있다면 비-인터랙티브
형태를 대신 사용:

```bash
python3 tools/session_monitor.py --list --days 30       # 평범한 리스트, 피커 없음
python3 tools/session_monitor.py --json --days 30        # 기계가 읽을 수 있는 형태
python3 tools/session_monitor.py --print-resume-command  # 첫 세션의 cd + resume 줄을 출력
```

각 세션은 상태 글리프를 표시하여 재개 대상을 알 수 있게:

| 글리프 | 상태 | 의미 |
|:---:|---|---|
| `●` | `live` | 그 워크트리에서 `claude`/`codex` 프로세스가 실행 중이거나, 마지막 턴이 매우 최근 |
| `○` | `idle` | 최근에 캡처되었지만 현재는 활성 아님 |
| `⌀` | `stale` | 워크트리가 머지되었거나 삭제됨; 재개는 메인 체크아웃으로 폴백 |

`stale` 세션은 브랜치가 이미 머지되었거나 워크트리가 사라졌음을 의미 —
거기서 재개할 것이 없을 수 있다. `live`와 `idle`이 평상시 원하는 것이다.

> **이 기능은 `/dev-kit:log`가 켜져 있어야 동작.** 세션 모니터는 로그
> 훅이 쓰는 트랜스크립트를 읽는다. 프로젝트에 로깅을 켠 적이 없으면
> (`/dev-kit:log on`) 나열할 트랜스크립트가 없다. [`docs/skills/log.md`](../skills/log.md)
> 참고.

`session_monitor.py`의 전체 플래그 레퍼런스는 README의 tooling 섹션에
있다.

---

## Case 4: Valuate 단계 건너뛰기

`valuate`는 계획을 6개 축에 대해 점수 매기고 `proceed`, `revise`, `hold`,
또는 `kill` 판정을 반환한다. 이것은 *계획이 빌드할 가치가 있는지*의
sanity 체크이지 빌드 단계가 아니다.

**`kill`을 반환해도 빌드를 막는 것은 없다.** 오늘 Valuate는 권고다:

- PR #589부터 `valuate`는 **모델 호출 전용** — `/dev-kit:plan` 및 다른
  계획 단계가 내부적으로 루브릭을 호출; 슬래시는 사용자 메뉴에 더 이상
  없으므로 손으로 실행할 것이 없다.
- `/dev-kit:build`는 Valuate 판정을 요구하지 **않음**. 비-`proceed`
  판정에 대해 Build를 거부하던 자동 게이트가 있었지만 PR #463에서 그것이
  의존하던 상태 기질과 함께 제거됨.
- 계획 단계가 `hold` / `revise` / `kill` 봉투를 `.dev-kit/valuations/<plan-id>.json`에
  쓰면 Build는 어쨌든 진행. 봉투를 손으로 읽고 heed할지 결정하는 것은
  당신(또는 리뷰어)의 몫. 플래그나 오버라이드는 존재하지 않음.

**여전히 실행할 가치가 있는 경우:** 사소하지 않은 어떤 것이든, `kill`또는
`hold` 판정은 빌드 시간을 쓰기 전의 값싼 통찰이다. 작고 분명히 가치
있는 변경에는 건너뛰는 것이 좋고; 더 큰 것에 대해서는 저비용 gut check으로
실행하는 것이 좋다.

---

## Case 5: 전체 계획 없이 Build로 직행

흔한 바람: "이건 사소하다, 전체 PRD는 원하지 않는다, 그냥 빌드하고 싶다."

**존재하는 것에 대해 분명히 하라.** 오늘 Build로 직행하는 **원커맨드
우회 플래그는 없다.** 이런 일을 했던 두 오래된 단축 명령(`tdd-fast`와
`quick-fix`)이 커밋 `62d2aa9`(PR #456)에서 **제거**되었다. 로컬
체크아웃에 그 명령 파일의 남은 사본이 보이면, 그것은 지원되는 명령이
아닌 오래된 캐시 아티팩트다 — 의존하지 마라.

`/dev-kit:build`는 무엇을 빌드할지 알기 위해 `phases/<name>/index.json`과
단계별 파일을 필요로 한다. 정직한 선택지는:

**옵션 A — Plan을 좁게 범위화 (권장).** `/dev-kit:plan`은 큰 PRD를
산출할 의무가 없다. 작은 작업에 대해서는 좁은 프롬프트를 주고 한두
단계의 짧은 계획을 뱉게 하라. 이것은 정상이고 지원되는 경로이며 작은
일에 빠르다. 여전히 Case 1(재개)과 Case 2(adapt)를 가능하게 하는 단계
추적을 얻는다.

**옵션 B — 최소 phase 파일을 직접 시드.** 계획 대화를 진짜로 건너뛰고
싶다면, 단일 단계와 그것의 `step1.md`로 최소 `phases/<name>/index.json`을
직접 만들고 `/dev-kit:build`를 실행할 수 있다. 이것은 수동이며 지원되지
않는 손 작업이다 — 스키마가 build가 읽을 수 있도록 유효해야 한다 —
따라서 phase 파일 형식을 이미 알고 있을 때만 손을 댄다. 거의 모든
사람에게 옵션 A가 더 쉽고 안전하다.

**추가 메모:** `/dev-kit:build`는 저장소에서 `/dev-kit:ci-setup`이
실행될 때까지 실행을 거부한다(`.dev-kit/ci-config.json`을 확인). 새
저장소에 있다면 `/dev-kit:bootstrap (with ci-setup prompt)` 를 먼저 실행 —
bootstrap과 ci-setup을 한 번에 수행.

Build가 단계 파일도 없이 프로덕션 코드를 쓰는 지원되는 방법은 없다.
단계 파일은 build에게 "완료"의 의미가 무엇인지를 알려주는 것; 그것이
없으면 검증할 대상이 없으며, 이것이 하네스의 전부다.

---

## 더 보기

- [`docs/stages/STAGES.md`](../stages/STAGES.ko.md) — 단계별 전체 명세
  (bootstrap / plan / valuate / build / review / security / ship이 각각
  무엇을 해야 하는지).
- [`docs/skills/build.md`](../skills/build.ko.md) — Build 스킬 상세.
- [`commands/adapt.md`](../../commands/adapt.md) — 정확한 `adapt` 메커니즘.
- [`docs/skills/log.md`](../skills/log.md) — 세션 모니터가 데이터를 가질
  수 있도록 세션 로깅 켜기.
- 메인 [`README.ko.md`](../../README.ko.md) — 설치, 빠른 시작, 그리고 이
  시나리오의 짧은 버전.
