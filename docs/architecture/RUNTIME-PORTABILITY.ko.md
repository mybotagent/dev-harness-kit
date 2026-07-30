# Runtime Portability (런타임 이식성)

**언어:** [English](RUNTIME-PORTABILITY.md) · 한국어

이 문서는 `lib/runtime_adapters/`의 모든 공개 API를 **중립성**
기준으로 분류한 정식 자료다: 계약의 어떤 부분이 Claude Code와 Codex
전반에 걸쳐 동일하고, 어떤 부분에 어댑터 shim이 필요한지 나타낸다.
Phase 0.9 산출물(issue #345)이며 "X는 이식 가능한가?"에 대한 단일
진실 공급원이다 — 이후의 모든 단계는 이 매트릭스를 참조한다.

## 요약

```python
from runtime_adapters import (
    RuntimeAdapter,        # Protocol — 중립 표면
    TokenLog,              # 중립 dataclass
    SessionEvent,          # 중립 dataclass
    ClaudeCodeAdapter,     # Claude Code 구현체
    CodexAdapter,          # Codex 구현체
)
```

`runtime_adapters` 패키지에서만 임포트하고 `RuntimeAdapter` Protocol을
통해 동작하는 코드는 구조적으로 이식 가능하다. `ClaudeCodeAdapter` /
`CodexAdapter`를 직접 임포트하는 코드는 의도적으로 한 런타임에
고정된 것이다 — 이는 허용되지만(예: `/dev-kit:runtime` 스킬),
호출부는 `adapter.is_current()`를 통해 명시적으로 선택해야 한다.

## 중립성 매트릭스

| API | 중립? | 두 어댑터가 구현하는 방식 |
|---|:---:|---|
| `name()` | ✅ | 안정적인 런타임 ID 문자열(`"claude-code"` / `"codex"`)을 반환한다. 이식성 이슈 없음. |
| `is_current()` | ❌ | 런타임별 환경 신호 + 바이너리 프로브. **이식 불가능** — 의도된 설계다. Protocol이 존재하는 이유가 바로 각 런타임이 자기만의 감지 방식을 갖기 때문이다. |
| `read_token_log(window)` | ✅ | 두 어댑터 모두 같은 5개 필드를 가진 `TokenLog` dataclass를 반환한다. 필드 의미는 정규화되어 있다: Codex의 `cached_input_tokens`는 `input_tokens`에서 빼져서 `input_tokens`가 "새로 발생한, 캐시되지 않은" 것을 의미하게 된다. |
| `read_session_events(session_id)` | ✅ | 두 어댑터 모두 `list[SessionEvent]`를 반환한다. 이벤트 이름은 **런타임 고유**이며 중립적이지 않다(Claude는 `PreToolUse`를, Codex는 `before_tool_use`를 발생시킨다); 매핑은 `hook_event_name()`을 참고. |
| `hook_event_name(neutral_name)` | ⚠️ | Claude는 항등 매핑이다(Claude 훅 이름이 곧 중립 집합이다). Codex는 정식 중립 집합을 자신의 이벤트 이름으로 매핑하고, 알 수 없는 이름은 그대로 통과시킨다. **중립 집합이 계약이며**, 런타임 고유 이름은 구현 세부사항이다. |
| `prompt_user(question)` | ✅ | 두 어댑터 모두 주입된 콜백에 위임한다. 연결되지 않았을 때 같은 `RuntimeError`("prompt callback is not configured")를 낸다. |
| `workspace_root()` | ✅ | 둘 다 같은 우선순위 체인으로 해석한다: 명시적 `project_root` 인자 > 런타임 환경 신호(`CLAUDE_PROJECT_DIR` / `CODEX_PROJECT_DIR`) > `Path.cwd()`. |
| `install_skill(name, dir)` | ✅ | 둘 다 주입된 설치 콜백에 위임한다. 연결되지 않았을 때 같은 `RuntimeError`. |

## "중립적"이 실제로 의미하는 것

중립 API는 동일한 입력에 대해 어댑터 전반에서 **바이트 단위로 동일한
관측 가능 동작**을 갖는다. 구체적으로:

```python
# 동일한 빈 workspace_root에 대해 두 어댑터 모두 동일한 TokenLog를
# 반환한다("파일 없음" 케이스가 정식 중립 예시다 — 
# test_both_adapters_return_same_shape_on_empty_input 참고).
claude = ClaudeCodeAdapter(project_root=tmp).read_token_log("7d")
codex  = CodexAdapter(project_root=tmp).read_token_log("7d")
assert type(claude) is type(codex)            # TokenLog == TokenLog
assert claude.input_tokens == codex.input_tokens  # 0 == 0
```

이것이 Phase 1+ 코드가 의존하는 **런타임 간 동등성 보장**이다. 미래의
세 번째 어댑터(자신의 토큰 로그를 `TokenLog`로 정규화할 수 있는 어떤
런타임이든)는 Phase 1+ 코드를 건드리지 않고 그대로 끼워넣을 수 있다.

## "중립적이지 않다"가 실제로 의미하는 것

`is_current()`는 명시적으로 이식 불가능한 유일한 메서드다: 각
런타임이 자신만의 자기 감지 방식을 갖기 때문에 정확히 그렇게
설계됐다. 이것이 옳은 결정인 두 가지 이유:

1. **호출자는 가정하지 않고 물어봐야 한다.** "지금 사용자가 실제로
   Claude Code를 실행 중인가?"를 알고 싶은 코드는 런타임 고유 신호를
   읽어야 한다. 중립적인 답은 없다.
2. **런타임 이식성 보장은 정규화된 출력에 관한 것이지, 감지에 관한
   것이 아니다.** Phase 1+ 코드는 Protocol을 통해 정규화된 데이터를
   읽으며, 런타임 자체를 감지하지 않는다(해서도 안 된다).

`hook_event_name()`은 *부분적으로만* 중립적인 유일한 메서드다: **중립
집합**(고정된 정식 이벤트 이름 목록)이 계약이지만, **구현**은
런타임별이다. Codex는 알 수 없는 중립 이름을 그대로 통과시키므로
미래의 중립 이벤트가 Codex에서 자동으로 동작하게 된다; 대가는 아직
중립 집합에 없는 Codex 고유 이벤트가 Claude Code 호출자에게는 보이지
않는다는 것이다.

## 흔한 패턴

### 패턴 1: "현재 어댑터를 달라"

```python
from runtime_adapters import ClaudeCodeAdapter, CodexAdapter

def current_adapter():
    for cls in (ClaudeCodeAdapter, CodexAdapter):
        if cls().is_current():
            return cls()
    raise RuntimeError("No supported runtime detected")
```

이곳이 코드베이스에서 `is_current()`를 검사해도 되는 유일한 곳이다.
다운스트림 코드는 그 결과 어댑터를 받으며 다시는 묻지 않는다.

### 패턴 2: "정규화된 토큰 사용량 읽기"

```python
from runtime_adapters import TokenLog

def last_24h_tokens(adapter) -> TokenLog:
    return adapter.read_token_log("24h")
```

이식 가능하다. 동일한 입력 → 런타임 전반에서 동일한 출력.

### 패턴 3: "중립 훅 이벤트를 런타임 고유 이름으로 매핑"

```python
def emit(adapter, neutral_name: str) -> None:
    native = adapter.hook_event_name(neutral_name)
    # `native`는 이 런타임의 훅 프로토콜이 기대하는 값이다.
```

이식 가능하다 — 중립 이름이 API이고, 런타임 고유 이름은 구현이다.

## CI 시행

`.github/workflows/test-portability.yml`은 `tests/test_portability.py`를
두 런타임의 환경 신호(매트릭스 runtime = `[claude-code, codex]`)로
실행한다. 어느 쪽 어댑터에서든 런타임 간 동등성 보장을 깨는 회귀는
그것을 검사하는 레인에서 CI를 실패시킨다.

전체 28개 테스트 계약은 `tests/test_portability.py`를,
구현체는 `lib/runtime_adapters/`를 참고한다.

## 관련

- `lib/runtime_adapters/base.py` — `RuntimeAdapter` Protocol + 데이터 클래스.
- `lib/runtime_adapters/claude_code.py` — Claude Code 어댑터.
- `lib/runtime_adapters/codex.py` — Codex 어댑터.
- `tests/test_portability.py` — 28개 테스트 계약 스위트.
- `.github/workflows/test-portability.yml` — CI 매트릭스.
- Issue #329 — Phase 0 상위 이슈.
- Issue #343 — `__init__.py` 익스포트.
- Issue #344 — `tests/test_portability.py`.
- Issue #345 — CI 매트릭스 + 이 문서.
