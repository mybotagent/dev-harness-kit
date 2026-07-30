# ACP — Agent Coordination Protocol (dev-harness-kit)

**언어:** [English](acp-harness.md) · 한국어

ACP는 오케스트레이터(M), 태스크 서브에이전트(T), 리프 서브에이전트(L)
사이의 결정론적 계약이다. 이전 라운드들이 어렵게 발견한 조정 규칙을
인코딩해서, 향후 라운드가 그것을 다시 발명하지 않도록 한다.

이 문서는 ACP의 설계 SSOT다. 구현은 §7에 나열된 좁은 범위의 PR들에
있다; 각 구현 PR은 여기 고정된 계약에 의해 제약된다.

## 1. 문제 (이 프로토콜이 닫는 다섯 가지 증상)

| # | 증상 | 근본 원인 | 닫는 ACP 조항 |
|---|---|---|---|
| 1 | 서브에이전트의 `cwd`가 워크트리가 아니라 부모 세션의 메인 체크아웃이다. "이 워크트리를 재사용하라"는 힌트가 전파되지 않아 훅이 걸리고 에이전트가 `main`에서 실행된다. | 디스패치 프롬프트가 `<WORKTREE_PATH>`도 `<PARENT_SESSION_CWD>`도 담지 않는다; 자식은 부모의 cwd가 잘못됐다는 것을 알 방법이 없다. | §3 핸드오프 템플릿(필수 플레이스홀더) + §5 cwd-discipline 훅 |
| 2 | 병렬 브랜치들이 같은 `origin/main` HEAD를 보고 각자 `+1` 씩 자동 범프한다 → 여러 브랜치에서 동일한 `plugin.json` 버전(슬롯 충돌). | "+1" 자동 범프는 로컬 연산이다; 병렬 브랜치 전반에 슬롯을 할당하는 할당자가 없다. | §4 version-slot 할당자 |
| 3 | 에이전트가 끝난 후 사용자가 요청하지 않았는데도 후속 디스패치("다음 PR")가 자동으로 발생한다. | 디스패처가 이벤트 기반이지 사용자 게이트 기반이 아니다. | §2 tier-cognition(T는 반드시 멈추고 완료를 assert해야 하며, M이 다음 디스패치를 결정) |
| 4 | 에이전트가 자신이 M인지 T인지 L인지 잊고 범위 밖 작업(커밋, 푸시, 소스 파일 편집)을 시도한다. | 역할이 암묵적이다; 디스패치 프롬프트의 어떤 것도 이를 명시하지 않는다. | §2 tier-assertion + `worktree-guard.sh`에 이미 있는 §5 orch-branch 격리 |
| 5 | 훅 체인이 해석된 파일 경로가 아니라 세션 cwd를 읽기 때문에 여섯 개의 bash-heredoc 우회 패턴이 쌓인다. | 훅이 파일 경로가 아니라 cwd로 범위를 정한다. | §5 cwd-discipline 훅은 도구가 건드리는 file_path에서 해석된 `git -C <path> symbolic-ref --short HEAD`로 범위를 정한다 |

## 2. Tier-cognition 계약

### 2.1 역할 (단일 진실 공급원)

| 티어 | 코드 | 사는 브랜치 | 소유하는 것 | 금지된 것 |
|---|---|---|---|---|
| **M** | 오케스트레이터 | `orch/<round-slug>` (또는 M이 선택한 세션 워크트리) | 라운드 상태, 디스패치 결정, `handoffs.md` 쓰기 | 코드, 훅, 테스트, 매니페스트 편집; `main`에 푸시/커밋; T가 끝난 후 자동 디스패치 |
| **T** | 태스크 서브에이전트 | `fix/<slug>` / `feat/<slug>` / `refactor/<slug>` / `chore/<slug>` / `test/<slug>` / `docs/<slug>` / `perf/<slug>` / `hotfix/<slug>` (T당 브랜치 하나) | PR 하나의 생명주기(브랜치 → 커밋 → 푸시 → PR → 리뷰 응답 → 머지 → 워크트리 정리) | PR 범위 밖 파일 편집; `main`에 푸시; 리뷰 시작 후 force-push |
| **L** | 리프 서브에이전트 | 자신의 T의 워크트리를 상속(cwd = T의 워크트리) | 읽기 전용 조사 하나: 파일 검색, 코드 읽기, 요약 — 편집 없음 | `Edit`/`Write`/`MultiEdit`; `git commit`/`git push`; `gh` 변경 작업 |

