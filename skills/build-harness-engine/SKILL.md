---
name: build-harness-engine
category: design
description: phase step file generation. Synthesizes plan-skill 6-step output into phases/<name>/{index.json, step<N>.md}. Dispatched by plan.
version: 0.1.0
when_to_use: |
  - Auto-invoked by plan after gate-pass
  - User triggers manual regeneration via `@dev-kit:plan`
allowed-tools: Read Write
disallowed-tools: Bash WebFetch Agent
model: sonnet
user-invocable: false
---

# build-harness-engine — Phase Decomposition (Plan+Design subgraph)

## Core Goal
Take PRD.md + non-goals and auto-generate `phases/<name>/{index.json, step<N>.md}`.

## Output

```
phases/<phase-alias>/
├── index.json          # step state machine
├── step0.md            # Phase 1 step (e.g., setup)
├── step1.md
└── stepN-output.json   # after execution
```

Each step file format:

```markdown
# Step N: <title>

## Must-read
- docs/ARCHITECTURE.md §<N>
- ../../CLAUDE.md §<N>

## Instruction (signature-level)
function createX(input: Type) -> Result
function validateX(input: Type) -> Result

## Acceptance Criteria (runnable)
\`\`\`bash
npm test -- --testNamePattern="createX"
\`\`\`
expected exit code 0, count 5+

## Don't do X because Y
- ❌ Don't use mock — production behavior required
- ❌ Don't skip tests — Iron Law L1
```

## Rules

- One step = one layer / one module (harness-runner's step is a separate cycle)
- must-read / AC / Don't do X because Y are mandatory 3 sections
- Function signature-level instruction (no body)

## Hook integration

Only `stop-verify=ON`. Others OFF (same as Plan stage).