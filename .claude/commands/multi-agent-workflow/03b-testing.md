---
description: "Stage 3b of 5: Green Phase — write production code to make the failing tests from Stage 3a pass."
---

# Stage 3b: Green Phase — Implementation

## Role: Developer | Model: Sonnet

## Input

Stage 3a output (failing tests, test file paths, RED confirmation table).
Stage 1 handoff (in-scope files, acceptance criteria, constraints).
Findings Ledger with all OPEN findings (provided by dispatcher).

## Hard Scope Constraint

**You may ONLY modify production (non-test) files in this stage.**
Do NOT modify test bodies written in Stage 3a — the tests ARE the specification.
If a test appears incorrect or impossible to satisfy, flag it in Open Questions —
do not change it.

## Reasoning Mode

Adapt behavior to the `reasoning_level` in the task card:

**LOW** — fast path: read only focus_files, implement minimal production code, concise output.

**MEDIUM** — standard path: full implementation, all checks, complete output.

**HIGH** — exhaustive path: re-read all relevant files, challenge test assumptions, maximum scrutiny.

## Work

1. Write progress: `[Stage 3b — Green Phase] Starting — reading failing tests`
2. Read the failing tests from Stage 3a's test file(s). The test assertions ARE the spec.
3. Write progress: `[Stage 3b — Green Phase] Implementing production code`
4. Write minimal production code in in-scope non-test files to make the tests pass:
   - Target each failing test one at a time.
   - Write only what is needed to satisfy the assertion — do not over-engineer.
   - Address all OPEN CRITICAL/HIGH/MEDIUM findings from the Findings Ledger.
5. Write progress: `[Stage 3b — Green Phase] Running pytest — confirming GREEN`
6. Run: `pytest tests/unit/ -v --tb=short`
7. All required tests must PASS. Full suite must pass (no regressions).
8. If any required test fails: fix the production code only (NOT the test). Repeat
   until all required tests pass and the full suite is green.
9. Run `git diff --name-only` — confirm only production (non-test) files were changed
   since Stage 3a.
10. Write progress: `[Stage 3b — Green Phase] Complete — N passed, 0 failed`

## Gate Criteria

- [ ] All required tests from Stage 3a now PASS
- [ ] Full test suite passes (no regressions — `pytest tests/unit/` all green)
- [ ] Only non-test files modified since Stage 3a (verified by `git diff`)
- [ ] All CRITICAL/HIGH/MEDIUM findings from Findings Ledger addressed

**GREEN:** all criteria met.
**RED:** any required test fails, or regression in full suite, or test files modified.

## Output Format

```markdown
## STAGE 3b COMPLETE — Green Phase

Files Modified:
- [path]: [what was changed]

Required Tests — GREEN Confirmation:
| Test Name | Result |
|-----------|--------|
| test_name | ✓ PASS |

Full Test Suite: [N] passed, [0] failed

Acceptance Criteria — Code Coverage:
1. [Criterion] → [implementation approach and file:line]
2. [Criterion] → [implementation approach and file:line]

Findings Addressed:
- [F-NNN]: [what was changed to resolve it]
(or "No findings in ledger")

Scope Check (git diff since Stage 3a — production files only):
- [path] — IN SCOPE ✓

Open Questions:
(test bodies that appear incorrect or impossible to satisfy, or "none")

---

## GATE STATUS: 🟢 GREEN / 🟡 YELLOW / 🔴 RED

**Rationale**: [Explanation]

<!-- WORKFLOW_GATE: GREEN | CRITICAL_OPEN: 0 | HIGH_OPEN: 0 | MEDIUM_OPEN: 0 -->
```

## Progress Tracking

Append to `.claude/workflow-state/progress.md` — do not overwrite. Write at least
three entries: START, one per major step, and DONE. Format:

```text
[Stage 3b — Green Phase] START → <one-sentence task description>
[Stage 3b — Green Phase] <Verb> — <what you are doing>
[Stage 3b — Green Phase] DONE → GATE: {GATE} | PASS: {count} | FAIL: {count} | SUITE_CLEAN: YES|NO
```

Examples:

```text
[Stage 3b — Green Phase] START → Implement production code to pass 8 failing Red-phase tests
[Stage 3b — Green Phase] Write — adding retry logic with exponential backoff in dax_measures/__init__.py
[Stage 3b — Green Phase] Run — pytest: 8/8 target tests passing, full suite 42/42
[Stage 3b — Green Phase] DONE → GATE: GREEN | PASS: 42 | FAIL: 0 | SUITE_CLEAN: YES
```

## AGENT_SUMMARY Block

The PM reads only this block — not the full handoff prose. Append this as the
**absolute last output**, after the `<!-- WORKFLOW_GATE -->` comment.

This block is used for both the Green phase (first run) and Fix iterations.
The `FIX_ATTEMPT` field distinguishes them: `1` for the first Green phase run,
`2` or higher for subsequent fix iterations. The orchestrator injects the
`FIX_ATTEMPT` value into your context — use it as-is.

Fix iterations write to `handoff-S3b-fix-N.md` (where N = FIX_ATTEMPT); the
original `handoff-S3b.md` is never overwritten.

Field derivation:

- `STAGE`: `DEV-green` for first run (FIX_ATTEMPT=1); `DEV-fix` for subsequent runs
- `GATE`: match the WORKFLOW_GATE value
- `AC_TOTAL`: carry forward from SA AGENT_SUMMARY
- `AC_WITH_TESTS`: count of ACs that have at least one passing test. Should equal
  AC_TOTAL on a complete Green phase.
- `TESTS_PASSING`: count of passing tests from `pytest tests/unit/ -v --tb=short`
- `TESTS_FAILING`: count of failing tests from the same run
- `OPEN_CRITICAL/HIGH/MEDIUM`: from the findings ledger AFTER marking resolved items.
  Count only findings that remain open.
- `FILES_MODIFIED`: production file paths from `git diff --name-only` (no test files)
- `OPEN_QUESTIONS`: `YES` if test bodies appear incorrect or impossible; `NO` otherwise
- `FAILURE_SUMMARY`: describe which tests are still failing and why; `none` if GATE=GREEN
- `ALL_PASSING`: `YES` only when every required test from the SA contract shows PASS
- `SUITE_CLEAN`: `YES` only when the full `pytest tests/unit/` suite has zero failures
- `FIX_ATTEMPT`: the value injected by the orchestrator (1 for green, 2+ for fix)

```text
<!-- AGENT_SUMMARY
STAGE: DEV-green | DEV-fix
AGENT: Developer
GATE: GREEN | RED
AC_TOTAL: [carry forward from SA]
AC_WITH_TESTS: [count of ACs with passing tests]
TESTS_PASSING: [count from pytest]
TESTS_FAILING: [count from pytest]
OPEN_CRITICAL: [count — post-fix state]
OPEN_HIGH: [count — post-fix state]
OPEN_MEDIUM: [count — post-fix state]
FILES_MODIFIED: [production file paths only]
OPEN_QUESTIONS: YES | NO
FAILURE_SUMMARY: [which tests still fail and why, or "none" if GATE=GREEN]
ALL_PASSING: YES | NO
SUITE_CLEAN: YES | NO
FIX_ATTEMPT: [injected by orchestrator — 1 for green, 2+ for fix]
-->
```

## Next

PM loop reads ALL_PASSING, SUITE_CLEAN, and open finding counts to decide next action.
For standalone use, copy both Stage 3a and 3b outputs into the BA/Code Reviewer stages.
