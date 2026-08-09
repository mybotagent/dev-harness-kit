# 훅 커버리지 갭 -- P4 버킷 B 감사

**언어:** [English](hook-coverage-gaps.md) · 한국어

> 이슈 #264(버킷 B 투자)의 일부로 생성됨. 이 문서는 부모 스레드의 최근
> 커밋 #259(프로바이더 소스 -- vars.CI_REVIEW_PROVIDER)와 #265(프로바이더
> 싱크 -- .env:CI_REVIEW_PROVIDER)에 대한 의도적 대응물이다. 아래 갭 #8은
> 그것들의 변경에 비추어 재진술; 나머지 매트릭스는 변경되지 않는다.
>
> 각 행은 실제 시나리오를 오늘 그것을 게이트하는 훅에 매핑한다. 오른쪽
> 끝 열은 갭을 표시; 하단의 요약은 이 PR에서 닫을 상위 3개를 선택한다.

심각도 척도(severity = 규칙이 잘못 발화되거나 발화되지 못할 때의 잔여
영향 반경):

- **HIGH** -- 사용자가 깨진 PR을 출하하거나 데이터를 잃거나 계약을 우회.
- **MEDIUM** -- 우회책이 존재하지만 훅이 잡았어야 함.
- **LOW** -- QoL 수정; 규칙은 이미 다른 곳에 백스톱이 있음.

## 시나리오 x 훅

