# ACP Dispatch — M-tier 아키텍처

**언어:** [English](ACP-DISPATCH.md) · 한국어

> `docs/architecture/acp-harness.md`의 동반 문서. #282를 닫는다.
> M(오케스트레이터) → T(태스크 서브에이전트) → L(리프 서브에이전트)
> 계층 구조, 이들을 연결하는 네 개의 통신 채널, 한 라운드에서 N개의
> PR을 팬아웃하는 병렬 워크트리 생성 패턴을 문서화한다.

## 1. 세 개의 티어 (SSOT)

| 티어 | 코드 | 브랜치 형태 | 소유하는 것 | 금지된 것 | 첫 도구 호출 |
|---|---|---|---|---|---|
| **M** | 오케스트레이터 | `orch/<round-slug>` | 라운드 상태, 디스패치 결정, `handoffs.md` 쓰기 | 소스 코드, 훅, 테스트, 매니페스트 편집; `main`에 푸시/커밋; T가 끝난 후 자동 디스패치 | `[tier-assert] I am Tier 1 (M). …` |
| **T** | 태스크 서브에이전트 | `fix/<slug>` / `feat/<slug>` / `refactor/<slug>` / `chore/<slug>` / `test/<slug>` / `docs/<slug>` / `perf/<slug>` / `hotfix/<slug>` (T당 브랜치 하나) | PR 하나의 생명주기(브랜치 → 커밋 → 푸시 → PR → 리뷰 → 머지 → 정리) | PR 범위 밖 파일 편집; `main`에 푸시; 리뷰 시작 후 force-push | `[tier-assert] I am Tier 2 (T). …` |
| **L** | 리프 서브에이전트 | T의 워크트리를 상속 | 읽기 전용 조사 하나: 파일 검색, 코드 읽기, 요약 — 편집 없음 | `Edit`/`Write`/`MultiEdit`; `git commit`/`git push`; `gh` 변경 작업 | `[tier-assert] I am Tier 3 (L). …` |

Tier-assertion 린트(`hooks/acp-tier-assert.sh`, `hooks/hooks.json`의
PreToolUse `*`에 연결됨)는 필수 `[tier-assert]` 줄을 내지 않은
세션의 첫 도구 호출을 거부한다. 이 단일 가드가
`docs/architecture/acp-harness.md` §1 #4(자신의 역할을 잊은
에이전트의 범위 밖 작업)를 닫는다.

## 2. 네 개의 통신 채널

세 티어는 네 개의 채널로 상태를 공유한다. 모든 채널은 정식 위치와
writer/reader 계약을 가지며, 이를 섞어 쓰는 것이
`docs/architecture/acp-harness.md` §1의 모든 증상의 근본 원인이다.

### 2.1 봉투 (M → T, M → L)

**Writer**: M.
**Reader**: T / L (디스패치된 단일 에이전트).
**위치**: `<orch_worktree>/.dev-kit/round-<descriptor>/dispatches/<branch>.md`.

봉투는 디스패치 프롬프트 그 자체다 — 일곱 개 플레이스홀더가 모두
해결된, `skills/_acp/sub-agent-prompt.md`의 정식 템플릿
사본이다:

| 플레이스홀더 | 해결 출처 |
|---|---|
| `<TASK>` | M의 분해 스텝 |
| `<BRANCH>` | T의 타깃 브랜치 |
| `<WORKTREE_PATH>` | 워크트리 디렉터리의 절대 경로 |
| `<CWD>` | 항상 = `<WORKTREE_PATH>` |
| `<PLUGIN_VERSION_TARGET>` | `bin/version-slot compute <PR_INDEX>` |
| `<LOCK_FILE>` | `<orch_worktree>/.dev-kit/round-<descriptor>/locks/<branch>.lock` |
| `<PARENT_SESSION_CWD>` | 디스패치 시점 M의 cwd의 절대 경로 |

린트(`tests/test_acp_hand_off.py`)는 플레이스홀더가 하나라도 빠진
디스패치를 거부한다. Python 헬퍼 `lib/acp_dispatch.py`
(`ACPDispatcher.fill_placeholders`)는 워크트리가 생성되기 *전에*,
디스패치 시점에 값이 빠져 있으면 `ValueError`를 발생시켜 잘못 설정된
M이 빨리 실패하게 한다.

