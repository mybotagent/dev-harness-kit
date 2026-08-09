# 이식성 및 장기 실행 루프 계약

**언어:** [English](PORTABILITY-AND-LOOP.md) · 한국어

라이브 계약은 의도적으로 작다:

```text
python3 tools/portability_check.py --json
python3 tools/loop_engine.py iterate --feature-list feature_list.json
python3 tools/loop_engine.py verify --feature-list feature_list.json
```

`portability_check.py`는 읽기 전용이다. Claude와 Codex 매니페스트 정체성을
비교하고, 그들의 plugin-루트 변수를 정규화하고, 모든 훅 이벤트/matcher/
명령을 비교하고, 모든 최상위 셸 훅을 `bash -n`으로 파싱한다. exit `0`은
이식성 계약이 유지됨을 의미; exit `1`은 실행 가능한 finding을 포함한다.

`loop_engine.py iterate`는 사전적으로 첫 번째 적격 `failing` feature를
결정론적으로 선택하고, 그것의 선언된 `test_path`를 실행하며, `.dev-kit/
loop-checkpoint.json`을 원자적으로 쓴다. 실패한 테스트도 여전히
기록된다. feature 목록은 조용히 바뀌지 않는다: 사람 또는 명시적 증거가
있는 에이전트만이 feature를 `passing`으로 표시할 수 있다. 이것은
초록 명령이 거짓 완료 주장이 되는 것을 방지한다.

체크포인트는 콜드-컨텍스트 핸드오프이다: 반복 번호, feature id, 정확한
명령, exit 코드, 한정된 출력 꼬리를 포함한다. 재실행은 안전하며 같은
feature의 상태가 의도적으로 업데이트될 때까지 같은 feature에서 계속한다.
`ci-setup`이 두 도구를 소비자에게 출하하므로, 루프는 plugin 체크아웃
경로나 Claude-특화 환경변수에 의존하지 않는다.

이전 `RUNTIME-PORTABILITY.md`는 삭제된 어댑터 실험을 설명하며 히스토리로
보존; 현재 런타임 계약이 아니다.