| # | 시나리오 | 기존 훅 | 갭 | 심각도 | 제안 수정 |
|---|----------|---------|-----|--------|-----------|
| 1 | 사용자가 메인 체크아웃에서 새 작업 시작 (Claude) | worktree-guard.sh (hard block) | ACP M-tier (PR-2)로 해결됨 | -- | -- |
| 2 | 사용자가 메인 체크아웃에서 새 작업 시작 (Codex) | 같은 훅, .codex-plugin/hooks/hooks.json를 통해 라우트 | 부분적 -- #4 참고 | MEDIUM | 패리티 배선, 아래 참고 |
| 3 | 메인 체크아웃에서 Edit/Write | worktree-guard.sh | 없음 | -- | -- |
| 4 | 비-메인 브랜치 커밋 + 푸시 | git-guard.sh + review-yml-isolation.sh (Claude만) | **Codex 런타임에 누락** -- .codex-plugin/hooks/hooks.json는 review-yml-isolation.sh를 등록하지 않으므로, Codex 서브에이전트는 review.yml + 무관한 편집을 같은 커밋에 착륙시킬 수 있다. CI 게이트 판정이 읽을 수 없게 됨. | **HIGH** | review-yml-isolation.sh 항목을 .codex-plugin/hooks/hooks.json(PreToolUse::Bash)에 미러. 단일-항목 추가. |
| 5 | 피처 브랜치에 force-push | bash-guard.sh (advisory) + git-guard.sh (-f / --force 항상 켜짐) | 부분적 -- 사양에 따라 force-with-lease 허용 | -- | -- |
| 6 | 메인 체크아웃에서 SessionStart | session-start-check.sh | 없음 | -- | -- |
| 7 | dev-kit 훅 없는 새 워크트리에서 SessionStart | log-on-session-start.sh | 없음 | -- | -- |
| 8 | 사용자 .env:CI_REVIEW_PROVIDER가 허용 목록 밖이거나 .env.example 기본값과 발산 | 없음 | **누락** -- bin/set-provider.sh는 허용 목록 외 쓰기를 거부(T4)하지만 `CI_REVIEW_PROVIDER=openai`로 수동 편집된 .env는 조용히 통과. CI 리뷰 워크플로가 잘못된/없는 프로바이더로 디스패치. 동반 갭: 로컬 값이 .env.example(저장소-차원 기본값을 문서화하는 추적된 템플릿)에서 발산할 때 세션별 알림이 없음. | MEDIUM | 새 SessionStart 훅 hooks/provider-divergence-check.sh가 (a) .env CI_REVIEW_PROVIDER가 허용 목록 외이거나 (b) 허용 목록이지만 .env.example과 다를 때 additionalContext를 방출. 변형 없음, 커밋 없음. (원본 갭 타겟은 이제 삭제된 .github/ci-review-provider.txt를 참조; 이 행은 #265 이후 계약을 위해 재진술.) |
| 9 | Write가 자격 증명 패턴 포함 | secret-scan.sh (PostToolUse, advisory) | 없음 (의도적) | -- | -- |
| 10 | Write가 LLM-tell 포함 | slop-detector.sh (PostToolUse, advisory) | 없음 (의도적) | -- | -- |
| 11 | Stale babysit.lock이 디스크에 있는 동안 babysit-pr 루프 실행 | TTL/PID를 확인하는 것이 없음 | **누락** -- SKILL.md lock-file 프로토콜은 `[ -f .dev-kit/babysit.lock ]`만 확인. SIGKILL / OOM / 네트워크 분할은 잠금을 영원히 남기고 모든 미래 babysit-pr이 "already running"으로 1을 반환하며 종료. | MEDIUM | lib/babysit_pr_reliability.py::is_stale_lock(path, ttl_seconds=1800) 출하. SKILL.md 복구 텍스트가 헬퍼를 참조. |
| 12 | Babysit-pr이 유령 워크플로 검사(서버-사이드 워크플로 삭제, 검사가 null/pending으로 남음)에서 영원히 대기 | 유령을 분류하는 것이 없음 | **누락** -- gh pr checks는 기저 워크플로가 제거된 후 한참 뒤까지 conclusion=null + state=pending으로 검사를 반환. babysit-pr 대기 루프(Algorithm step 4)는 MAX_ITERS까지 sleep하고 재시도 -- 조기 종료 없는 순수한 busy-loop. | MEDIUM | lib/babysit_pr_reliability.py::classify_check(check, now_epoch) 출하, 임계값을 넘어 pending이거나 databaseId가 없는 경우(github의 정리 신호) "ghost"를 반환. SKILL.md가 분류 + 복구 경로를 설명. |
| 13 | 종료 코드가 없는 Stop-hook 완료 주장 | stop-verify.sh | 없음 | -- | -- |
| 14 | git worktree add가 자동 컷하지만 새 트리에 tools/save_log.py 없음 | worktree-log-auto-install.sh | 없음 | -- | -- |

## 이 PR에서 닫을 상위 3개

### 1. #4 -- Codex 런타임에 Review.yml 격리 누락.

실제 듀얼-런타임 홀: review.yml 편집이 커밋-전용이어야 한다는 규칙은
두 클라이언트 모두 같은 git 트리를 읽기 때문에 둘 다에서 시행 가능하지만,
훅은 Claude에만 배선되어 있다. 실패한 review.yml 테스트를 고치는
Codex babysit-pr 실행은 무관한 편집을 조용히 번들한다.

**수정**: 항목을 .codex-plugin/hooks/hooks.json에 미러. 훅 스크립트
(hooks/review-yml-isolation.sh)는 이미 존재; 배선만 누락. 회귀 테스트
확장은 tests/test_hooks_status.py에 -- 기존
test_codex_manifest_registers_shared_hook_definition는 이제 Codex
PreToolUse::Bash 인벤토리가 review-yml-isolation.sh를 포함한다고 단언.

### 2. #8 -- .env 프로바이더 비허용 / 발산에 표면 없음.

현재 허용 목록은 set-provider.sh 쓰기 경로(T4 test_set_provider.py)에서
시행된다. 하지만 (a) .env의 수동 편집(또는 오래된 .env.example에서의
복사)은 아무도 알아차리지 못한 채 비허용 값을 거기에 둘 수 있고, CI가
실패할 때까지 드러나지 않으며, (b) 추적된 템플릿
.env.example:CI_REVIEW_PROVIDER은 저장소 기본값을 문서화하지만 로컬 값이
그것에서 발산할 때 운영자에게 알리는 훅이 없다. 둘 다 오늘의 조용한
실패 경로다.

**수정**: 새 SessionStart 훅 hooks/provider-divergence-check.sh가
(i) bin/set-provider.sh와 같은 파서로 .env와 .env.example을 읽고,
(ii) 로컬 값을 허용 목록에 대해 검증하며, (iii) .env.example 기본값과
비교. 어느 쪽이든 불일치는 SessionStart additionalContext를 방출 -- 어느
파일도 변형하지 않는다. 회귀 테스트:
tests/test_provider_divergence_hook.py(훅 전 실패, 후 통과)와
tests/test_provider_divergence_wiring.py(훅이 .claude-plugin/hooks/hooks.json
와 .codex-plugin/hooks/hooks.json 둘 다에 등록됨을 단언, 위 #1에서
review-yml-isolation에 대해 시행되는 듀얼-런타임 계약).

### 3. #11/#12 -- Babysit-pr stale-lock + 유령-워크플로 분류.

하나의 헬퍼 모듈(lib/babysit_pr_reliability.py)에서의 두 신뢰성 갭.
SKILL.md가 명시적 복구 텍스트를 얻고 헬퍼를 참조.

**수정**: 순수 함수 헬퍼, 결정론적, I/O 시각 무작위성 없음(테스트가
재현 가능하도록 호출자가 `now_epoch`를 전달):

- is_stale_lock(path, ttl_seconds=1800) -> bool
  mtime이 TTL보다 오래됐거나 파싱된 pid= 필드가 더 이상 실행 중인
  프로세스를 가리키지 않을 때(Linux /proc 스캔; macOS kill(0) 프로브)
  True.

- classify_check(check_dict, now_epoch, ghost_threshold_seconds=300) -> str
  {approved, failing, pending, ghost} 중 하나를 반환. 결론이 None이고
  databaseId가 없거나 검사의 startedAt/updatedAt가 임계값보다 오래된
  경우 Ghost.

회귀: 두 헬퍼를 위한 합성 입력으로
tests/test_babysit_pr_reliability.py. 헬퍼 출하 전 실패(ImportError);
출하 후 통과.

## 이 PR 범위 밖 (연기)

- 보호된 브랜치 규칙셋을 통한 review.yml 격리의 서버-사이드 시행
  (운영 관심사, 저장소 Settings에 산다).
- Slop / secret strict-모드 UX (별도 워크스트림; 두 훅은 오늘 의도적으로
  advisory).
- 소유하지 않은 브랜치에 대한 force-push 훅 (횡단; 별도 보안 감사
  워크스트림).
- .env에 CI_REVIEW_PROVIDER가 전혀 없을 때의 세션별 알림 -- 첫 클론에
  시끄러움; 설정 힌트로 연기.