### 2.2 Tier-assertion (모든 디스패치된 에이전트의 첫 도구 호출에서 필수)

모든 M, T, L 에이전트는 세션의 **첫 도구 호출**에서 다음 리터럴
줄을 반드시 내보내야 한다:

```
[tier-assert] I am Tier <N> (<M|T|L>). cwd is <WORKTREE_PATH>. I own <OWNERSHIP_SENTENCE>.
```

여기서:

- `<N>`은 M이면 `1`, T면 `2`, L이면 `3`이다.
- `<WORKTREE_PATH>`는 에이전트의 세션 cwd가 해석되는 워크트리의
  절대 경로다. L의 경우 상속받은 T의 워크트리이며, M의 경우
  orch-branch 워크트리다.
- `<OWNERSHIP_SENTENCE>`는 다음 중 하나다:
  - M: `the round state and dispatch decisions only`
  - T: `ONE PR's lifecycle on branch <BRANCH>`
  - L: `read-only investigation for T on branch <BRANCH>; no edits`

### 2.3 Tier-assertion 린트 (`hooks/acp-tier-assert.sh`)

- **이벤트**: `PostToolUse`, 매처 `Bash | Edit | Write | MultiEdit`.
- **트리거**: 모든 에이전트의 첫 비어있지 않은 도구 호출에서
  발생한다. 훅은 세션별 상태를
  `<orch_worktree>/.dev-kit/round-<descriptor>/tier-state/<session-id>.json`
  아래 사이드카 파일에 추적한다(§6 참고).
- **동작**: stdin에서 에이전트 세션 트랜스크립트의 처음 ~4 KiB를
  읽는다(`{"transcript":"..."}`); 리터럴 `[tier-assert] I am Tier`
  접두사가 없거나, `<WORKTREE_PATH>`가 판별 기준(cwd에서 해석된
  `git_dir != git_common_dir`)과 일치하지 않거나, `<OWNERSHIP_SENTENCE>`가
  잘못된 형식이면 누락된 필드를 명시하며 **이유와 함께 거부**한다.
- **Fail-closed 계약**: `jq` 없음 → `PreToolUse` 거부 + exit 2(같은
  `require_jq` 패턴, `hooks/lib/payload-parse.sh`).
- **테스트 범위**: `tests/test_acp_tier_assert.py` — 다음을 커버한다:
  존재 + 부재 + cwd 불일치 + 잘못된 ownership + jq 없음 시
  fail-closed + 빈 stdin no-op + non-Bash/Edit/Write 매처 no-op.

## 3. 핸드오프 포맷

### 3.1 정식 템플릿

정식 서브에이전트 프롬프트 템플릿은
`.claude/skills/_acp/sub-agent-prompt.md`에 있다. `_acp`의 선행
언더스코어는 이것이 *private 템플릿 디렉터리*이지 검색 가능한
스킬이 아님을 나타낸다(프로젝트 스킬 규칙: `rules/skill-authoring.md`).

### 3.2 필수 플레이스홀더 (일곱 개)

모든 디스패치는 반드시 일곱 개 플레이스홀더를 모두 채워야 한다.
핸드오프 린트(`tests/test_acp_hand_off.py`)는 하나라도 빠진 디스패치
프롬프트를 거부한다.

