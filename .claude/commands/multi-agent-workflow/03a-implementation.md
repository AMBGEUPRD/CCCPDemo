---
description: "Stage 3a of 5: Red Phase — write failing tests from the acceptance criteria test contract."
---

# Stage 3a: Red Phase — Test Specification

## Role: Developer | Model: Sonnet

## Input

Stage 1 handoff (in-scope files, acceptance criteria, Required Tests with
Given/When/Then docstrings). Findings Ledger (provided by dispatcher).

## Hard Scope Constraint

**You may ONLY modify test files in this stage.**
Do NOT write or modify production code — that is Stage 3b.
If a production file must change to support the test, note it in Open Questions.

## Reasoning Mode

Adapt behavior to the `reasoning_level` in the task card:

**LOW** — fast path: read only focus_files, write minimal failing tests for AC, concise output.

**MEDIUM** — standard path: full test contract, all checks, complete output.

**HIGH** — exhaustive path: re-read all relevant files, challenge contract assumptions, maximum coverage.

## Work

1. Write progress: `[Stage 3a — Red Phase] Starting — reading test contract`
2. Read Stage 1's Required Tests section. Each test has a name and a
   Given/When/Then docstring describing the exact expected behaviour.
3. Write progress: `[Stage 3a — Red Phase] Writing failing tests`
4. For each required test, write a complete test function body:
   - Use the Given/When/Then docstring as the specification.
   - Write REAL assertions: `assert result == expected`, `pytest.raises(...)`,
     `mock.assert_called_once_with(...)` — NOT `pass`, NOT `...`.
   - Place tests in the correct existing test file (mirror source tree structure
     under `tests/unit/`).
   - Import the production symbol under test — it will cause `ImportError` if
     the symbol doesn't exist yet, which is the expected RED state.
5. Write progress: `[Stage 3a — Red Phase] Running pytest to confirm RED`
6. Run: `pytest tests/unit/ -v --tb=short -k "<space-separated required test names>"`
7. For each required test, classify the failure reason:
   - **ACCEPTABLE RED:** `ImportError` (symbol not yet created), `AttributeError`
     (method not yet defined), `AssertionError` (function exists but returns wrong value)
   - **NOT ACCEPTABLE → gate RED:** test PASSES (vacuous — test is wrong),
     `SyntaxError` (test is broken), fixture/setup error (test infrastructure issue)
8. Write progress: `[Stage 3a — Red Phase] Complete — N tests failing (RED)`

## Gate Criteria

- [ ] All required tests exist with complete assertion bodies (no `pass`, no `...`)
- [ ] All required tests FAIL when run
- [ ] Every failure reason is ACCEPTABLE (ImportError, AttributeError, AssertionError)
- [ ] No production files were touched (verified by `git diff --name-only`)
- [ ] Test names match exactly the names listed in Stage 1's Required Tests

**GREEN:** all criteria met.
**YELLOW:** minor fixture issues (test runs but fails on setup — fixable without production code).
**RED:** any test passes vacuously, has SyntaxError, or has fixture error.

## Output Format

```markdown
## STAGE 3a COMPLETE — Red Phase

Test File(s) Modified:
- [path]: [test names added]

Required Tests — RED Confirmation:
| Test Name | Failure Reason | Acceptable? |
|-----------|----------------|-------------|
| test_name | ImportError: cannot import 'func_x' | YES |
| test_name | AssertionError: assert None == expected | YES |

Scope Check (git diff --name-only — test files only):
- [test file path] — IN SCOPE ✓

Open Questions:
(production symbols needed that are not yet clear from Stage 1 spec, or "none")

---

## GATE STATUS: 🟢 GREEN / 🟡 YELLOW / 🔴 RED

**Rationale**: [Explanation]

<!-- WORKFLOW_GATE: GREEN | CRITICAL_OPEN: 0 | HIGH_OPEN: 0 | MEDIUM_OPEN: 0 -->
```

## Progress Tracking

Append to `.claude/workflow-state/progress.md` — do not overwrite. Write at least
three entries: START, one per major step, and DONE. Format:

```text
[Stage 3a — Red Phase] START → <one-sentence task description>
[Stage 3a — Red Phase] <Verb> — <what you are doing>
[Stage 3a — Red Phase] DONE → GATE: {GATE} | RED: {failing count} | GREEN: {passing count} | ALL_FAILING: YES|NO
```

Examples:
```text
[Stage 3a — Red Phase] START → Write 8 failing tests from SA contract for retry logic
[Stage 3a — Red Phase] Write — adding test_retry_on_rate_limit, test_retry_exhausted (2/8)
[Stage 3a — Red Phase] Run — pytest confirms 8/8 failing with ImportError / AssertionError
[Stage 3a — Red Phase] DONE → GATE: GREEN | RED: 8 | GREEN: 0 | ALL_FAILING: YES
```

## AGENT_SUMMARY Block

The PM reads only this block — not the full handoff prose. Append this as the
**absolute last output**, after the `<!-- WORKFLOW_GATE -->` comment.

Field derivation:

- `STAGE`: always `DEV-red`
- `GATE`: match the WORKFLOW_GATE value
- `AC_TOTAL`: carry forward from SA AGENT_SUMMARY
- `AC_WITH_TESTS`: count the acceptance criteria from Stage 1 that have at least one
  test in the test file. Compare test docstrings/names against AC list.
- `TESTS_PASSING`: should be `0` — in a correct Red phase, no tests pass
- `TESTS_FAILING`: count of failing tests from pytest output
- `OPEN_CRITICAL/HIGH/MEDIUM`: from the WORKFLOW_GATE finding counts
- `FILES_MODIFIED`: comma-separated test file paths only (from `git diff --name-only`)
- `OPEN_QUESTIONS`: `YES` if Open Questions has production symbols not yet clear; `NO` otherwise
- `FAILURE_SUMMARY`: describe why Red phase is invalid if GATE=RED (e.g., "test_foo passes
  vacuously — assertion is missing real value"); `none` if GATE=GREEN
- `ALL_FAILING`: `YES` only when EVERY required test fails for acceptable reasons
  (ImportError, AttributeError, AssertionError). Any passing test or SyntaxError = `NO`.

```text
<!-- AGENT_SUMMARY
STAGE: DEV-red
AGENT: Developer
GATE: GREEN | YELLOW | RED
AC_TOTAL: [carry forward from SA]
AC_WITH_TESTS: [count of ACs with at least one test written]
TESTS_PASSING: 0
TESTS_FAILING: [count from pytest output]
OPEN_CRITICAL: [count]
OPEN_HIGH: [count]
OPEN_MEDIUM: [count]
FILES_MODIFIED: [test file paths only]
OPEN_QUESTIONS: YES | NO
FAILURE_SUMMARY: [why Red is invalid, or "none" if GATE=GREEN]
ALL_FAILING: YES | NO
-->
```

## Next

PM loop advances to developer/green after confirming ALL_FAILING=YES.
For standalone use, copy this output into Stage 3b.
