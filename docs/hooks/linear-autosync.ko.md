# `linear-autosync.sh`

**언어:** [English](linear-autosync.md) · 한국어

> `Edit` / `Write` / `MultiEdit`에 대한 PreToolUse 훅. 모든 Claude Code
> 편집을 수동 `/dev-kit:linear` 호출 없이 사용자의 Linear 워크스페이스에
> 반영하도록 `tools/linear_sync.py`를 발화한다.

## 무엇을 하는가

훅은 얇은 셸 래퍼다. 이 행동을 한다:

1. Claude Code가 모든 Edit/Write/MultiEdit에서 보내는 JSON 페이로드에서
   `cwd`를 끌어온다. 페이로드가 그 필드를 생략하면 `$CLAUDE_PROJECT_DIR`
   또는 `pwd`로 폴백.
2. **프로젝트 디렉터리로 `cd`**하여 Python 스크립트가 상대 경로로 자체
   `tools/linear_sync.py`를 찾을 수 있게 한다.
3. **PROJECT_DIR 가드** (2026-08-06 추가, PR #590): `$PROJECT_DIR/tools/
   linear_sync.py`가 존재하지 않으면 0으로 조용히 종료. 이것은
   크로스-프로젝트 플러그인-공유 경우다 — `tools/` 없이 `hooks/linear-autosync.sh`
   만 클론하는 다른 Claude Code 프로젝트는 그렇지 않으면 모든 Edit에서
   "No such file or directory"를 출력했을 것이다. silent-bail은
   non-blocking 계약을 보존.
4. **Env fast-path**: 활성 소스가 없으면(LINEAR_API_KEY env var 없음,
   user-scope `~/.config/dev-kit/.env` 없음, 워크트리별
   `.dev-kit/.env.linear` 또는 `linear-config.json` 없음, 레거시
   `.dev-kit/.enabled.json` 없음) Python을 포크하지 않고 0으로 종료.
   이것은 저비용 경로다 — 가장 흔한 경우(Linear가 설정되지 않음)에 대한
   단일 bash 조건 검사.
5. **Python fork**: 활성 소스가 설정되어 있으면 `$PATH`의 첫 번째
   `python3` / `python` / `py`를 통해 `tools/linear_sync.py` 실행.
   Python 스크립트가 권위 있는 게이트(설정 검증, GraphQL 호출, 핸드오프
   쓰기); 셸 래퍼는 fast-path만 제공.

훅은 항상 0으로 종료한다. 전송 실패, 누락된 토큰, GraphQL 오류, 그리고
Python 스크립트 안의 다른 모든 문제는 stderr에 보고되지만(`LINEAR_DEBUG=1`
하에서 보임) Edit을 절대 차단하지 않는다. 이것은 부모
[SKILL.md](../../skills/linear/SKILL.md)와 이슈 스레드(#539)에 문서화된
non-blocking 계약이다.

## 교차 참조

- [skills/linear/SKILL.md](../../skills/linear/SKILL.md) — 명시적 호출을
  위해 같은 Python 스크립트를 래핑하는 사용자-대면 스킬
  (`/dev-kit:linear on`, `/dev-kit:linear list` 등).
- [docs/skills/linear.md](../skills/linear.md) — linear 스킬의 공개 docs
  페이지.
- [tools/linear_sync.py](../../tools/linear_sync.py) — Python 구현(훅은
  호출만 함; 모든 행동은 여기에 산다).
- [HOOK-REFERENCE.ko.md](./HOOK-REFERENCE.ko.md) — 훅 인덱스.
