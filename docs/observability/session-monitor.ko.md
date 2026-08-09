# 세션 모니터

**언어:** [English](session-monitor.md) · 한국어

`tools/session_monitor.py`는 `/dev-kit:log`가 이 저장소의 워크트리
전반에서 캡처한 모든 Claude Code와 Codex 세션을 live / idle / stale
상태와 함께 나열한다. 인라인 화살표 키 UI로 하나를 고르면 그 도구가
정확한 `cd <wt> && claude --resume <sid>` 재개 명령을 출력하며
`!`로 실행할 수 있다. stdlib-전용 인라인 피커도 `ssh` 또는 평범한
셸에서 사용 가능하다.

## 어떻게 생겼나

![session-monitor `--list` 출력, dev-harness-kit, 최근 30일](../screenshots/session-monitor.png)

*캡처된 `logs/claude-code/<branch>/*.jsonl` 트랜스크립트에 대한 실제
실행. 스크린샷은 [`tools/render_session_monitor.py`](../../tools/render_session_monitor.py)
(Playwright + Chrome, 1200 × 1400 × 1×)에 의해 재생성된다. 새로 고치려면
`python3 tools/render_session_monitor.py` 실행.*

본문은 컬럼 정렬이다; `--list` 출력과 인터랙티브 피커 둘 다 모든 그룹
라벨 아래에 `STATUS  SRC  ID  MODEL  BRANCH  AGE  COMMIT` 헤더를
출력하여 브랜치가 자체 라벨이 붙은 컬럼으로 읽힌다.

## 모드

| 모드 | 사용 시점 |
|---|---|
| 인터랙티브 피커 (기본, TTY 필요) | 로컬 터미널 / `Terminal.app`. 화살표 키 + Enter. |
| `--list` | 평범한 stdout 리스트 — TTY 없이도 동작, 어떤 하네스에서도 안전. |
| `--json` | 스크립트 / 스킬 소비자를 위한 기계가 읽을 수 있는 출력. |
| `--print-resume-command` | 첫 세션의 cwd + argv를 출력하고 종료 (피커 없음, 실행 없음). 스크립팅에 유용. |
| `--cli-setup` | `session-monitor` 셸 별칭을 `~/.zshrc` / `~/.bashrc`에 (idempotent하게) 설치하고 종료. |

## 빠른 시작

```bash
# 인터랙티브 인라인 피커 (진짜 TTY 필요 — 화살표 키 + Enter)
python3 tools/session_monitor.py

# 평범한 리스트 (TTY 없이도 동작; 어떤 하네스에서도 안전)
python3 tools/session_monitor.py --list --days 30

# 스크립팅 / Claude-Code가 아닌 호출자를 위한 기계가 읽을 수 있는 JSON
python3 tools/session_monitor.py --json --days 30 | jq '.total_sessions, .live_sessions'

# 첫 세션의 resume argv 합성을 디버그
python3 tools/session_monitor.py --print-resume-command
# -> cd /Users/sanghee/dev/dev-harness-kit && claude --resume <sid>

# rc 파일에 `session-monitor` 별칭을 (idempotent하게) 설치
python3 tools/session_monitor.py --cli-setup
# -> 그 후: source ~/.zshrc   (이제 `session-monitor`가 어떤 cwd에서도 동작)
```

## 플래그

