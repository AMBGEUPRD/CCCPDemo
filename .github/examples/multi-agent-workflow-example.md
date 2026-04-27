# Example: Running the Multi-Agent Workflow in GitHub Copilot

This example walks through a complete 6-stage workflow for a real task in **GitHub Copilot Chat**.

---

## Example Task

**Issue**: "Add circuit breaker to pipeline metadata extraction to prevent cascading failures when Tableau API is down."

---

## Step 1: Open Copilot Chat in VS Code

1. Open your repo in VS Code
2. Open GitHub Copilot Chat (Ctrl+Shift+I on Windows, Cmd+Shift+I on Mac)
3. You should see a chat window

---

## Step 2: Load the Orchestration Prompt

Copy this text into the chat:

```
@github #copilot-instructions

I want to run a multi-agent workflow for this task:

"Add circuit breaker to pipeline metadata extraction to prevent cascading failures 
when Tableau API is down."

Use the orchestration guide at `.github/prompts/run-multi-agent-workflow.prompt.md`.

Start with Stage 1: Architecture Review. Follow the handoff contract template at 
`.github/templates/agent-handoff-contract.md` and produce a complete handoff.
```

---

## Step 3: Stage 1 (Architecture Reviewer) Executes

GitHub Copilot will invoke the **AI Agent Architecture Reviewer** agent.

Expected output:
```
# Stage 1: Architecture Review

## HANDOFF v1

**Task ID**: `task-circuit-breaker-20260415-1430`

**Objective**: Add circuit breaker pattern to metadata extractor to fail fast when 
Tableau API is down, preventing token waste and cascading retries.

**In-Scope Files**:
- `src/Tableau2PowerBI/core/metadata_extractor.py`
- `src/Tableau2PowerBI/agents/metadata_extractor/SKILL.md` (prompt tuning only)
- `tests/unit/test_metadata_extractor.py`

**Out-of-Scope Files**:
- `src/Tableau2PowerBI/cli/` (orchestration layer)
- Any other agent packages
- Retry logic (covered separately in backoff task)

**Constraints**:
1. Do not break existing test suite
2. Circuit breaker state must be thread-safe (use asyncio.Lock if needed)
3. Circuit breaker threshold configurable (default: 3 consecutive failures)
4. All state transitions must be logged at INFO level

**Acceptance Criteria**:
1. Circuit breaker transitions: CLOSED → OPEN → HALF_OPEN → CLOSED
2. When OPEN, all calls fail immediately without contacting API
3. When HALF_OPEN, single test call allowed; if success → CLOSED; if fail → OPEN
4. Timeout between OPEN and HALF_OPEN is configurable (default: 60 seconds)
5. All state transitions logged with timestamp and reason
6. Circuit breaker is injectable/testable (not hardcoded in class)

**Required Tests**:
1. `test_circuit_breaker_opens_after_max_failures`
2. `test_circuit_breaker_fails_fast_when_open`
3. `test_circuit_breaker_half_open_on_timeout`
4. `test_circuit_breaker_closes_on_recovery`
5. `test_circuit_breaker_state_transitions_logged`

**Risks**:
- MEDIUM: Circuit breaker state could desynchronize if concurrent requests race. 
  Mitigation: Use asyncio.Lock for all state transitions.
- MEDIUM: Timeout between OPEN and HALF_OPEN could be too short or too long. 
  Mitigation: Make configurable per deployment.
- LOW: Existing code may assume metadata extractor always attempts the call.
  Mitigation: Document behavior change in code comments.

**Artifacts for Next Agent**:
(to be filled by later stages)

**Open Questions**:
- Should circuit breaker track failures per API endpoint, or per agent package? 
  (Propose: per agent, can refactor to per-endpoint in phase 2)
- Should we emit a metric/alert when circuit opens? 
  (Propose: log as WARNING, defer metrics to phase 2)

---

## GATE STATUS: 🟢 GREEN

**Rationale**: Scope is minimal and well-defined. Design avoids unnecessary abstractions. 
Test plan covers all state transitions.
```

---

## Step 4: Copy the Contract and Move to Stage 2

In the same chat, paste:

```
@github #copilot-instructions

Contract from Stage 1 accepted. Now run Stage 2: Python Solution Review (Pre-Implementation).

[PASTE THE FULL HANDOFF HERE]

Validate the design approach for correctness, async safety, error handling, and typing. 
Return your design feedback.
```

---

## Step 5: Stage 2 (Python Solution Reviewer Pre) Executes

Expected output:

```
# Stage 2: Python Solution Review (Pre-Implementation Design Gate)

## CONTRACT VALIDATION
✓ All required handoff fields present
✓ No contradictions in scope
✓ Acceptance criteria are testable

## DESIGN REVIEW

**CRITICAL**: None

**HIGH**: None

**MEDIUM**:
- Type hints on circuit breaker state enum should be explicit (Enum type, not string)
  Mitigation: Define `class CircuitState(Enum): CLOSED = 1; OPEN = 2; HALF_OPEN = 3`

**Findings Summary**:
The design is sound. Async safety is ensured with asyncio.Lock. Error handling 
is explicit (fail-fast when OPEN). Test plan covers all transitions.

**Mitigation for Medium findings**: Define CircuitState as strict Enum; proposal 
checked during implementation.

---

## GATE STATUS: 🟢 GREEN (with 1 logged medium finding)

**Rationale**: Design approach is correct. Async patterns align with codebase. 
No blockers to implementation. One type hint suggestion to apply during implementation.
```

---

## Step 6: Copy and Move to Stage 3

Paste in chat:

```
@github #copilot-instructions

Design gate accepted. Now run Stage 3: Implementation.

[PASTE THE FULL HANDOFF + DESIGN FEEDBACK HERE]

Implement the circuit breaker in `src/Tableau2PowerBI/core/metadata_extractor.py`. 
Add/update tests in `tests/unit/test_metadata_extractor.py`.

When done, run `pytest tests/unit/ -v --tb=short` and report test results.
```

---

## Step 7: Stage 3 (Tableau2PBIHelper Implementation Agent) Executes

Expected output:

```
# Stage 3: Implementation

## FILES MODIFIED

- src/Tableau2PowerBI/core/metadata_extractor.py (87 lines added/modified)
  + Added CircuitState enum
  + Added CircuitBreaker class with async context manager
  + Integrated into MetadataExtractor.fetch()
  
- tests/unit/test_metadata_extractor.py (120 lines added)
  + test_circuit_breaker_opens_after_max_failures
  + test_circuit_breaker_fails_fast_when_open
  + test_circuit_breaker_half_open_on_timeout
  + test_circuit_breaker_closes_on_recovery
  + test_circuit_breaker_state_transitions_logged

## TEST RESULTS

pytest tests/unit/ -v --tb=short

tests/unit/test_metadata_extractor.py::test_circuit_breaker_opens_after_max_failures PASSED
tests/unit/test_metadata_extractor.py::test_circuit_breaker_fails_fast_when_open PASSED
tests/unit/test_metadata_extractor.py::test_circuit_breaker_half_open_on_timeout PASSED
tests/unit/test_metadata_extractor.py::test_circuit_breaker_closes_on_recovery PASSED
tests/unit/test_metadata_extractor.py::test_circuit_breaker_state_transitions_logged PASSED

tests/unit/ — 87 passed, 5 new tests added, 0 failed

## ACCEPTANCE CRITERIA MAPPING

1. State transitions (CLOSED → OPEN → HALF_OPEN → CLOSED) 
   → Implemented in CircuitBreaker class, tested in test_circuit_breaker_state_transitions_logged
   
2. Fast-fail when OPEN 
   → MetadataExtractor.fetch() checks state, raises OpenCircuitError immediately, 
     tested in test_circuit_breaker_fails_fast_when_open
   
3. Half-open test call 
   → CircuitBreaker.half_open_timeout triggers single test call, 
     tested in test_circuit_breaker_half_open_on_timeout
   
4. Configurable timeout 
   → CircuitBreaker(failure_threshold=3, reset_timeout=60) constructor params, 
     defaults defined in core/config.py
   
5. All state transitions logged 
   → CircuitBreaker emits logging.INFO on every transition, 
     tested in test_circuit_breaker_state_transitions_logged
   
6. Testable/injectable 
   → CircuitState is passed to MetadataExtractor constructor, 
     can be mocked in tests (verified with test fixtures)

## ARTIFACTS FOR NEXT AGENT

Path: src/Tableau2PowerBI/core/metadata_extractor.py
Path: tests/unit/test_metadata_extractor.py

Summary: Circuit breaker fully implemented, all 5 required tests passing, no regressions 
in existing tests.

---

## GATE STATUS: 🟢 GREEN

**Rationale**: All acceptance criteria implemented. All required tests pass. 
No regressions. Medium type-hint finding from Stage 2 addressed (CircuitState enum in place).
```

