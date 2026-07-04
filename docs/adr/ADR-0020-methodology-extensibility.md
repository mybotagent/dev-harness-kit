# ADR-0020 — Methodology Extensibility (TDD/SDD/DDD/BDD/FDD)

**Status**: Accepted

## 결정
Iron Law L1 = "no prod code without verification artifact" 일반화. 사용자가 방법론 선택. adapter 1 파일 / doc 1개 / test 1개로 신규 방법론 추가.

## 왜 L1 일반화?
TDD는 test artifact. SDD는 contract artifact. DDD는 domain test. BDD는 Gherkin scenario. FDD는 feature flag. Iron Law L1은 "artifact 없는 prod code"로 일반화.

## Adapter 인터페이스
```python
class Methodology(ABC):
    name: str  # "tdd" | "sdd" | ...
    def pre_check(self, worktree, step) -> Dict: ...
    def verification_command(self, worktree, step) -> List[str]: ...
    def cycle_steps(self) -> List[str]: ...
    def report_status(self, worktree, step) -> Dict: ...
```

## 5 default
- TDD: pytest / vitest. cycle: red, green, refactor.
- SDD: pact-contract. cycle: spec, impl, contract.
- DDD: domain-test. cycle: model, test, refine.
- BDD: behave/cucumber. cycle: given/when/then.
- FDD: feature-flag eval. cycle: plan/design/build.

## Selector
`lib/methodology.json` (active: "tdd" default). `/dev-kit:config` picker 변경.