### 2.2 라운드 상태 (M이 쓰고, T + L이 읽음)

**Writer**: M.
**Reader**: T + L (읽기 전용).
**위치**: `<orch_worktree>/.dev-kit/round-<descriptor>/`.

세 개의 하위 경로:

- `meta.json` — 라운드 매니페스트(PR 목록, 티어 코드, 디스패치
  타임스탬프, 의존성 엣지). M이 유일한 writer이며, T와 L은 봉투에
  임베드된 사본을 통해 참조한다.
- `handoffs.md` — append-only 핸드오프 로그. M은 디스패치마다
  (`## <utc> — dispatch T(<branch>): <one-line task>`) 하나, 완료마다
  (`## <utc> — T(<branch>) done: <exit summary>`) 하나의 항목을
  추가한다. T와 L은 봉투의 `<TASK>` 블록에 자신의 핸드오프 노트를
  덧붙인다 — `handoffs.md`를 직접 편집하는 일은 **결코** 없다.
- `locks/<branch>.lock` — T의 디스패치 생명주기 동안 M이 보유하는
  브랜치별 flock 락. T의 락 파일 경로는 봉투에 임베드되며, T는 첫
  도구 호출에서 반드시 그것을 `touch`해서 `ls`로 활성 브랜치 집합을
  드러내야 하고, M은 `git push`가 성공한 후 락을 해제한다.

### 2.3 티어 센티널 (T가 쓰고, M이 읽음)

**Writer**: T (`hooks/acp-tier-assert.sh`를 통해).
**Reader**: M (감사), 향후 `Eval` 하네스(회귀 채점).
**위치**: `<orch_worktree>/.dev-kit/round-<descriptor>/tier-state/<session-id>.json`.

세션의 tier-assertion 린트가 통과하면 훅이 다음을 쓴다:

```json
{
  "asserted": true,
  "n": "2",
  "letter": "T",
  "cwd": "/Users/.../acp-dispatch",
  "ownership": "ONE PR's lifecycle on branch feat/acp-dispatch",
  "first_tool": "Bash",
  "asserted_at": "2026-07-18T22:34:12Z"
}
```

이후 훅은 같은 세션의 모든 후속 도구 호출에서 no-op이 된다(사이드카가
"tier-asserted" 캐시 역할을 한다). M은 `git push`가 허용되기 전에 각
T가 실제로 asserted 했는지 확인하기 위해 사이드카 집합을 읽을 수
있다; 향후의 `Eval` 회귀는 라운드를 assertion 존재율로 채점할 수
있다.

### 2.4 핸드오프 노트 (T → M, append-only)

**Writer**: T (완료 시 한 줄을 덧붙임).
**Reader**: M (다음 디스패치가 이전 N개 항목을 읽어 의존 PR의
`<TASK>` 컨텍스트를 채운다).
**위치**: `## Hand-off` 헤딩 아래,
`<orch_worktree>/.dev-kit/round-<descriptor>/dispatches/<branch>.md`에
있는 T의 디스패치 봉투 파일에 덧붙여짐. M은 다음 디스패치 프롬프트에
마지막 N개 항목을 복사하므로 `handoffs.md`에 두 번째 writer 없이
컨텍스트가 전파된다.

## 3. M-tier 디스패처 (`lib/acp_dispatch.py`)

`ACPDispatcher`는 봉투 + cut + lock 패턴을 위한 단일 M-tier
진입점이다. 소유하는 것:

1. **정식 템플릿 읽기** — `skills/_acp/sub-agent-prompt.md`에서
   (`--template`으로 오버라이드 가능).
2. **일곱 개 플레이스홀더를 입력 순서대로 채움** — 값이 하나라도
   없으면 `ValueError`를 발생시킨다. `tests/test_acp_hand_off.py`의
   린트 계약을 그대로 따른다.
3. **PR당 워크트리 생성** — `git worktree add -b <branch> <path>
   origin/main`을 통해. 경로 중복이나 이미 존재하는 브랜치에는
   fail-closed로 동작하며, 실패 시 부분 상태를 정리한다.
4. **PR당 봉투 파일 하나를 씀** —
   `<orch_worktree>/.dev-kit/round-<descriptor>/dispatches/` 아래.