---

## Step 8: Copy and Move to Stage 4

Paste in chat:

```
@github #copilot-instructions

Implementation complete. Now run Stage 4: QA Verification.

[PASTE THE FULL HANDOFF + IMPLEMENTATION ARTIFACTS HERE]

Verify each acceptance criterion against the test evidence. 
Produce evidence matrix: criterion → test name → PASS/FAIL.
Check for unverified high-risk areas.
```

---

## Step 9: Stage 4 (QA Subagent) Executes

Expected output:

```
# Stage 4: QA Verification

## EVIDENCE MATRIX

| Acceptance Criterion | Test Name | Result | Notes |
|---------------------|-----------|--------|-------|
| 1. State transitions (CLOSED → OPEN → HALF_OPEN → CLOSED) | test_circuit_breaker_state_transitions_logged | PASS | All 4 transitions verified in log output |
| 2. Fast-fail when OPEN | test_circuit_breaker_fails_fast_when_open | PASS | Raises OpenCircuitError < 1ms |
| 3. Half-open test call | test_circuit_breaker_half_open_on_timeout | PASS | Single call allowed, timing verified |
| 4. Configurable timeout | test_circuit_breaker_half_open_on_timeout | PASS | Timeout set to 5s in test, verified |
| 5. State transitions logged | test_circuit_breaker_state_transitions_logged | PASS | All 5 transitions in log at INFO level |

## COVERAGE CHECK

- Boundary case: 0 failures → stays CLOSED ✓ (implicit in test suite)
- Boundary case: max_failures + 1 → opens immediately ✓ (covered)
- Concurrent access → asyncio.Lock prevents races ✓ (lock verified in implementation)

## UNVERIFIED HIGH-RISK AREAS

- None. All risks from handoff have corresponding tests.

## TEST COVERAGE: 100% of acceptance criteria

---

## GATE STATUS: 🟢 GREEN

**Rationale**: All 5 acceptance criteria verified with passing tests. 
No unverified high-risk areas. Coverage is complete.
```

---

## Step 10: Copy and Move to Stage 5

Paste in chat:

```
@github #copilot-instructions

QA verification approved. Now run Stage 5: Python Solution Review (Post-Implementation Code Gate).

[PASTE THE FULL HANDOFF + QA REPORT HERE]

Review the actual implementation code for:
- Correctness and async safety
- Type hints completeness
- Error handling and logging
- Test code quality
- Unnecessary complexity

Return code review findings.
```

---

## Step 11: Stage 5 (Python Solution Reviewer Post) Executes

Expected output:

```
# Stage 5: Python Solution Review (Post-Implementation Code Gate)

## CODE REVIEW FINDINGS

**CRITICAL**: None

**HIGH**: None

**MEDIUM**:
- CircuitBreaker.half_open_timeout property uses float seconds; consider adding @property 
  docstring with units clarification.
  Suggestion: Add docstring "Reset timeout in seconds after entering OPEN state"
  
**Assessment**: Code is well-typed, async-safe, and thoroughly tested. Logging is clear 
and at appropriate levels (INFO for state transition, DEBUG for call attempts during 
HALF_OPEN). One minor docstring suggestion for clarity.

---

## GATE STATUS: 🟢 GREEN (with 1 logged medium finding)

**Rationale**: Code is production-ready. Async patterns are correct (asyncio.Lock 
prevents races). Error handling is explicit. Test code is clear and one-assertion-per-test. 
One docstring suggestion recorded but does not block merge.
```

---

## Step 12: Copy and Move to Stage 6

Paste in chat:

```
@github #copilot-instructions

Code review approved. Now run Stage 6: Uncommitted Code Reviewer (Final Merge Gate).

[PASTE THE FULL HANDOFF + CODE REVIEW HERE]

Review the git diff for:
- Only in-scope files modified
- No regressions
- Test coverage adequate
- No unnecessary complexity

Return final merge gate decision.
```

---

## Step 13: Stage 6 (Uncommitted Code Reviewer) Executes

Expected output:

```
# Stage 6: Uncommitted Code Reviewer (Final Merge Gate)

## DIFF SUMMARY

Files changed:
- src/Tableau2PowerBI/core/metadata_extractor.py (87 lines added)
- tests/unit/test_metadata_extractor.py (120 lines added)

Lines total: +207, -0 (only additions, no deletions)

Test coverage: Complete (5 new tests for 5 acceptance criteria)

## IN-SCOPE VERIFICATION

✓ All changes in src/Tableau2PowerBI/core/metadata_extractor.py (in-scope)
✓ All changes in tests/unit/test_metadata_extractor.py (in-scope)
✗ No changes to out-of-scope files (cli/, other packages, etc.)

## REGRESSION RISK: LOW

Full test suite passed (87 passed). No changes to contract of existing functions. 
Only additive change to MetadataExtractor (injects CircuitBreaker). 
Backwards-compatible: existing callers continue to work.

## SIMPLIFICATION OPPORTUNITIES

- None. Code is direct and purposeful. CircuitBreaker class has single responsibility.

---

## RECOMMENDATION: ✅ APPROVED FOR MERGE

**Confidence Level**: HIGH

**Rationale**:
- Only in-scope files modified
- No regressions detected
- Test coverage is complete
- Code is clear and async-safe
- All prior stages returned GREEN or YELLOW (with logged findings only)

Ready to commit.
```

---

## Summary: Full Workflow Execution

**You just demonstrated a complete 6-stage workflow in Copilot Chat:**

1. **Stage 1** (Architecture Reviewer): Defined scope, constraints, and acceptance criteria → 🟢 GREEN
2. **Stage 2** (Python Reviewer Pre): Validated design approach with 1 suggestion → 🟢 GREEN
3. **Stage 3** (Implementation): Coded solution + 5 tests, all green → 🟢 GREEN
4. **Stage 4** (QA): Verified all acceptance criteria with evidence matrix → 🟢 GREEN
5. **Stage 5** (Python Reviewer Post): Reviewed code for quality + 1 docstring suggestion → 🟢 GREEN
6. **Stage 6** (Merge Gate): Final regression check, approved for merge → ✅ APPROVED

**Total tokens used**: ~80-100K (depends on code size)  
**Total time**: ~10-15 minutes (in real chat)  
**Quality gates passed**: 6/6  
**Ready to commit**: YES

---

## How to Use This in Your Repo

1. **Save the prompt** as `.github/prompts/run-multi-agent-workflow.prompt.md` ✓ (already done)
2. **Save the contract template** as `.github/templates/agent-handoff-contract.md` ✓ (already done)
3. **Save the checklist** as `.github/templates/multi-agent-stage-checklist.md` ✓ (already done)
4. **On your next task**, open Copilot Chat and paste:
   ```
   @github #copilot-instructions

   Run the multi-agent workflow at `.github/prompts/run-multi-agent-workflow.prompt.md` 
   for this task: [your task description]
   ```
5. **Follow the workflow** through all 6 stages
6. **Sign off each stage** using the checklist template
7. **Commit when Stage 6 returns APPROVED**

---

## Key Validation Points

✅ **Works in Copilot Chat**: No code generation, no external scripts—pure prompt-based orchestration.  
✅ **Uses existing agents**: Leverages your 5 custom agents exactly as defined.  
✅ **Explicit handoffs**: Each stage outputs a contract; next stage validates it before starting.  
✅ **Quality gates**: RED outcomes route back to prior stage automatically.  
✅ **Token-efficient**: Uses artifact references instead of full file pastes.  
✅ **Human-verifiable**: Checklist provides clear pass/fail criteria per stage.  
✅ **Testable**: Complete evidence matrix shows what was tested and why.

**This workflow is production-ready and can be used starting today.**
