# 0001 - MCP 통합은 (의도적으로) 범위 밖이다

**언어:** [English](0001-no-mcp.md) · 한국어

**상태:** 채택 (2026-08-06)
**출처:** dev-harness-kit 슬림-스윕 리뷰 (PR-1)

## 맥락

이 플러그인은 `commands/`, `skills/`, `hooks/`, `lib/`, `tools/`, `agents/`
디렉터리를 가진다. `mcp/` 디렉터리나 어떤 MCP 서버 엔트리도 가지고 있지
않다.

`/dev-kit:config` 스킬은 "skill + MCP + hook + methodology picker"를
나열하지만 `skill`과 `methodology`만 배선되어 있다. 피커의 MCP 옵션은
동작하지 않는다.

## 결정

이 플러그인은 MCP 서버 엔트리를 출하하지 않는다. 이것은 보류가 아니라
의도적이다.

## 결과

- `/dev-kit:config`은 MCP 피커 옵션을 제거한다.
- 소비자 저장소 통합은 다음으로 제한된다: 슬래시 명령, 훅, 라이브러리
  함수.
- 미래 기여자는 이 결정의 명시적 재검토 없이 MCP 지원을 추가해서는
  안 된다.
- `PreCompletionChecklistMiddleware`, `cost-gate`, `token-analyzer`는
  계속 슬래시 명령 + 라이브러리 함수로 제공된다.

## 재검토 시점

- 소비자 저장소의 MCP 통합 요청이 3건 이상 들어올 때.
- 훅/스킬 번들을 가진 플러그인(단독 서버가 아닌)을 위한 MCP 스펙이
  안정될 때.
- 새로운 플러그인-차원의 표면(예: `commands/<x>.md` -> 외부 API 호출)이
  MCP-레벨 배선을 요구할 때.
