---
name: build-methodology
category: build
description: methodology router. TDD/SDD/DDD/BDD/FDD/custom selection (MUST-48). Auto-dispatched via lib/methodology/<name>.py.
when_to_use: |
  - User runs /dev-kit:config "methodology" question
  - Auto-invoked by build-engine per step
allowed-tools: Read Write Bash
disallowed-tools: WebFetch Agent
model: haiku
user-invocable: false
---

# build-methodology — Verification Artifact Router

## Iron Law
**L1 = "no prod code without verification artifact"** (artifact type varies by methodology).

## Adapter interface (`lib/methodology/abc.py`)

```python
class Methodology(ABC):
    name: str  # tdd | sdd | ddd | bdd | fdd | custom
    @abstractmethod
    def pre_check(self, worktree: Path, step: Dict) -> Dict: ...
    @abstractmethod
    def verification_command(self, worktree: Path, step: Dict) -> List[str]: ...
    @abstractmethod
    def cycle_steps(self) -> List[str]: ...
    @abstractmethod
    def report_status(self, worktree: Path, step: Dict) -> Dict: ...
```

## 5 Adapters (default-able)

| Methodology | Artifact | Verification | Cycle | Hook |
|---|---|---|---|---|
| **TDD** (default) | failing unit test | `pytest` / `vitest` | Red→Green→Refactor | `tdd-guard` |
| **SDD** | OpenAPI / proto spec | contract test (Pact) | Spec→Impl→Contract | `spec-guard` |
| **DDD** | Aggregate / Domain | domain test (ubiquitous lang) | Model→Test→Refine | `domain-guard` |
| **BDD** | Gherkin feature | step def + scenario | Given/When/Then | `bdd-guard` |
| **FDD** | Feature spec | feature flag / smoke | Plan→Design→Build | `feature-guard` |

## Selector

`/dev-kit:config` multiSelect "methodology" answer → `lib/methodology.json` auto-recorded.

## Hook integration

`.dev-kit/.active-hooks.json` stage-cell `tdd-guard` value:
- `true` (all hooks ON)
- `false` (all OFF, user opt-out)
- methodology adapter registers its own mapping

## Adding a new methodology

One file `lib/methodology/<name>.py` + one regression in `lib/test_methodology.py` (YAGNI). No ADR or migration required.