| 플래그 | 기본값 | 목적 |
|---|---|---|
| `--days N` | `30` | 룩백 윈도우; 오래된 세션은 제외 |
| `--repo <name>` | (없음) | 저장소 basename의 서브스트링 필터 |
| `--logs-dir <path>` | `<main-repo>/logs` | `claude-code/`와 `codex/` 서브디렉터리의 루트 |
| `--list` | 끔 | 평범한 stdout 리스트 (어떤 하네스에서도 미리보기 가능) |
| `--json` | 끔 | 스크립트 / 스킬 소비자를 위한 기계가 읽을 수 있는 출력 |
| `--print-resume-command` | 끔 | 첫 세션의 cwd + argv를 출력; 종료 |
| `--cli-setup` | 끔 | `session-monitor` 별칭을 `~/.zshrc`/`~/.bashrc`에 (idempotent하게) 설치; 종료 |
| `--filter PATTERN` | (없음) | session_id, branch, model, source, log_path, worktree, status에 걸친 서브스트링 필터 (대소문자 무시) |
| `--picker` | 끔 | 인터랙티브 피커를 요구; TTY가 아닐 때 (조용히 `--list`로 강등하는 대신) 에러를 낸다 |
| `--skill-usage` | 끔 | 같은 로그에 대해 `tools/skill_usage.py`로 워크트리별 상위 스킬 + 글로벌 상위 10 패널을 부착 |
| `--skill-days N` | `30` | `--skill-usage` 집계의 윈도우 (일) (비활성화하려면 `0` 전달) |
| `--dry-run` | 끔 | `--cli-setup`과 함께, 별칭 블록을 쓰지 않고 출력 |

## 상태 시맨틱

| 글리프 | 상태 | 의미 |
|:---:|---|---|
| `●` | `live` | `claude`/`codex` 프로세스가 세션의 워크트리에 cwd로 들어가 실행 중이거나, 마지막 턴이 180초 이내 활성 윈도우 내에 있다 |
| `○` | `idle` | 캡처되어 `--days` 이내이지만 최근에 활성이지 않음 |
| `⌀` | `stale` | 워크트리가 `main`에 머지되었거나 사라짐; resume은 메인 체크아웃으로 폴백 |

## 피커의 작동 방식

인터랙티브 피커는 `termios` + ANSI 이스케이프(stdlib 전용, `curses` 없음,
서드파티 의존성 없음) 위에 직접 구축된다. `Enter`에서 원래 `termios`
모드를 복원하고, 세션의 워크트리로 `cd`하고, `claude --resume <sid>`
(Claude Code) 또는 `codex resume <sid>`(Codex)로 `exec`한다 — `exec`는
Python 프로세스를 대체하므로 사용자가 재개된 세션에 직접 진입한다.
워크트리가 사라지거나 머지되었다면 피커는 메인 체크아웃으로 폴백하고
경고를 출력한다.

각 세션의 `branch`는 워크트리의 현재 `git rev-parse --abbrev-ref HEAD`로
오버라이드되어 피커가 save-log 시점에 캡처된 브랜치가 아니라 워크트리가
*실제로* 있는 브랜치를 보여준다. Stale(merged/gone) 워크트리와
detached-HEAD 워크트리만 로그 캡처 브랜치를 폴백으로 유지한다.

피커 UI는 의도적으로 단일-패널 인라인 패턴이다(화살표 키로 이동, Enter로
재개, `q` / `Esc` / `Ctrl-C`로 취소) — Claude Code 자신의
`AskUserQuestion`이 사용하는 같은 "N개 중 하나 고르기" 패턴 — 그래서
렌더링은 터미널의 일반 스크롤백 안에 머물고 사용자는 마지막 명령의
출력을 잃지 않는다.

### 피커 내부의 라이브 검색

피커 안에서 `/`를 누르면 인라인 편집 버퍼로 진입한다. 인쇄 가능한
각 글자(`q`, `Q`, `/` 포함)가 버퍼에 추가되며 행 집합을 다시 좁힌다;
`Backspace` / `DEL`은 마지막 글자를 제거한다. 헤더는
` session-monitor  /<query>  N / M matches `(필터 후 / 필터 전 카운트)로
바뀌고 푸터는 edit-모드 키 힌트로 바뀐다. 비어 있지 않은 결과 목록에서
`Enter`는 선택된 세션을 재개한다; 매치 0개의 버퍼에서 `Enter`는 NORMAL로
돌아가며 사용자가 다시 입력하지 않고 다듬을 수 있도록 버퍼를 유지한다.

