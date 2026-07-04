# ADR-0020 — Methodology Extensibility (TDD/SDD/DDD/BDD/FDD)

**Status**: Accepted

## Decision
Generalize Iron Law L1 to "no prod code without verification artifact". User picks the methodology. Adding a new methodology needs 1 adapter file + 1 doc + 1 test.

## Why generalize L1?
TDD uses a test artifact. SDD uses a contract artifact. DDD uses a domain test. BDD uses a Gherkin scenario. FDD uses a feature flag. Iron Law L1 generalizes to "prod code without any artifact".

## Adapter interface
```python
class Methodology(ABC):
    name: str  # "tdd" | "sdd" | ...
    def pre_check(self, worktree, step) -> Dict: ...
    def verification_command(self, worktree, step) -> List[str]: ...
    def cycle_steps(self) -> List[str]: ...
    def report_status(self, worktree, step) -> Dict: ...
```

## 5 defaults
- TDD: pytest / vitest. cycle: red, green, refactor.
- SDD: pact-contract. cycle: spec, impl, contract.
- DDD: domain-test. cycle: model, test, refine.
- BDD: behave/cucumber. cycle: given/when/then.
- FDD: feature-flag eval. cycle: plan/design/build.

## Selector
`lib/methodology.json` (active: "tdd" default). Change via `/dev-kit:config` picker.