5. **PR별 `DispatchResult` 반환** — M이 디스패처를 다시 읽지 않고도
   `meta.json`과 `handoffs.md`를 쓸 수 있게 한다.

CLI 형태:

```bash
python3 lib/acp_dispatch.py \
    --round thin-harness \
    --prs "PR-3:l6-alpha,PR-2:launcher" \
    --parent-session-cwd /Users/sanghee/dev/dev-harness-kit \
    --plugin-version-target 0.3.84 \
    --dry-run
```

`--dry-run`은 파일시스템을 건드리지 않고 봉투를 렌더링한다 — M이
워크트리를 생성하기 전에 팬아웃을 미리 보고 싶은 `plan`과 `review`
단계에 유용하다.

## 4. 병렬 워크트리 생성 패턴

디스패처의 팬아웃 루프는 `hooks/worktree-auto-cut.sh:247-269`의 단일
생성 패턴을 확장한다. 훅이 태스크 프롬프트당 워크트리 하나를
생성하는 반면, `ACPDispatcher.dispatch()`는 한 번의 M 호출에서 N개의
워크트리를 다음 보장과 함께 생성한다:

- **PR별 격리**: 각 `git worktree add`는 자신만의 서브프로세스에서
  실행된다. 하나가 실패하면 그 워크트리만 롤백되고(`git worktree
  remove --force` + `git branch -D`), 다른 워크트리는 그대로 유지된다.
- **브랜치별 락**: 각 T는 `<round>/locks/<branch>.lock`에 락 파일을
  하나 소유한다. 디스패처 자신은 락을 `flock`하지 않는다 — M이 외부에서
  락을 보유하고 그 경로를 봉투에 전달한다. 이는 디스패처를 상태 없이
  유지해서 M이 락 조정 없이 실패한 PR을 재디스패치할 수 있게 한다.
- **기존 브랜치 거부**: 타깃 브랜치가 이미 존재하는 PR(예: 이전에
  중단된 디스패치에서 남은 오래된 브랜치)은 `FileExistsError`를
  발생시킨다. M은 이름을 바꿔 재디스패치할 수 있다; 이는
  `docs/architecture/acp-harness.md` §1 #2의 사일런트 충돌 버그
  클래스를 방지한다.

같은 형태가 `single`과 `parallel` 오케스트레이션 모드 모두에서
동작한다(`git config --global dev-kit.orch.concurrency`). `single`은
디스패처를 PR당 한 번 실행하고, `parallel`은 모든 PR을 한 배치로
디스패처를 한 번 실행한다.

## 5. 첫 진입점 4단계 스택

디스패치된 T가 세션을 시작하면 순서대로 네 개의 가드를 만난다. 각각
`docs/architecture/acp-harness.md` §1의 서로 다른 실패 모드를 닫는다.

| # | 훅 (이벤트) | 매처 | 닫는 것 | 메커니즘 |
|---|---|---|---|---|
| 1 | `acp-tier-assert.sh` (PreToolUse) | `*` | §1 #4(자신의 역할을 잊은 에이전트의 범위 밖 작업) | 트랜스크립트에 리터럴 `[tier-assert] I am Tier …` 줄이 나타날 때까지 첫 도구 호출을 거부한다. `tier-state/<sid>.json`의 사이드카가 세션의 나머지 동안 assertion을 캐시한다. |
| 2 | `acp-cwd-discipline.sh` (PreToolUse) | `Bash` | §1 #1(서브에이전트 cwd가 부모 체크아웃인 경우) | argv(`git -C <path>`, `cd <path>` 등)에서 명령의 의도된 cwd를 해석하고 T의 예상 브랜치와 비교한다. 해석된 브랜치가 main이면 리터럴 이유와 함께 거부한다. |
| 3 | `worktree-guard.sh` (PreToolUse) | `Write\|Edit\|MultiEdit` | §1 #5(여섯 개의 bash-heredoc 우회 패턴) | 메인 체크아웃의 Edit/Write를 강제 차단; 판별 기준은 세션 cwd가 아니라 워크트리에서 해석된 `git_dir != git_common_dir`이다. |
| 4 | `git-guard.sh` (PreToolUse) | `Bash` | §1 #2(병렬 PR의 슬롯 충돌) | `bin/version-slot pre-push-gate`를 통한 pre-push 슬롯 점검; 현재 버전 < 타깃 슬롯이면 `git push`를 거부한다. |

