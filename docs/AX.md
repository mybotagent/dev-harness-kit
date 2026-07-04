# AX — 개인 10x / 팀 100x AX 가이드 (ADR-0006, 0007, 0019)

## 3축 통합 (MUST-45~47)

### A) AI-native (MUST-45)
- 모든 인터페이스 AI-readable 우선 (typed JSON, YAML frontmatter)
- 사람 doc 위주 ❌. 자동 합성 + AI read-first.
- 사용자 = 결과만 review.

### B) Team-share (MUST-46, --team mode)
- `--team` 시 `.dev-kit/` git include.
- 자동 PR bot 첨부 (`/dev-kit:build` 종료 시 hand-off 발췌).
- Attribution via `.dev-kit/loop-log.json` + `a2a_log.jsonl`.

### C) Easy-onboard (MUST-47)
- `/dev-kit:onboard <github_username>` 0-arg.
- 30분 productive 목표 (CLAUDE.md 자동 + codebase-map + first task 위임 + PR 자동).

## 모드 비교

| 모드 | 트리거 | 효과 |
|---|---|---|
| **10x** (default) | `--team` 안 줌 | local only. .gitignore에 `.dev-kit/`. |
| **100x** | `--team` | git include. PR bot. attribution. |

## 사용자 4 역할 ONLY (MUST-35)
1. 기획 (goal + AC + non-goals)
2. 스펙 (PRD.md)
3. 판단 (gate + cost + approve)
4. 리뷰 (PR + Eval-Repair)

❌ 단계 쪼개기, ❌ cost 질문 작성, ❌ commit (PR 단위만), ❌ hook + CI 관리.
