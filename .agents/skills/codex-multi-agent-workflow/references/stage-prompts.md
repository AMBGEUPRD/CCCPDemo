# Stage Prompts

Use these prompts as reusable stage contracts. They are written for Codex's tool model,
not Claude's `runSubagent` model.

## Kickoff prompt

```text
Use the repo-local skill at .agents/skills/codex-multi-agent-workflow.
Run the Codex workflow for this task.

Task:
<paste task>

Expectations:
- decide fast vs full path
- maintain a findings ledger for CRITICAL/HIGH/MEDIUM issues
- keep edits in-scope
- run target tests, then the regression suite
- finish with a merge-gate verdict
```

## Stage 1 prompt

```text
Act as the Architecture Reviewer for this repo.

Produce:
- Objective
- In-Scope Files
- Out-of-Scope Files with reasons
- Constraints
- Acceptance Criteria
- Required Tests
- Risks
- Path Selection: fast or full
- Gate Status: GREEN, YELLOW, or RED

Use the smallest viable scope. If the task is ambiguous, ask one focused question
instead of guessing.
```

## Stage 2 prompt

```text
Act as the Design Reviewer.

Review the Stage 1 contract before coding.
Challenge:
- algorithmic soundness
- async and error-handling strategy
- naming clarity
- test coverage against acceptance criteria
- unnecessary complexity

Report CRITICAL, HIGH, and MEDIUM findings. Mark each finding as Task or Pre-existing.
Return Gate Status: GREEN, YELLOW, or RED.
```

## Stage 3 prompt

```text
Act as the Implementer.

Requirements:
- edit only in-scope files
- resolve all OPEN CRITICAL/HIGH findings
- add or update tests for each acceptance criterion
- run the target test first
- run the regression suite after the target test is green

Return:
- Files Modified
- Test Results
- Acceptance Criteria Mapping
- Findings Resolved
- Unresolved Findings
- Gate Status
```

## Stage 4 prompt

```text
Act as QA Verifier.

For each acceptance criterion:
- name the test that covers it
- state PASS or FAIL
- note any unverified risk

Also:
- report CRITICAL/HIGH/MEDIUM findings
- verify whether previously resolved findings are actually fixed
- re-open any finding still present

Return an evidence matrix and Gate Status.
```

## Stage 5 prompt

```text
Act as the Code Reviewer.

Review the written code, not the plan.
Focus on:
- correctness
- maintainability
- naming
- async safety
- error handling
- logging quality
- test readability

Report CRITICAL/HIGH/MEDIUM findings and verify the ledger state.
Return Gate Status.
```

## Stage 6 prompt

```text
Act as the Merge Gate.

Inspect the actual git diff and confirm:
- only in-scope files changed
- targeted tests passed
- no OPEN CRITICAL/HIGH findings remain
- no temporary files remain
- the diff does not introduce avoidable complexity

Return:
- Diff Summary
- Regression Risk
- Findings Ledger Status
- Recommendation: APPROVED, APPROVED_WITH_NOTES, or BLOCKED
```

## Claude-to-Codex role map

| Claude role | Codex role |
|---|---|
| AI Agent Architecture Reviewer | Stage 1 Architecture Reviewer |
| Python Solution Reviewer (pre) | Stage 2 Design Reviewer |
| BITransposerDev | Stage 3 Implementer |
| QA | Stage 4 QA Verifier |
| Python Solution Reviewer (post) | Stage 5 Code Reviewer |
| Uncommitted Code Reviewer | Stage 6 Merge Gate |

## Practical note

In Codex, these roles are primarily prompt lenses. Spawn subagents only when the user
explicitly asks for delegated or parallel execution.