훅 1과 2는 ACP 전용(이 PR + PR-3)이고, 훅 3과 4는 ACP가 그 위에
얹히는 기존 프로젝트 규칙이다.

## 6. 완료 기준 (#282 닫음)

| AC | 검증 위치 |
|---|---|
| `lib/acp_dispatch.py`에 `ACPDispatcher.dispatch(round, prs)` 존재 | `tests/test_acp_dispatch.py::DispatchDryRun::test_dry_run_returns_results_without_cutting` |
| 7개 필수 플레이스홀더 채워짐 | `tests/test_acp_dispatch.py::FillPlaceholders::test_seven_placeholders_match_canonical_template` |
| 3-PR 분해 → 3개 워크트리 + 3개 봉투 | `tests/test_acp_dispatch.py::DispatchFullCut::test_three_prs_produce_three_worktrees_and_three_envelopes` |
| `hooks/hooks.json` PreToolUse `*`가 `acp-tier-assert.sh`에 연결됨 | `tests/test_acp_tier_assert.py::WiringTests::test_hooks_json_wires_pretooluse_star_to_acp_tier_assert` |
| Tier-assert 린트가 누락/잘못된 assertion을 거부 | `tests/test_acp_tier_assert.py::BehaviorTests::test_missing_assertion_denies` + `test_malformed_assertion_denies` |
| Tier-assert 린트가 유효한 T assertion을 허용하고 사이드카로 캐시 | `tests/test_acp_tier_assert.py::BehaviorTests::test_valid_t_assertion_allows` + `test_repeat_call_with_sidecar_is_noop` |
| `jq`가 없을 때 훅이 fail-closed | `hooks/acp-tier-assert.sh:23-26` (거부 + exit 2 자체 완결 printf, `worktree-guard.sh:74-79`에서 미러링) |

## 7. 범위 밖

- **`lib/acp_hand_off.py`** — 핸드오프 린트(`tests/test_acp_hand_off.py`)는
  자매 PR이다(thin-harness 라운드의 T3).
- **`bin/version-slot`** — 별도 PR로 분리됨; 디스패처는
  `--plugin-version-target`을 통해 사전 계산된 값을 받는다.
- **`hooks/acp-cwd-discipline.sh`** — 자매 PR; 디스패처의 argv 해석
  패턴은 §4에 문서화되어 있지만 훅 자체는 여기 범위 밖이다.
- **T 완료 시 자동 디스패치** — `docs/architecture/acp-harness.md` §1
  #3에 의해 명시적으로 금지된다. M은 T가 발생시킨 `[tier-done]` 줄을
  읽고 다음에 무엇을 실행할지 결정한다; 디스패처는 후속 PR을
  스폰하지 않는다.

## 8. 관련

- `docs/architecture/acp-harness.md` — ACP 설계 SSOT (§1–§6).
- `skills/_acp/sub-agent-prompt.md` — 정식 디스패치 템플릿.
- `hooks/acp-tier-assert.sh` — tier-assertion 린트(이 PR).
- `hooks/acp-cwd-discipline.sh` — cwd-discipline 훅(자매 PR).
- `hooks/worktree-guard.sh` — 기존 워크트리 규칙; 그 위에 얹힘.
- `hooks/git-guard.sh` — 기존 pre-push 슬롯 게이트; 그 위에 얹힘.
- `lib/acp_dispatch.py` — M-tier 디스패처(이 PR).
- `tests/test_acp_dispatch.py` — 디스패처 회귀(이 PR).
- `tests/test_acp_tier_assert.py` — tier-assert 연결 + 동작(이 PR).
- `rules/git-workflow.md` — 워크트리 + 브랜치 프로토콜.
- `rules/session-hygiene.md` — ACP 디스패치를 위한 모델 선택 + 캐시 규율.
- `bin/version-slot` — 슬롯 할당자(자매 PR).
- Issue #282 — 원래 기능 요청.
- PR #266 (`feat/p3-skill-governance-gate`) — L6/L7 Iron Law 출처.
- PR #270 (`fix/worktree-guard-routing-question`) — version-slot 규칙 프로토타입.