2단계 `Esc` 규칙: 비어 있지 않은 버퍼에서 첫 `Esc`는 버퍼를 지운다
(EDITING에 머무름); 빈 버퍼에서 두 번째 `Esc`는 EDITING을 종료한다
(NORMAL로 복귀). `Ctrl-C`는 여전히 `KeyboardInterrupt`를 발생시켜 외부의
`try/except`가 `termios`를 복원하고 깔끔하게 `None`을 반환할 수 있게 한다.

| 모드 | 키 | 효과 |
|---|---|---|
| NORMAL | `/` | EDITING 진입 (버퍼 그대로) |
| NORMAL | 인쇄 가능 `c` | 버퍼 = `c`로 EDITING 진입 |
| NORMAL | `q` / `Q` / `Esc` / `Ctrl-C` | 종료, `None` 반환 |
| NORMAL | `Enter` | 하이라이트된 세션 재개 |
| NORMAL | `j` / `k` / `↑` / `↓` | 커서 이동 |
| EDITING | 인쇄 가능 | 버퍼에 추가 (재-좁히기) |
| EDITING | `Backspace` / `DEL` (`\x7f` / `\b`) | 마지막 글자 제거 (빈 상태에서 no-op) |
| EDITING | `q` / `Q` / `/` | 글자로 그대로, 종료하지 않음 |
| EDITING | `Enter` (매치) | 하이라이트된 세션 재개 |
| EDITING | `Enter` (매치 0) | NORMAL로 떨어짐 (버퍼 유지) |
| EDITING | `Esc` | 버퍼 비어 있지 않으면: 버퍼 지움; 비어 있으면: EDITING 종료 |
| EDITING | `Ctrl-C` | 종료, `None` 반환 |
| EDITING | `j` / `k` / `↑` / `↓` | 필터된 뷰 내에서 커서 이동 |

라이브 검색은 `--filter` 위에 합성된다: `--filter feat-x`를 전달했다면
피커는 그 서브셋으로 열린 후 `/`가 추가로 좁힌다. 헤더의 `M`은 피커 열린
시점의 카운트(즉, post-CLI-filter 총합)이므로 `N / M matches` 비율은
라이브 검색이 뷰를 얼마나 좁혔는지를 반영한다.

## 왜 스킬과 함께 도구인가

스킬은 하네스(`AskUserQuestion` 렌더링용)를 필요로 한다; CLI는 TTY(피커
렌더링용)를 필요로 한다. 둘은 하나의 데이터 계층 —
`discover → aggregate → group → enrich → render` — 을 공유하며, 스킬의
`--json` 모드는 문자 그대로 CLI의 JSON 출력을 모델로 파이프한 것이다.
어느 쪽에도 LLM이 루프 안에 있지 않다; 둘 다 `/dev-kit:log` 트랜스크립트의
순수 소비자다.

이는 [`/dev-kit:token-analyzer`](token-efficiency.ko.md)와 같은 형태다:
스킬은 데이터를 Claude 대화 안에서 접근 가능하게 하고; CLI는 평범한
셸, `ssh`, CI에서 접근 가능하게 한다. CLI 형태는 진짜로 CLI-친화적
(`--list` / `--json`은 TTY 불필요; 피커는 옵트인)이므로 살아남는다.

## 관련

- `tools/session_monitor.py` — CLI 드라이버 (stdlib 전용).
- `tools/session_monitor_{alias,cli,format,picker,render,types}.py` —
  피커 / `--cli-setup` 설치기 / JSON 출력기; 임포트 사이클을 결정론적으로
  유지하기 위해 작은 모듈 집합으로 분리됨.
- `tools/skill_usage.py` — `--skill-usage` / `--skill-days`에 재사용되는
  스킬별 턴 + 호출 집계기.
- `/dev-kit:log` — 피커가 소비하는 트랜스크립트.
- [`/dev-kit:token-analyzer`](token-efficiency.ko.md) — 같은 로그에 대한
  사후 비용 대시보드.
