# Live Context Server (LCS) — 사용 참조

> 하네스의 실시간 상태를 위한 읽기 전용 URI 표면 — 훅, 에이전트, 운영자가
> 모두 같은 화면을 본다.

dev-kit · Phase 1.x (issues #346–#356) · v0.3.147

## 목차

1. [무엇인가](#1-무엇인가)
2. [URI 문법](#2-uri-문법)
3. [리소스](#3-리소스)
4. [CLI 표면](#4-cli-표면)
5. [JSON-RPC 트랜스포트 (`--serve`)](#5-json-rpc-트랜스포트---serve)
6. [통합 맵](#6-통합-맵)
7. [빠른 시작](#7-빠른-시작)
8. [치트시트](#8-치트시트)
9. [README 드리프트](#9-readme-드리프트-v03147-기준)
10. [검증 로그](#10-검증-로그)

---

## 1. 무엇인가

Live Context Server (LCS)는 dev-harness-kit 하네스의 실시간 상태를 하나의
네임스페이스 — `lcs://<resource>` — 아래에 노출하는 **읽기 전용**,
인-프로세스 URI 라우터다. 이는 `git worktree list`, `gh pr checks`, 버킷별
토큰 질의, 스킬별 인터뷰 조회 같은 임시 셸아웃을 한 번의 왕복 JSON
페이로드로 대체한다.

이것은 **아니다**:

- 데몬. 호출 프로세스 (소비자당 하나의 `LCSServer`) 안에서 동작하며, 5초
  인메모리 스냅샷 캐시를 가진다.
- 데이터베이스. 모든 페치는 매번 새로운 파일시스템 / 서브프로세스 상태를
  읽는다.
- 변경 가능. 리소스는 디스크에 쓰거나 네트워크에 푸시하지 않는다 (`gh api`
  / `git` 읽기 이상).

### 세 조각

1. **서버 코어** (`lib/lcs_server.py`, 308 LoC) — URI 파서 + 최장 일치
   라우터 + URI별 스냅샷 캐시. 순수 함수, 전역 상태 없음.
2. **CLI 드라이버** (`bin/dev-kit-lcs.py`) — 서버를 감싼 얇은 래퍼.
   Bash, MCP 클라이언트, 훅에서 stdio로 스폰된다.
3. **리소스 핸들러** (`lib/lcs_resources/*.py`) — URI당 하나의 Python
   클래스. 기본 레지스트리에서 6개가 출시되며, 3개는 요청 시 임포트된다.

---

## 2. URI 문법

스킴은 `lcs://` (소문자, 대소문자 구분)로 고정된다. 본문은 `/`로 분리되며,
마지막 세그먼트는 리소스 이름 또는 경로 파라미터가 될 수 있다 — 레지스트리에
대한 최장 일치로 결정된다.

```
lcs://<resource-name>[/<segment>[/...]][/]

컬렉션 형태            URI가 "/"로 끝난다. 일부 리소스는 이를 거부한다 (interview, pr).
경로 파라미터 형태      URI 본문이 리소스 이름 뒤에 하나 이상의 세그먼트를 가진다.
트레일링 슬래시 관용    "lcs://worktrees"와 "lcs://worktrees/" 모두 해석된다.
중첩 리소스 이름        "lcs://hooks/coverage"는 레지스트리에서 단일 키로 등록되며,
                       최장 일치 리졸버가 접두사를 순회한다.
세그먼트 내부 슬래시    %2F로 인코딩 — 왕복 보존됨:
                       "lcs://branches/feat%2Ffoo"는 한 세그먼트로 유지된다.
```

모든 페치는 정규화된 봉투(envelope)를 반환한다:

```json
{
  "status":  "ok" | "partial" | "error",
  "data":    <핸들러 고유 dict>,
  "missing": [str, ...]   // status="partial"일 때 존재
  "error":   str          // status="error"일 때 존재
}
```

핸들러는 외부로 예외를 던지지 않는다 — 예외는 `status="error"` 페이로드가
되어 읽기 경로가 충돌하지 않게 한다.

---

## 3. 리소스

**기본 레지스트리에서 6개의 리소스가 출시된다.** 3개 (`hooks/coverage`,
`interview`, `research/cache`)는 임포트 가능하지만 기본 CLI 레지스트리에는
없다 — 아래 [README 드리프트](#9-readme-드리프트-v03147-기준) 참조.

### `lcs://worktrees[/{branch}]` — 모든 git worktree

`git worktree list --porcelain`을 통해 모든 worktree를 나열한다. 항목 형태는
더티 파일 목록, 훅 연결 상태, 슬롯 버전을 추가한다.

컬렉션 — `lcs://worktrees`:

```json
{
  "status": "ok",
  "data": {
    "worktrees": [
      {
        "branch":       "main",
        "path":         "/Users/sanghee/dev/dev-harness-kit",
        "head":         "6bd1073bbef4b50d477aaabedfbafc4511a8d459",
        "detached":     false,
        "dirty_files":  [],
        "dirty":        false,
        "hooks_wired":  true,
        "last_touched": "2026-07-28T02:01:14+00:00",
        "slot_version": "0.3.147"
      }
    ]
  }
}
```

항목 — `lcs://worktrees/main`: 하나의 컬렉션 항목과 같은 형태, 추가로
`git status --porcelain`이 채운 `dirty_files` 배열 포함.

실패 모드:
- 단일 깨진 worktree → `status="partial"`, 깨진 서브필드가 `missing`에
  나열됨.
- `.dev-kit/runtime.json` 없음 → `slot_version: null`.

### `lcs://branches/{name}` — 한 브랜치 스냅샷

로컬 HEAD, 원본 HEAD, ahead/behind 카운터, 마지막 CI 실행 (`gh api`
경유), `plugin.json`에서 머지된 슬롯 버전. README는
`lcs://branches/<name>/slot`을 언급하지만, 그 하위 URI는 **구현되지
않았다**; 슬롯 버전은 메인 페이로드에 있다.

```json
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

실패 모드:
- 브랜치가 로컬에 없음 → `status="partial"`, `missing=["no such branch"]`.
- `origin/<name>` 업스트림 없음 → `(ahead=0, behind=0)`, 실패 아님.

### `lcs://pr/{number}` — 한 PR의 CI + 리뷰

`gh pr view <N> --json number,title,state,statusCheckRollup,reviews,comments`에
의해 구동된다. 항목 전용 — 컬렉션 형태는 `LCSError`를 발생시킨다.

항목 — `lcs://pr/447`:

```json
{
  "status": "ok",
  "data": {
    "number":              447,
    "title":               "feat(audit): Phase 7 batch — cross-harness audit",
    "status":              "MERGEABLE",
    "checks":              [...],
    "reviews":             [...],
    "unresolved_threads":  [...]
  }
}
```

실패 모드:
- `gh`가 없거나 인증되지 않음 → PR 번호 + 갭을 설명하는 `missing`을 가진
  `status="partial"`.
- PR을 찾을 수 없음 → 동일한 부분 봉투.

### `lcs://sessions/{id}` — 하나의 기록된 세션

세 가지 소스에서 세션을 해석하며, 첫 번째 적중이 이긴다:

1. `<logs_root>/sessions/<id>.json` — 정식 상태 덤프 (Phase 0.4)
2. `<logs_root>/<id>.json` — 동일한 정식 스키마, 최상위
3. `<logs_root>/{claude-code,codex}/*<id>*.jsonl` — 트랜스크립트에서 파생

항목 페이로드 (6개 필드):

```json
{
  "status": "ok",
  "data": {
    "id":            "a0f83efc-...",
    "role":          "user" | "assistant",
    "cwd":           "/Users/.../dev-harness-kit",
    "current_task":  "Show worktree state",
    "last_tool":     "Bash",
    "started_at":    "2026-07-28T01:55:12Z"
  }
}
```

실패 모드:
- 모든 소스에 레코드 없음 → `missing=["no session <id>"]`을 가진
  `status="partial"`.

### `lcs://spend/{window}` — 토큰 소비 버킷

`<logs_root>/{claude-code,codex}/**/*.jsonl`을 순회하며 TokenLog 레코드를
찾고, 세션 / worktree / 스킬별로 버킷팅한다.

윈도우 문법:

- `lcs://spend/today` — UTC 일, 00:00 → 24:00
- `lcs://spend/last-hour` — `now`에서 끝나는 60분
- `lcs://spend/<iso-start>-<iso-end>` — ISO-8601 범위, 둘 다 UTC에 `Z` 접미사

```json
{
  "status": "ok",
  "data": {
    "window":       { "since": "...", "until": "..." },
    "by_session":   [{ "key": "<id>",      "tokens": 12345 }],
    "by_worktree":  [{ "key": "main",      "tokens": 78910 }],
    "by_skill":     [{ "key": "build",     "tokens": 12321 }]
  }
}
```

로그 비어있음 / 윈도우 비어있음 → 빈 배열, 실패 없음.

### `lcs://valuations/{plan-id}` — 빌드 게이트 판정

`<project>/.dev-kit/valuations/<plan-id>.json`을 읽는다 — `valuate` 스킬이
쓴 정식 판정 봉투. 빌드 게이트가 이를 소비하며, `decision == proceed`와
유효한 status가 게이트를 통과하는 유일한 방법이다.

```json
{
  "status": "ok",
  "data": {
    "plan_id":            "phase-2-3",
    "decision":           "proceed" | "revise" | "hold" | "kill",
    "rationale":          "...",
    "blocking_findings":  [...],
    "scores":             { ... },
    "persisted_at":       "2026-07-28T01:55:12Z"
  }
}
```

실패 모드:
- 봉투 누락 → `status="partial"` → 빌드 게이트가 `hold`로 처리.
- 읽기 / 파싱 오류 → `status="error"` → 실패-페일드(fail-closed).

### `lcs://demo/{anything}` — 에코 리소스 · 개발 전용

내장 전송 테스트. 외부 상태 없이도 읽기 경로를 운동할 수 있도록 파싱된
URI를 JSON으로 반환한다. 환경 변수 `DEV_KIT_LCS_DEMO=1`로 활성화.

```bash
$ DEV_KIT_LCS_DEMO=1 python3 bin/dev-kit-lcs.py --get 'lcs://demo/example%2Fpath'
{
  "status": "ok",
  "data": {
    "first_segment": "demo",
    "path_segments": ["demo", "example/path"],
    "is_collection": false
  }
}
```

### 기본 레지스트리에 없는 리소스

| URI | Status | 기본적으로 꺼져 있는 이유 |
|---|---|---|
| `lcs://hooks/coverage` | `ok \| partial` | `.claude/hooks.json` + `.codex/hooks.json` + `hooks/*.sh`을 읽는다. hook-doctor가 사용. |
| `lcs://interview/{step}` | `ok \| partial \| error` | `.dev-kit/hand-off/<step>.md`을 읽는다. `lib/interview_engine.py`가 소비. 항목 전용. |
| `lcs://research/cache[/{sub}]` | `partial` | v1 스텁 — 모든 `/{sub}`가 `LCSPartialError`를 발생. Phase 5에서 채워짐. |

---

## 4. CLI 표면

하나의 파일, 네 개의 상호 배타 플래그. 정확히 하나가 필요하다:

```bash
$ python3 bin/dev-kit-lcs.py --help
usage: dev-kit-lcs [-h] (--list-resources | --describe NAME | --get URI | --serve)
```

| 플래그 | 표면 | 사용처 | 출력 |
|---|---|---|---|
| `--list-resources` | 휴먼 | 터미널 | 리소스당 한 줄: `name   module.Class` |
| `--describe NAME` | 둘 다 | 터미널 / 에이전트 | `{ "name": "...", "class": "..." }` JSON |
| `--get URI` | 에이전트 | 훅 / 에이전트 / MCP | 전체 status/data 봉투를 JSON으로 |
| `--serve` | 에이전트 | MCP 클라이언트 | stdio 위의 한 줄당 하나의 JSON-RPC 객체 |

### 종료 코드

| 코드 | 의미 |
|---|---|
| **0** | OK — 핸들러가 완전한 페이로드 반환 |
| **1** | 알 수 없는 서브커맨드 / argparse 실패 |
| **2** | URI 파싱 오류 또는 알 수 없는 리소스 |
| **3** | 핸들러가 예외 발생 — 페이로드의 `status="error"` 참조 |

> **STDERR vs STDOUT.** 에러 봉투는 **stderr**로, 성공 페이로드는
> **stdout**으로. `--get` 출력을 `2>/dev/null`로 파이프하는 스크립트도
> 여전히 종료 코드 2/3을 받는다 — 캡처된 JSON에 의존해 실패를 감지하지 말라.

### 스냅샷 캐시

각 `LCSServer`는 `ttl_seconds=5`인 URI별 캐시를 가진다. CLI는 호출당 새로운
서버를 스폰하므로 캐시가 프로세스를 넘나들지 않는다 — 더 신선한 데이터가
필요하면 장기 실행 소비자 안에서 `server.invalidate(uri)`를 호출하라.

---

## 5. JSON-RPC 트랜스포트 (`--serve`)

MCP 클라이언트와 장기 실행 소비자를 위해, `--serve`는 stdio 위에서
JSON-RPC를 말한다. 요청 한 줄당 응답 한 줄, 둘 다 줄바꿈 구분 JSON 객체.

```jsonc
요청   →  {"id": 1, "method": "lcs.list", "params": {}}
응답   ←  {"id": 1, "result": ["branches", "pr", "sessions", "spend",
                              "valuations", "worktrees"]}

요청   →  {"id": 2, "method": "lcs.get", "params": {"uri": "lcs://pr/447"}}
응답   ←  {"id": 2, "result": { "status": "ok", "data": { ... } }}

요청   →  {"id": 3, "method": "lcs.describe", "params": {"name": "spend"}}
응답   ←  {"id": 3, "result": { "name": "spend",
                                "class": "lcs_resources.spend.SpendResource" }}

오류   ←  {"id": 2, "error": "no registered resource matches URI ..."}
```

### 지원되는 메서드

| 메서드 | 파라미터 | 결과 |
|---|---|---|
| `lcs.get` | `{"uri": "lcs://..."}` | 핸들러 봉투 (`{status, data, missing?, error?}`) |
| `lcs.list` | `{}` | 등록된 리소스 이름의 정렬된 목록 |
| `lcs.describe` | `{"name": "spend"}` | `{name, class}` 설명자 |

통지 (`id` 없는 요청)는 조용히 수락된다. 서버는 우아한 MCP 종료를 위해
`SIGTERM` / `SIGINT`를 트랩한다.

---

## 6. 통합 맵

`lcs://`를 읽는 실제 호출 지점. 훅은 더 많은 git 서브셸을 스폰하는 것을
피하기 위해 LCS를 선호한다.

| 소비자 | URI | 이유 |
|---|---|---|
| `hooks/git-guard.sh` (PreToolUse) | `lcs://branches/{branch}` | 푸시 전 plugin.json 범프를 검증하기 위해 `slot_version`을 읽음 — LCS 사용 불가 시 git rev-list로 폴백. |
| `lib/execute.py` (Phase 4) | `lcs://valuations/{plan-id}` | 하드 노고 게이트. `decision == "proceed"`만이 이 지점을 통과하는 유일한 길 — 그렇지 않으면 빌드가 중단. |
| `lib/research_engine.py` | `lcs://research/cache` | Phase 0 캐시 적중. 같은 질의가 최근에 해결되었다면 네트워크 왕복을 건너뜀. |
| `lib/interview_engine.py` | `lcs://interview/{step}` | 각 인터뷰 단계를 게이트하기 위해 5-필드 핸드오프를 읽음 (Phase 6 안전 계약). |
| 채팅 표면 (이 스킬) | 등록된 모든 URI | 사용자 친화 진입점: `/dev-kit:lcs`가 모델 호출 스킬을 호출하여 CLI로 셸. |

> **왜 Python 임포트가 아니라 CLI인가?** 훅은 bash 스크립트이고 MCP
> 클라이언트는 서브프로세스를 스폰한다. `bin/dev-kit-lcs.py`는 단일 계약
> 경계 — 서버 코어 (`lib/lcs_server.py`)는 직접 임베딩을 위해 인-프로세스
> Python 모듈로 남는다.

---

## 7. 빠른 시작

1. **등록된 리소스 나열.**

    ```bash
    $ python3 bin/dev-kit-lcs.py --list-resources
      branches                          lcs_resources.branches.BranchesResource
      pr                                lcs_resources.pr.PRResource
      sessions                          lcs_resources.sessions.SessionsResource
      spend                             lcs_resources.spend.SpendResource
      valuations                        lcs_resources.valuations.ValuationsResource
      worktrees                         lcs_resources.worktrees.WorktreesResource
    ```

2. **리소스 탐색.**

    ```bash
    $ python3 bin/dev-kit-lcs.py --describe spend
    {
      "name": "spend",
      "class": "lcs_resources.spend.SpendResource"
    }
    ```

3. **URI 페치.**

    ```bash
    $ python3 bin/dev-kit-lcs.py --get 'lcs://worktrees/'
    $ python3 bin/dev-kit-lcs.py --get 'lcs://branches/main'
    $ python3 bin/dev-kit-lcs.py --get 'lcs://pr/447'
    $ python3 bin/dev-kit-lcs.py --get 'lcs://spend/today'
    ```

4. **데모 리소스 실행.**

    ```bash
    $ DEV_KIT_LCS_DEMO=1 python3 bin/dev-kit-lcs.py --get 'lcs://demo/example%2Fpath'
    ```

5. **JSON-RPC 말하기.**

    ```bash
    $ echo '{"id":1,"method":"lcs.list","params":{}}' \
      | python3 bin/dev-kit-lcs.py --serve
    {"id": 1, "result": ["branches", "pr", "sessions", "spend", "valuations", "worktrees"]}
    ```

---

## 8. 치트시트

### 사용 케이스 → URI

- "어떤 worktree가 있는가?" → `lcs://worktrees`
- "내 브랜치 슬롯이 최신인가?" → `lcs://branches/{name}`
- "이 PR이 통과인가?" → `lcs://pr/{n}`
- "이번 시간 토큰 소비는?" → `lcs://spend/last-hour`
- "빌드가 진행 가능한가?" → `lcs://valuations/{plan-id}`
- "세션 X는 어디에?" → `lcs://sessions/{id}`

### 실패 처리

- `status="partial"` → 누락 필드가 `missing[]`에 나열. 가지지 않은 데이터로
  취급.
- `status="error"` → `error` 문자열 확인. 핸들러가 충돌 (드묾). 대부분
  서브프로세스 실패 (`gh` 없음 등)를 의미.
- 종료 코드 2 → URI 잘못됨 또는 리소스 이름 오타. `--list-resources`로
  철자 확인.

---

## 9. README 드리프트 (v0.3.147 기준)

> README는 §"Live Context Server (LCS)"에서 LCS를 문서화하지만 — 여러
> 주장이 더 이상 코드와 맞지 않는다. README에서 URI를 복사해
> `status="partial"`를 받으면, 다음 중 하나일 가능성이 높다:

| README 주장 | 현실 |
|---|---|
| "다섯 개의 프로덕션 핸들러" | **여섯 개**: `branches`, `pr`, `sessions`, `spend`, `valuations`, `worktrees`. `valuations`는 Phase 4 (issue #373)에서 추가되었으며 README는 여전히 다섯으로 제한한다. |
| `lcs://branches/<name>/slot` | **등록되지 않음.** `slot_version`은 `lcs://branches/<name>` 메인 페이로드의 키다. 하위 URI 주장은 스테일. |
| `lcs://hooks/coverage`, `lcs://interview/<step>`, `lcs://research/cache`가 "프로덕션"으로 나열됨 | **기본 CLI 레지스트리에 없음.** `lib/lcs_resources/`의 임포트 가능한 핸들러 클래스로 출시되며 해당 엔진 (`lib/interview_engine.py`, `lib/research_engine.py`, `hooks/hook-doctor.sh`)에 연결되어 있지만, `bin/dev-kit-lcs.py`는 등록하지 않는다. |
| README의 `/dev-kit:lcs` 채팅 예시 문구 | 여전히 정확: 모델 호출 스킬이 `bin/dev-kit-lcs.py`로 셸하며 JSON을 인라인으로 렌더링. |

---

## 10. 검증 로그

이 문서의 모든 명령은 작성 시점에 실행되었다. Iron Law L3: 완료 주장은
종료 코드를 인용해야 한다.

| 명령 | 종료 |
|---|---|
| `python3 bin/dev-kit-lcs.py --list-resources` | **0** |
| `python3 bin/dev-kit-lcs.py --describe spend` | **0** |
| `python3 bin/dev-kit-lcs.py --get lcs://branches/main` | **0** (`status=ok`) |
| `python3 bin/dev-kit-lcs.py --get lcs://worktrees/` | **0** (204 worktrees; 80개 더티) |
| `DEV_KIT_LCS_DEMO=1 python3 bin/dev-kit-lcs.py --get lcs://demo/example%2Fpath` | **0** (에코 왕복) |
| `echo '{...lcs.list}' | python3 bin/dev-kit-lcs.py --serve` | **0** (stdout의 JSON-RPC 응답) |
| `python3 bin/dev-kit-lcs.py --get lcs://does-not-exist` | **2** (알 수 없는 리소스) |

---

워크트리 `.worktrees/lcs-usage-html`에서 작성 · 브랜치 `docs/lcs-usage-html` ·
`origin/main @ 6bd1073`에서 분기. 영어 원본: [`docs/lcs-usage.md`](lcs-usage.md).
HTML 버전: [`docs/lcs-usage.html`](lcs-usage.html). [`docs/00-index.ko.md`](00-index.ko.md)로 돌아가기.
