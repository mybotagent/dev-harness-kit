# ADR-0001 — 5 → 1 흡수

**Status**: Accepted

## 결정
외부 의존 0. 5개 repo를 완전히 흡수(코드/스킬/훅 그대로 이동, namespace만 변경). 옛 repo는 `DEPRECATED.md` 1줄 + archive 안내.

## 배경
- `pm-prd-fast/`, `interview-harness-skills/`, `dev-harness/`, `claude-review-plugins/`, `slop-shield/`
- 같은 워크플로우 단계 중복 → 5 plugin 동시 관리 부담.

## 근거
- dev-harness의 `install.sh --with-plugins`가 이미 외부 의존 0 회피 권장.
- absorption은 한 install로 모든 단계 활성화.

## 결과
- 옛 repo 코드 보존. `DEPRECATED.md` 1줄.
- namespace: kebab-case (ADR-0010).