| 플레이스홀더 | 해결 출처 | 없으면 잘못되는 것 |
|---|---|---|
| `<TASK>` | 사용자 요청 또는 M의 분해 스텝 | 서브에이전트에 목표가 없음 |
| `<BRANCH>` | 워크트리의 `git symbolic-ref --short HEAD` | T가 잘못된 브랜치에서 편집(오작동 §1 #1) |
| `<WORKTREE_PATH>` | 워크트리 디렉터리의 절대 경로 | 서브에이전트가 부모 체크아웃으로 `cd`함(오작동 §1 #1) |
| `<CWD>` | 디스패치된 에이전트가 사용해야 할 cwd(항상 = `<WORKTREE_PATH>`) | cwd가 부모 세션의 체크아웃(오작동 §1 #1) |
| `<PLUGIN_VERSION_TARGET>` | `bin/version-slot compute <PR_INDEX>` 출력(§4) | 슬롯 충돌(§1 #2) |
| `<LOCK_FILE>` | `<orch_worktree>/.dev-kit/round-<descriptor>/locks/<branch>.lock`의 절대 경로 | 두 T가 같은 브랜치를 경합(오작동 §1 #1, §6) |
| `<PARENT_SESSION_CWD>` | 디스패치 시점 M의 cwd의 절대 경로 | 서브에이전트가 부모-cwd 오작동을 감지할 방법이 없음(§1 #1) |

### 3.3 테스트 범위

`tests/test_acp_hand_off.py`가 시행하는 것:

- 템플릿 파일이 `.claude/skills/_acp/sub-agent-prompt.md`에 존재.
- 템플릿의 프런트매터(있다면)가 그것이 템플릿이지 스킬이 아님을
  선언(`skills/<name>/SKILL.md` 형태와 일치하는 `name:`/`category:`
  없음).
- 일곱 개 플레이스홀더 모두가 리터럴 `<NAME>` 문자열로 존재.
- 편집된 샘플 디스패치(테스트 픽스처로 제공됨)가 스텁 orch-worktree에
  대해 파싱되고 모든 플레이스홀더가 해석됨.

## 4. Version-slot 할당자

### 4.1 알고리즘 (정식)

```
slot = origin/main HEAD .claude-plugin/plugin.json version + (PR_merge_index - 1)
```

`PR_merge_index`는 1부터 시작한다: `origin/main`의 HEAD 이후 착륙하는
첫 PR은 `+0`(범프 없음 — main의 버전과 동일)을 받고, 두 번째는
`+1`을 받는 식이다. **순진하게 PR당 `+1`을 하는 것은 틀렸다** — 병렬
브랜치는 모두 `origin/main` HEAD에서 시작하므로 모두 `+1`씩 범프하게
되기 때문이다.

### 4.2 네 개의 서브커맨드 (`bin/version-slot`)

| 서브커맨드 | Stdout | Exit | 목적 |
|---|---|---|---|
| `bin/version-slot compute <PR_INDEX>` | 슬롯 버전(예: `0.3.84`) | 0 | T가 자신의 타깃 버전을 계산 |
| `bin/version-slot check` | `ok` 또는 `drift: current=X target=Y` | ok면 0, 아니면 1 | T가 푸시 전에 자신의 브랜치의 `plugin.json`이 슬롯과 일치하는지 확인 |
| `bin/version-slot pin <PR_INDEX>` | `.claude-plugin/plugin.json`과 `.codex-plugin/plugin.json`을 슬롯 버전으로 재고정(현재 워크트리의 두 파일 모두 씀) | 0 | T가 슬롯 드리프트 후 재고정 |
| `bin/version-slot pre-push-gate` | `ok` 또는 드리프트 이유 | ok면 0, 아니면 1 | `git-guard.sh` pre-push에서 호출됨; 현재 < 타깃이면 푸시 거부 |

### 4.3 기존 인라인 헬퍼 (참고용, 정식 아님)

`hooks/worktree-guard.sh`는 이미 프로토타입인 `_compute_version_slot`
bash 함수(46–62번 줄)를 갖고 있다. 향후 `bin/version-slot` 구현은
그 헬퍼를 독립 Python 스크립트로 결정론적으로 추출한 것이어야
한다(테스트 가능하고, 린트 가능하고, pre-push 훅에서 호출 가능하도록).
인라인 헬퍼는 얇은 참고 자료로 남는다; 이를 제거하는 것은 slot PR의
범위 밖이다.

### 4.4 테스트 범위

`tests/test_version_slot.py`가 커버하는 것:

- 스텁된 `git show origin/main:.claude-plugin/plugin.json`에 대한
  `compute`(Python `unittest.mock`으로 `subprocess.run`을 모킹).
- 브랜치의 `plugin.json`이 슬롯과 일치할 때 `check`는 통과, 아니면
  드리프트 문자열과 함께 실패.
- `pin`은 `.claude-plugin/plugin.json`과 `.codex-plugin/plugin.json`
  둘 다에 쓰고 마지막 정수를 정확히 `(PR_INDEX - 1)`만큼 범프.
- `pre-push-gate`는 브랜치 ≥ 타깃이면 exit 0, 브랜치 < 타깃이면
  exit 1이며 stderr에 드리프트 이유를 포함.
- 폴백(`origin/main`에 접근 불가): 스크립트는 `0.3.75`(문서화된
  폴백)를 반환하고 stderr에 `WARN: origin/main unreachable; using
  fallback`을 로그.

## 5. 워크트리-cwd 규율

### 5.1 훅 계약 (`hooks/acp-cwd-discipline.sh`)

- **이벤트**: `PreToolUse`, 매처 `Bash`.
- **판별 기준**: Bash 명령의 argv가 `git`, `gh`, `core.hooksPath=`,
  `cat >`, `cat >>`, `tee `, 또는 어떤 write-tool heredoc
  (`<<EOF`, `<<-EOF`, `<<'EOF'`)로 시작하면, argv에서 **명령의
  의도된 작업 디렉터리**를 해석하고(기본값: 부모의 cwd) 그것의
  `git symbolic-ref --short HEAD`를 예상 브랜치와 비교한다.
- **"예상 브랜치"의 출처**: `git <anything>`이면 `git -C <path>`가
  있으면 파싱하고 없으면 부모 cwd를 사용; `cat > <path>`면 `<path>`를
  절대 경로로 해석하고 `git -C <absolute_dir>`; `gh`면 부모 cwd를
  사용.
- **거부 조건**: 해석된 브랜치가 `main`이고 명령이 읽기 전용 검사
  (`git status`, `git log`, `git diff`, `git show`)가 아닌 경우.
- **거부 이유**: 리터럴 — "Use `git -C <expected-worktree>` or `cd
  <expected-worktree> && <cmd>`. Branch resolution returned main for
  command: <command_prefix>."
- **Fail-closed 계약**: `jq` 없음 → 거부 + exit 2(같은 `require_jq`
  패턴).
- **범위 밖**: `main`에 대한 `git status`/`git log`/`git diff`/`git
  show`는 허용된다(읽기 전용이고 사용자가 비교하고 싶을 수 있다).
  기존 `bash-guard.sh`의 heredoc 차단 목록(`base64`, `python -c`,
  `python3 -c`)을 미러링; 향후 구현 PR은 그 목록을 확장해 여섯 개의
  문서화된 우회 패턴을 커버한다.

### 5.2 `bash-guard.sh`와의 관계

`hooks/bash-guard.sh`는 이미 `git push --force`와 작은 파괴적 패턴
집합을 차단한다. cwd-discipline 훅은 이를 보완한다; cwd-discipline
계약을 위해 **`bash-guard.sh`를 변경할 필요는 없다**. (향후 라운드가
`bash-guard.sh`의 차단 목록이 오래됐다고 판단하면, 그것은
`bash-guard.sh`에 대한 별도 PR이다.)

### 5.3 테스트 범위

`tests/test_acp_cwd.py`가 커버하는 것:

- non-orch `main` 체크아웃에서의 `git commit` → 리터럴 이유와 함께
  거부.
- non-orch `main` 체크아웃에서의 `git push` → 거부.
- 메인 체크아웃에서 `cat > .worktrees/fix-x/foo.sh <<EOF` → 거부.
- 메인 체크아웃에서 `git -C .worktrees/fix-x commit ...` → 허용
  (`-C`가 명령을 재고정).
- 메인 체크아웃에서 `cd .worktrees/fix-x && git commit ...` → 허용
  (`cd`가 재고정; 훅은 `cd` 이후의 argv를 읽음).
- 메인 체크아웃에서 `git status` → 허용(읽기 전용 검사).
- `jq` 없음 → 거부 + exit 2.
- 빈 stdin → exit 0.
- non-Bash 매처(예: Edit) → no-op(훅은 Bash 범위).

## 6. 라운드-메타 프로토콜

### 6.1 라운드 디렉터리

각 라운드의 메타데이터는 **`<orch_worktree>/.dev-kit/round-<descriptor>/`**에
있다. `<orch_worktree>`는 M의 워크트리의 절대 경로이고,
`<descriptor>`는 라운드를 위한 짧은 kebab-case 슬러그다(예:
`p3-skill-governance`).

레이아웃:

```
<orch_worktree>/.dev-kit/round-<descriptor>/
├── handoffs.md         # M 전용 writer; T/L은 reader (§6.2 참고)
├── locks/              # 병렬 T 디스패치를 위한 브랜치별 락 (§6.3 참고)
│   └── <branch>.lock   # T 브랜치당 flock(2) 스타일 파일 락
├── tier-state/         # 세션별 tier-assert 사이드카 (§2.3 참고)
│   └── <session-id>.json
└── decisions.md        # M 전용; 중요한 설계 선택과 근거
```

### 6.2 `handoffs.md` 쓰기 규율

- **M이 유일한 writer다.** T와 L은 자신의 디스패치 프롬프트의
  `<TASK>` 블록에 핸드오프 노트를 덧붙인다; `handoffs.md`를 직접
  편집하는 일은 **결코** 없다.
- M은 각 디스패치마다(`## <timestamp> — dispatch T(<branch>):
  <one-line task>`)와 각 T-완료마다(`## <timestamp> — T(<branch>)
  done: <exit summary>`) 항목을 추가한다.
- T의 `handoffs.md` 읽기 전용 접근은 디스패치 프롬프트에 임베드된
  관련 항목의 사본을 통한다(M이 관련 항목의 마지막 N개를 디스패치에
  임베드).

### 6.3 락 격리

- `<orch_worktree>/.dev-kit/round-<descriptor>/locks/<branch>.lock`의
  브랜치별 flock 락.
- 그 브랜치를 소유할 T를 스폰하기 전에 디스패처(M)가 획득.
- T의 `git push`가 성공한 후(또는 사용자의 명시적 취소 시) M이 해제.
- 락 밖에서의 `git push`는 짝을 이루는 `git-guard.sh` 규칙에 의해
  거부된다(이 이슈의 범위 밖; 향후 lock-isolation PR에서 추적).

### 6.4 라운드 종료

- 라운드 디렉터리는 **명시적 사용자 요청**으로만 제거된다
  (`rm -rf .dev-kit/round-<descriptor>/`).
- 자동 정리 없음. `git clean` 없음. 라운드 디렉터리에서 `git worktree
  remove` 없음.
- M의 워크트리 제거는 `rules/git-workflow.md` §5의 일반 `git worktree
  remove` 절차를 따른다.

## 7. 완료 기준 → 향후 PR 매핑

issue #274의 각 완료 기준 항목은 향후 구현 PR 하나에 매핑된다. **그
PR들 중 어느 것도 이 설계 이슈의 일부가 아니다.** 이 설계 이슈는
§1–§6을 계약으로 배포한다; 아래 PR들은 그것에 대해 구현한다.

| AC 항목 (issue #274) | 향후 PR (각각 좁은 범위) | 건드리는 것 |
|---|---|---|
| `tests/test_skill_governance.py`의 Tier-cognition assertion(L6 시행) | `feat(acp-tier-assert): lint hook + governance test` | `hooks/acp-tier-assert.sh`, `hooks/hooks.json`, `tests/test_acp_tier_assert.py`, `tests/test_skill_governance.py` |
| 핸드오프 템플릿 + 테스트 | `feat(acp-hand-off): canonical template + lint` | `.claude/skills/_acp/sub-agent-prompt.md`(템플릿 스캐폴드만 — 이 설계 이슈와 함께 배포), `tests/test_acp_hand_off.py` |
| `bin/version-slot` 스크립트 + 테스트 | `feat(acp-version-slot): standalone allocator + pre-push gate` | `bin/version-slot`, `tests/test_version_slot.py`, `hooks/git-guard.sh`(짝을 이루는 pre-push 규칙) |
| `hooks/acp-cwd-discipline.sh` + 테스트 | `feat(acp-cwd-discipline): bash-scoped worktree resolver` | `hooks/acp-cwd-discipline.sh`, `hooks/hooks.json`, `tests/test_acp_cwd.py` |
| ACP 섹션이 추가된 `docs/deterministic-harness.md` | `docs(acp): merge into deterministic-harness.md` | `docs/deterministic-harness.md`(`docs/architecture/acp-harness.md`를 이름 변경; §1–§6을 상위 문서로 통합; force-push 안전성과 lock-isolation 섹션 추가) |
| 라운드-메타 쓰기 규율: M 전용 `handoffs.md` | `chore(acp-round-meta): hand-off lock + lifecycle doc` | `docs/architecture/acp-harness.md` §6 상호 참조; 향후 시행 훅(ACP 범위 밖, 별도 추적) |
| 명시적 사용자 요청이 없는 한 새 문서를 추가하는 PR 없음 | 리뷰 시점에 `/dev-kit:review`(기존 게이트)로 시행 | n/a |

## 8. 범위 밖(명시적)

- **"마스터 ACP 오케스트레이터" 프로세스** — M 역할은 기존
  오케스트레이터 패턴(Claude Code 세션 + Codex 서브에이전트)으로
  남는다. 새 데몬 없음.
- **서브에이전트 디스패치를 위한 별도 `bin/` 데몬** — Agent 도구가
  디스패치 프리미티브로 남는다.
- **소비자 프로젝트의 훅** — 이 프로토콜은 `dev-harness-kit`에만
  산다.
- **소비자 프로젝트의 `.claude-plugin/plugin.json` 마이그레이션** —
  슬롯 할당자의 폴백(`0.3.75`)이 접근 불가능한 `origin/main`을
  처리한다; 이 이슈에는 마이그레이션 도구가 없다.
- **`docs/deterministic-harness.md` 생성 또는 업데이트** — 향후 PR;
  §7에서 추적.
- **`hooks/worktree-guard.sh`에서 인라인 `_compute_version_slot`
  제거** — 독립 `bin/version-slot`이 충분히 검증될 때까지 인라인
  헬퍼는 참고용으로 남는다.

## 9. 관련

- PR #266 (`feat/p3-skill-governance-gate`) — L6/L7 Iron Law
  출처(`alpha:` 프런트매터 게이트, `tests/test_skill_governance.py`).
- PR #270 (`fix/worktree-guard-routing-question`) — version-slot 규칙
  + 인라인 `_compute_version_slot` 프로토타입.
- `rules/git-workflow.md` — 브랜치 + 워크트리 프로토콜(모든 태스크
  새 워크트리 규칙).
- `rules/skill-authoring.md` — 스킬 프런트매터 계약(L6 alpha 게이트).
- `rules/session-hygiene.md` — ACP 디스패치를 위한 모델 선택 + 캐시
  규율.
- `hooks/worktree-guard.sh` — orch-branch 격리(M은 `orch/*`에 산다;
  `orch/*` 워크트리에서 쓸 수 있는 것은 `.dev-kit/round-*/**`뿐이다).
- `hooks/lib/worktree-detect.sh` — 공유 `worktree_detect()` 판별
  기준(단일 진실 공급원).
- `hooks/lib/payload-parse.sh` — 공유 `require_jq` + `deny`
  봉투(모든 ACP 훅이 재사용하는 fail-closed 패턴).
- `tools/token_efficiency_analyzer.py` — 세션 비용 대시보드; ACP
  디스패치 프롬프트는 session-hygiene §3(프롬프트 꼬리의 변동
  콘텐츠)을 따라야 한다.
- 메모리: `feedback-rounds-leave-no-files.md`,
  `feedback-minimal-action-on-vague-prompts.md`.
