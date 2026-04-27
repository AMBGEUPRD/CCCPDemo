# Agent Handoff Contract Template

Use this exact format for every agent-to-agent transition. Copy, fill in, paste into next stage.

---

## Handoff v1

**Task ID**: `task-{issue-number}-{timestamp}` (e.g., `task-42-20260415-1430`)

**Objective**: One sentence describing the work.  
*Example: "Add exponential backoff retry logic to metadata extractor agent with configurable max attempts."*

**In-Scope Files**:
- `src/Tableau2PowerBI/core/validation.py`
- `tests/unit/test_validation.py`

**Out-of-Scope Files**:
- `src/Tableau2PowerBI/agents/metadata_extractor/SKILL.md` (LLM instructions—do not touch in implementation phase)
- `src/Tableau2PowerBI/cli/` (orchestration layer; not handled by this task)
- Any file outside `src/Tableau2PowerBI/`

**Constraints** (non-negotiables):
- Do not break existing test suite (`pytest tests/unit/ -v`)
- Do not remove or rename public APIs
- Do not add synchronous blocking calls; use `async`/`await`
- Max line length 120 characters
- Prefer the smallest correct implementation; avoid speculative abstractions
- Use clear, intention-revealing names for new or changed symbols
- **Remove all temporary files** (smoke tests, scratch scripts, debug dumps) before handoff

**Acceptance Criteria**:
1. Metadata extractor retries on HTTP 429 with exponential backoff (2s, 4s, 8s)
2. Backoff respects `Retry-After` header if present
3. Circuit breaker stops retrying after 3 consecutive failures
4. All retry attempts logged with attempt number and elapsed time
5. New tests cover: max retries reached, backoff calculation, Retry-After parsing

**Naming and Maintainability Expectations**:
1. New symbols use descriptive domain names (avoid ambiguous abbreviations)
2. Changes keep responsibilities cohesive and avoid unnecessary helper layers
3. Code remains understandable to a new contributor within one quick read

**Required Tests**:
1. `test_retry_on_rate_limit()` — validates 429 handling
2. `test_backoff_timing()` — confirms exponential delays
3. `test_retry_after_header()` — validates header parsing
4. `test_circuit_breaker_stops_retry()` — circuit break at N failures
5. `test_all_retries_logged()` — log audit

**Risks**:
1. **MEDIUM**: Backoff timing could cause slow test runs if not mocked properly
2. **MEDIUM**: Retry loop could mask transient infrastructure issues
3. **LOW**: Existing callers may rely on fail-fast behavior; confirm no silent breakage

**Artifacts for Next Agent**:
1. Path: `src/Tableau2PowerBI/core/validation.py` — updated retry logic
2. Path: `tests/unit/test_validation.py` — new test suite  
3. Summary: "Retry logic in place, all tests green, no regressions in unrelated tests"
4. Workspace Status: Clean (all temporary files removed; only production code remains)
5. Evidence block:
   ```
   TESTS RUN:
   ✓ test_retry_on_rate_limit
   ✓ test_backoff_timing
   ✓ test_retry_after_header
   ✓ test_circuit_breaker_stops_retry
   ✓ test_all_retries_logged
   ✓ pytest tests/unit/ -v (full suite: 87 passed)
   
   FILES TOUCHED:
   - src/Tableau2PowerBI/core/validation.py (42 lines added/modified)
   - tests/unit/test_validation.py (75 lines added)
   
   UNRESOLVED RISKS:
   - None
   ```

**Open Questions**:
- Should circuit breaker reset after N seconds of success, or stay broken until restart? (Propose: reset after 60s of no failures)
- Should we emit a metric/alert when circuit breaker activates? (Propose: log as WARNING, defer metrics to phase 2)

---

## How to Use This Contract

**Stage 1 (Architecture Reviewer)** fills this in and passes to Stage 2.

**Each subsequent stage**:
1. Reads the contract at the start
2. Verifies the handoff includes all required fields
3. If any field is missing or contradictory, returns RED and asks Stage 1 or prior stage to reissue
4. If contract is complete and consistent, proceeds
5. At the end of its work, fills in the "Artifacts for Next Agent" section with concrete evidence
6. Passes updated contract to next stage

**Sample Red Gate** (QA stage finds contract incomplete):
> "CONTRACT REJECTION: Required tests section lists 5 tests but actual test count is 3. Artifacts missing evidence block. Return contract to Implementation stage for reissue."

---

## Validation Checklist (for each stage)

Before proceeding, verify:

- [ ] Task ID is present and unique
- [ ] Objective is a single clear sentence
- [ ] In-Scope Files are explicit (not just directory names)
- [ ] Out-of-Scope Files are explicit and justified
- [ ] At least 3 Constraints listed
- [ ] 5+ Acceptance Criteria (numbered, testable, concrete)
- [ ] Required Tests (exact test function names or test classes)
- [ ] Risks quantified (LOW/MEDIUM/HIGH) with reasoning
- [ ] Naming and maintainability expectations are explicit
- [ ] Artifacts block includes file paths and summary
- [ ] Evidence block shows actual test runs or will-run attestation
- [ ] Open Questions are specific (not vague)

If any field fails this check, return RED to the prior stage.
