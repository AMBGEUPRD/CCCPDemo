---
description: "Stage 1 of 5: Solution Architect — define scope, acceptance criteria, risks, and the TDD test contract (Given/When/Then specs for every required test)."
---

# Stage 1: Architecture Review — Solution Architect

## Input

Provide a task description: bug fix, feature, or refactor.

## Reasoning Mode

Adapt behavior to the `reasoning_level` in the task card:

**LOW** — fast path: read only focus_files, trust BA scope signals, produce concise output.

**MEDIUM** — standard path: full scope analysis, all checks, complete output.

**HIGH** — exhaustive path: re-read all relevant files, challenge assumptions, maximum scrutiny on risks.

## Work

1. Define objective (one sentence).
2. List in-scope files (exact paths, no wildcards).
3. List out-of-scope files with reasoning.
4. State constraints (non-negotiables, at least 3).
5. Write acceptance criteria (testable, at least 5).
6. List required tests — this is the TDD test contract for Stage 3a (Red Phase).
   For each required test provide:
   - Exact function name (e.g. `test_chunked_two_batches`)
   - One-line Given/When/Then docstring:
     `"Given [input/state], when [action], then [expected outcome]"`
   - Example: `test_chunked_two_batches` — `"Given func_doc exceeds token limit,
     when call1 runs, then output contains all tables split across two batch responses"`
   Minimum 5 required tests. Cover happy path, error path, and boundary conditions
   for each acceptance criterion — not just the sunny-day scenario.
7. Identify risks (severity: LOW/MEDIUM/HIGH).
8. Challenge the scope: is this the smallest viable change?
9. Define naming expectations for new/changed symbols to keep intent obvious.

## Output Format

```markdown
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

Required Tests (TDD contract — Given/When/Then spec for each):
1. test_name_1 — "Given [state], when [action], then [expected outcome]"
2. test_name_2 — "Given [state], when [action], then [expected outcome]"
3. test_name_3 — "Given [state], when [action], then [expected outcome]"
4. test_name_4 — "Given [state], when [action], then [expected outcome]"
5. test_name_5 — "Given [state], when [action], then [expected outcome]"

Risks:
- [description] â†’ SEVERITY (LOW/MEDIUM/HIGH)
- [description] â†’ SEVERITY

Artifacts for Next Agent:
(leave blank)

Open Questions:
(list any clarifications needed)

---

## GATE STATUS: ðŸŸ¢ GREEN / ðŸŸ¡ YELLOW / ðŸ”´ RED

**Rationale**: [Explanation]

<!-- WORKFLOW_GATE: GREEN | CRITICAL_OPEN: 0 | HIGH_OPEN: 0 | MEDIUM_OPEN: 0 -->
```

> Replace GREEN with YELLOW or RED as appropriate. Fill in the finding counts based
> on any open issues in this stage's output. These counts are read by the orchestrator
> to drive routing â€” fill them accurately.

## Gate Criteria

- [ ] Contract is complete (all fields present)
- [ ] Scope is minimal (no over-engineering)
- [ ] Acceptance criteria are testable
- [ ] Required tests cover all criteria
- [ ] Constraints are non-negotiable
- [ ] Naming expectations for new/changed symbols are explicit
- [ ] Maintainability risk is acceptable for the proposed scope

**Return GREEN if all pass. Return YELLOW if scope is sound but minor open questions
remain. Return RED if scope is too broad or acceptance criteria are vague.**

## Gate Rules

- **GREEN**: Proceed to next stage (Stage 2 on full path, Stage 3 on fast path).
- **YELLOW**: Proceed to next stage, but log findings in the handoff.
- **RED**: Do not proceed. Report blocking issues.

## Progress Tracking

Append to `.claude/workflow-state/progress.md` — do not overwrite. Write at least
three entries: START, one per major step, and DONE. Format:

```text
[Stage 1 — Solution Architect] START → <one-sentence task description>
[Stage 1 — Solution Architect] <Verb> — <what you are doing>
[Stage 1 — Solution Architect] DONE → GATE: {GATE} | AC: {count} | TESTS: {contract count} | SCOPE: {file count} files
```

Examples:
```text
[Stage 1 — Solution Architect] START → Define scope and TDD contract for retry logic in DAX agent
[Stage 1 — Solution Architect] Read — reviewing target files: dax_measures/__init__.py
[Stage 1 — Solution Architect] Write — defining 6 acceptance criteria and 8 required tests
[Stage 1 — Solution Architect] DONE → GATE: GREEN | AC: 6 | TESTS: 8 | SCOPE: 2 files
```

## AGENT_SUMMARY Block

The PM reads only this block — not the full handoff prose. Append this as the
**absolute last output**, after the `<!-- WORKFLOW_GATE -->` comment.

Field derivation:

- `STAGE`: always `SA`
- `GATE`: match the WORKFLOW_GATE value
- `AC_TOTAL`: count the numbered items in the Acceptance Criteria section
- `AC_WITH_TESTS`: always `0` (no tests written yet at this stage)
- `TESTS_PASSING`, `TESTS_FAILING`: always `0`
- `OPEN_CRITICAL/HIGH/MEDIUM`: from finding counts in the WORKFLOW_GATE comment
- `FILES_MODIFIED`: comma-separated list of in-scope file paths from the handoff
- `OPEN_QUESTIONS`: `YES` if the Open Questions section has content; `NO` if empty
- `FAILURE_SUMMARY`: describe blocking issues; `none` if GATE=GREEN
- `DESIGN_AMBIGUITY`: `YES` if any HIGH-severity item in the Risks section relates to
  design choices (implementation approach, technology selection, architecture), or if
  the SA text includes "two viable approaches", "unclear which", or "either X or Y".
  Set `NO` otherwise.
- `SCOPE_SIZE`: count of in-scope file paths listed in the handoff
- `TEST_CONTRACT_COUNT`: count of numbered items in the Required Tests section

```text
<!-- AGENT_SUMMARY
STAGE: SA
AGENT: Solution Architect
GATE: GREEN | YELLOW | RED
AC_TOTAL: [count of acceptance criteria]
AC_WITH_TESTS: 0
TESTS_PASSING: 0
TESTS_FAILING: 0
OPEN_CRITICAL: [count]
OPEN_HIGH: [count]
OPEN_MEDIUM: [count]
FILES_MODIFIED: [comma-separated in-scope file paths]
OPEN_QUESTIONS: YES | NO
FAILURE_SUMMARY: [blocking issues, or "none" if GATE=GREEN]
DESIGN_AMBIGUITY: YES | NO
SCOPE_SIZE: [count of in-scope files]
TEST_CONTRACT_COUNT: [count of required tests]
-->
```

## Next

When run via the PM loop, the handoff is passed automatically.
For standalone use, copy this handoff into the next stage prompt.
