> [← 스킬 인덱스](README.ko.md) · [프로젝트 README](../../README.ko.md)

# `plan`

**카테고리:** `plan` · **알파:** `state` · **호출:** `/dev-kit:plan` (사람이 호출)

`plan`은 한 줄 아이디어를 5개 게이트를 단일 Ralph 루프에서 실행하여
`PRD.md`와 `phases/<name>/{index.json, step<N>.md}`로 바꾼다. 옛 8-게이트
구조( frame → evidence → diff → non-goals → socratic → phase-decompose
→ seed-convergence → prd-writer)를 대체: 그 게이트 중 여러 개가 겹치는
"이것이 빌드할 가치가 있는가?"를 물었으므로 하나의 정량화된 `validate`
게이트로 축소되었다. 이전 `plan-ralph` 서브-스킬도 흡수(이슈 #58) —
`plan`은 완전히 자기 완결이며 위임된 서브-스킬 호출이 없다. 스킬은
계획 산출물만 생성: 사용자가 "그냥 코드를 작성하라"고 해도 코드, 빌드,
또는 배포 출력 없음.

## 사용 시점

- 사용자가 아이디어와 함께 `/dev-kit:plan`을 입력.
- 사용자가 PRD를 재생성하길 원함.
- HOLD 일시 중지 후 `.dev-kit/decision-log.md`에서 재개(게이트 2의
  모호성 루프 캡이 수렴 없이 도달).

## 작동 방식

### 워크트리 전제조건 (fail-closed)

게이트 1이 물어보기 전, 스킬은 `./.git`을 읽어 cwd가 워크트리인지 메인
체크아웃인지 감지(`plan`의 `disallowed-tools`가 `Bash`를 포함하므로 `Bash`
대신 `Read` 사용). `./.git`이 `gitdir:`로 시작하는 파일이면 cwd는 워크트리이며
게이트 1 진행. `./.git`이 디렉터리(메인 체크아웃)이면 스킬은 게이트 1
물음 전에 중단하고 부모 에이전트에게 먼저 워크트리를 자를 것을 알린다 —
어쨌든 진행하면 `hooks/worktree-guard.sh`가 모든 `Write`를 블록해 게이트
응답은 캡처되지만 `PRD.md`가 방출되지 않으며, 실패는 `/dev-kit:build`가
단계 누락으로 실패할 때만 나중에 드러난다.

### 5개 게이트, 1 Ralph 루프

```
[1/5] frame        — 목표 + 타겟 사용자 + 1줄 상황
       ↓
[2/5] validate     — 증거 (>=3 소스) + value_score + 모호성 루프
       ↓
[3/5] non-goals    — 3+ 비-목표와 rationale + 위반-응답
       ↓
[4/5] decompose    — phases/<name>/index.json + step<N>.md (단계별 상태)
       ↓
[5/5] emit         — PRD.md 6-섹션 DoD 통과 + 핸드오프
```

**게이트 1/5 — frame.** 한 메시지에서 묻는다: 목표(한 문장, 무엇이 출하되고
사용자에게 무엇이 바뀌는지), 타겟 사용자(한 명명된 페르소나, "모두"가
아님), 상황(한 문장, 오늘 사용자가 어디에 있는지). 빈 필드는 한 번 더
묻고 `"<unspecified>"`로 채움. 3개 필드 모두 `# frame` 아래 `.dev-kit/decision-log.md`에
기록.

**게이트 2/5 — validate.** 세 가지 숫자 입력이 하나의 합성 수렴 검사를
공급:
- *증거*: 타겟 사용자가 이것을 원한다는 독립 신호 ≥3개(`{source, claim, date}`)를
  한 번 묻는다. 3개 미만이면 게이트 실패 — "한 번 더 다듬기" 재시도 없음,
  카운트 게이트가 이 입력을 게이트함.
- *Value score*: 묻지 않고 계산 — `value_score = (LTV_per_user × reachable_users_year1) / total_cost`.
  임계값 `value_score >= 3.0`; 미만이면 게이트 실패 및 스킬이 갭을
  닫는 단일 최대 레버를 명명(더 저렴 / 더 도달 가능 / 더 높은 LTV —
  하나, 리스트 아님).
- *모호성 루프 (0-10)*: 10에서 시작. 각 반복은 정확히 하나의 질문을
  최고-레버리지 미지에 대해 묻고(노브: user, pain, scope, metric, kill —
  각 -1 ~ -3 점수), 그 다음 재점수. 재점수는 이전 반복보다 낮아야 함
  (`narrowed_delta`); 두 번 동일한 점수가 연속되면(`dedup_metric: identical-ambiguity-cycle=2`)
  루프를 "최선"으로 조기 종료.
- *수렴 검사*: `evidence_count >= 3 AND value_score >= 3.0 AND ambiguity_score <= 3`인
  경우에만 PASS. FAIL이면 실패 차원에서 루프, `safety_valve=8` 반복에서
  캡. 캡 도달 시 패스 없으면 `"status": "held"`를 `loop-log.json`에 쓰고,
  남은 갭을 표면화하며, `PRD.md`를 자동 방출하지 않음.

**게이트 3/5 — non-goals.** PRD가 하지 않을 3가지를 각각 rationale과
breach-response(리뷰어가 다시 추가하라고 묻는 경우 일어나는 일)와 함께
한 번 묻는다. 3개 미만 → 스킬이 결정 로그에서 후보를 생성하고 사용자에게
확인 또는 교체를 묻는다. PRD.md §3에 기록.

**게이트 4/5 — decompose.** `phases/<name>/index.json`(한 단계 = 하나의
출하 가능, 의존성 순서화된 레이어) 방출. 최상위 `worktree` 필드는 각
단계별 워크트리가 파생되는 브랜치 베이스(`<branch-base>-step<N>`)를
가지고, 규약적으로 `<prefix>-<phase>`이며 `<prefix>`는 워크트리-컷 규약을
따름(예: `plan/plugin-harness-v3`); 부재 시 빌드 러너는 `feat/<phase>`로
폴백 — 계약이 아닌 방어-인-심층. 각 단계에 대해: `lib/execute.py:register_step()`이
인덱스 항목을 `status="unimplemented"`로 생성, 그 다음 스킬이 고정된
템플릿(Status / Read first / Task / Acceptance Criteria / Verification &
Status Update / Don't)에서 `phases/<name>/step<N>.md`를 작성 — plan은
오직 `Status: pending`만 기록; 러너와 실행 서브에이전트가 나머지
라이프사이클을 소유. 단계별 상태 값은 SSOT `lib/execute.py:VALID_STATUSES`;
plan은 오직 `unimplemented`와 `pending`만 기록 — 런타임 상태(`in_progress`,
`completed`, `error`, `blocked`)는 하네스-러너의 것.

단계 파일의 `Verification & Status Update` 섹션은 두 개의 필수 HTML-주석
마커(`<!-- status: completed|error|blocked -->`와 매칭 `<!-- summary/error_message/blocked_reason: ... -->`)로
종료 — 이것은 build 러너의 파서가 읽는 plan↔build SSOT; 누락되거나
잘못 형성되면 러너가 index.json 상태로 폴백.

**기계-실행 가능 검증 (`lib/verify_harness.py`).** 단계는 하네스-러너가
`completed` 대 `error`를 결정하기 위해 실행할 명령을 선언 — 자유 텍스트
AC 산문만 사용하지 않음. 초기 `lib/verify_harness.py` PR 기준으로 이
필드는 파싱되어 실행 가능하지만 **`lib/execute.py`에 아직 배선되지 않음**
— 후속 PR이 `_verify_and_retry` 게이트를 착륙시킬 때까지 러너는
서브프로세스 exit-0만으로 `completed`를 결정. 오늘 `verification`을 선언하는
것은 단계의 의도를 기계-파스 가능하게 만드는 것을 넘어 런타임 효과가
없음. 우선순위: `index.json`의 단계 필드 `verification`(`str | list[str]`,
예: `"verification": "pytest tests/test_foo.py -q"` 또는 `"verification": ["pytest tests/test_foo.py -q", "ruff check lib/foo.py"]`)이
step.md `Verification & Status Update` 헤더 아래 펜스된 코드 블록을
이김(펜스 내에서 주석/공백이 아닌 각 줄이 하나의 명령). 어느 출처로도
선언되지 않은 단계는 `[]`로 선언되며 게이트는 no-op — 이 필드 이전
기존 단계는 현재 동작을 변경하지 않고 유지. `lib/verify_harness.py:parse_verification()`이
우선순위를 해결; `run_verification()`은 `shlex.split`(no `shell=True`)로
단계의 워크트리에서 각 명령을 실행하고 exit 코드 + pytest `N passed`/`M
failed` 횟수를 증거로 캡처.

**게이트 5/5 — emit.** 5개 DoD 조건에 게이트된 6개 섹션으로 `PRD.md`를
작성: §1 frame은 게이트 1에서 verbatim; §2 validate는 `value_score >= 3.0`
및 `ambiguity_score <= 3` 표시(또는 `status: held` — 이 경우 스킬이
중단하고 사용자에게 묻는다); §3 non-goals은 ≥3 rationale+breach-response
항목; §4 phase plan은 모든 단계 제목을 나열하는 `phases/<name>/index.json`을
가리킴; §5 AC 리스트(1-5 항목)는 단계 AC 명령에 1:1 매핑; §6 hand-off는
다음으로 `/dev-kit:build`를 명명. 스킬은 그 다음 마지막 사이클을 `.dev-kit/loop-log.json`에
추가하고, `.dev-kit/hand-off/plan→build.md`를 쓰며, 디자인 제안을 자동
렌더링(아래 참고).

### Proposal 자동 호출

게이트 5/5의 마지막 단계는 `proposal` 스킬을 호출해 `/dev-kit:build` 실행
전 디자인 레코드를 구체화, 체인을 **plan → proposal → build**로 만든다.
주제 슬러그는 `<main>/<sub>`: `<main>`은 umbrella(이 프로젝트에서는
`harness-architecture`로 하드코딩); `<sub>`은 게이트 4/5의 단계 디렉터리
이름 — 단계 디렉터리, 제안 서브-주제, 워크트리 브랜치 베이스의 `<phase>`
세그먼트가 공유하는 하나의 이름. 스킬은 `docs/proposals/<main>/<sub>.yaml`을
기록(각 PRD §가 하나의 제안 섹션이 됨; 프런트매터 상태는 `design-discussion`)
하고 `Skill("proposal", topic="<main>/<sub>")`를 호출 — `plan`의 `disallowed-tools:
Bash`는 `Skill`이 별도의 도구이므로 블록하지 않음. 서브-주제 슬러그가
잘못 형성되거나 파일이 다른 내용으로 이미 존재하면 제안 스킬이 거부하고
게이트 5/5가 사용자에게 해결을 위해 모순을 표면화.

## 사용법

```bash
/dev-kit:plan
```

0-인자 — 아이디어는 플래그가 아닌 사용자 프롬프트 텍스트로 제공됨.

## 출력

- `PRD.md` — 6-섹션 계획.
- `phases/<name>/index.json` — 단계 상태 머신.
- `phases/<name>/step<N>.md` — 단계당 하나.
- `.dev-kit/decision-log.md` — 누적 Q&A 및 점수 델타(반복에 걸친 누적).
- `.dev-kit/loop-log.json` — 사이클별 좁히기 (MUST-16).
- `.dev-kit/hand-off/plan→build.md`.
- `docs/proposals/<main>/<sub>.{yaml,html}` — 자동 렌더링된 디자인 레코드.

## 관련

- [proposal](proposal.md) — 디자인 레코드를 렌더링하기 위해 게이트 5/5에서
  자동 호출; 이 스킬이 방출하는 YAML 형태는 "Authoring a proposal" 섹션 참고.
- `/dev-kit:build` — 명명된 다음 단계; 하네스-러너를 통해 `phases/<name>/step<N>.md`를
  소비.
- `lib/execute.py` — `register_step`, `VALID_STATUSES`, `update_step_status`,
  `parse_status_marker()` 소유.
- `rules/git-workflow.md` — 게이트 4/5의 `worktree` 필드가 참조하는 워크트리-컷
  규약.

---
*출처: [`skills/plan/SKILL.md`](../../skills/plan/SKILL.md)*
