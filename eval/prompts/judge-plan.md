# Eval: Plan Dimension (judge-plan, v2.0.0)

You are judging the agent's `/dev-kit:plan` output for one case fixture.
Score 4 axes 0-10 each.

## Case

- **Case ID**: ${CASE_ID}
- **Dimension**: ${DIM}
- **Category**: ${CATEGORY} (`clear-spec` | `ambiguous-spec` | `coupled-spec`)
- **Input** (the idea + AC + non-goals the planner was given):
```
${INPUT}
```
- **Agent output** (the PRD.md + phases/<name>/index.json + step<N>.md):
```
${AGENT_OUTPUT}
```
- **Expected behavior** (the ground-truth phase decomposition):
```
${EXPECTED}
```

## Axes (0-10)

1. **spec_clarity** — does the emitted PRD reduce ambiguity to <= 3
   per step (per the plan skill's Gate 2/4 rule)? 10 = every step has
   explicit, measurable AC and no vague language; 0 = raw 1-line idea
   is restated as a step with no decomposition.
2. **step_atomicity** — is each step a single shippable deliverable
   (no compound tasks like "build the API and the UI and the tests")?
   10 = every step is one deliverable; 0 = one mega-step does
   everything.
3. **ac_executability** — for each step's AC, is the command in a
   fenced ```bash block that would exit 0 on success? 10 = every AC
   is a runnable shell command with quoted exit code expected; 0 = AC
   is prose-only.
4. **dependency_ordering** — are the steps in dependency-first order
   (data model before API before UI; no forward references between
   steps)? 10 = strictly layered; 0 = random order with circular
   deps.

## Output Format

ONLY a JSON object (no prose). 4 axes, each 0-10:

```json
{"spec_clarity":N,"step_atomicity":N,"ac_executability":N,"dependency_ordering":N}
```
