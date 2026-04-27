---
description: "Stage 1 of 6: Architecture Review. Define scope, constraints, and acceptance criteria for a coding task."
agent: "AI Agent Architecture Reviewer"
model: "Claude Opus 4.6 (copilot)"
tools: ["read", "search", "todo"]
---

# Stage 1: Architecture Review

## Input

Provide a task description: bug fix, feature, or refactor.

## Work

1. Define objective (one sentence).
2. List in-scope files (exact paths, no wildcards).
3. List out-of-scope files with reasoning.
4. State constraints (non-negotiables, at least 3).
5. Write acceptance criteria (testable, at least 5).
6. List required tests (exact test function names, at least 5).
7. Identify risks (severity: LOW/MEDIUM/HIGH).
8. Challenge the scope: is this the smallest viable change?
9. Define naming expectations for new/changed symbols to keep intent obvious.

## Output Format

```
## HANDOFF v1

Task ID: task-{issue}-{timestamp}

Objective: [one sentence]

In-Scope Files:
- [exact path]
- [exact path]

Out-of-Scope Files:
- [exact path]: [reasoning]

Constraints:
1. [constraint]
2. [constraint]
3. [constraint]

Acceptance Criteria:
1. [testable criterion]
2. [testable criterion]
3. [testable criterion]
4. [testable criterion]
5. [testable criterion]

Required Tests:
1. test_name_1
2. test_name_2
3. test_name_3
4. test_name_4
5. test_name_5

Risks:
- [description] → SEVERITY (LOW/MEDIUM/HIGH)
- [description] → SEVERITY

Artifacts for Next Agent:
(leave blank)

Open Questions:
(list any clarifications needed)

---

## GATE STATUS: 🟢 GREEN / 🟡 YELLOW / 🔴 RED
```

## Gate Criteria

- [ ] Contract is complete (all fields present)
- [ ] Scope is minimal (no over-engineering)
- [ ] Acceptance criteria are testable
- [ ] Required tests cover all criteria
- [ ] Constraints are non-negotiable
- [ ] Naming expectations for new/changed symbols are explicit
- [ ] Maintainability risk is acceptable for the proposed scope

**Return GREEN if all pass. Return YELLOW if scope is sound but minor open questions remain (log them). Return RED if scope is too broad or acceptance criteria are vague.**

## Gate Rules

- **GREEN**: Proceed to next stage (Stage 2 on full path, Stage 3 on fast path).
- **YELLOW**: Proceed to next stage, but log findings in the handoff.
- **RED**: Do not proceed. Report blocking issues.

## Next

When run via the automated dispatcher, the handoff is passed automatically.
For standalone use, copy this handoff into the next stage prompt.
