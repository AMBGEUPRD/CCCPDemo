# Multi-Agent Workflow Checklist

Use this checklist to orchestrate the 6-stage workflow for a coding task.

Cross-stage rule: every stage must preserve simplicity, naming clarity, and
maintainability. If a stage passes functionally but fails these quality gates, return
YELLOW or RED with explicit rework instructions.

---

## Workflow: [Task Title]

**Task ID**: `task-{issue-number}-{timestamp}`  
**Created**: [date]  
**Owner**: [your name]

---

## Stage 1: Architecture Review

**Agent**: AI Agent Architecture Reviewer

**Entry Criteria**:
- [ ] Task description is provided
- [ ] Task scope is 1-3 files or 1 small component

**Work**:
- [ ] Review task for over-engineering risk
- [ ] Produce handoff contract with in_scope_files, out_of_scope_files, constraints
- [ ] List 5+ acceptance criteria (testable, concrete)
- [ ] Identify top 3–5 risks with severity
- [ ] Propose smallest viable approach
- [ ] Reject if design involves unnecessary abstractions
- [ ] Define naming expectations for all new or changed symbols

**Exit Gate**:
- [ ] Contract delivered and complete
- [ ] All required fields populated (see validation checklist)
- **Gate Status**: [ ] GREEN  [ ] YELLOW  [ ] RED

**Gate Rationale**: (if YELLOW or RED, explain why)  
________________________________________

**Blockers**: (if any, address before moving to Stage 2)  
________________________________________

---

## Stage 2: Python Solution Review (Pre-Implementation Design Gate)

**Agent**: Python Solution Reviewer

**Entry Contract**: (Paste the handoff from Stage 1)  
________________________________________

**Entry Criteria**:
- [ ] Handoff contract from Stage 1 is complete
- [ ] No open questions remain from Stage 1
- [ ] Constraints and acceptance criteria are clear

**Work**:
- [ ] Review proposed approach for correctness, async safety, error handling
- [ ] Challenge type hints, docstring quality, and module organization
- [ ] Suggest any design changes to improve clarity or maintainability
- [ ] Validate complexity is justified and not avoidable
- [ ] Validate that the in_scope_files are the right set (not too broad)
- [ ] Request mitigation for any high-risk items identified in Stage 1

**Exit Gate**:
- [ ] Design feedback delivered (findings first, ordered by severity)
- [ ] Any CRITICAL findings documented with concrete fixes
- [ ] Test plan reviewed for coverage gaps
- **Gate Status**: [ ] GREEN  [ ] YELLOW  [ ] RED

**Gate Rationale**: (if YELLOW or RED, explain why; if RED, document required changes)  
________________________________________

**Blockers**: (if any, address before moving to Stage 3)  
________________________________________

---

## Stage 3: Implementation

**Agent**: Tableau2PBIHelper (or implementation-stage agent for your domain)

**Entry Contract**: (Paste updated handoff from Stage 2)  
________________________________________

**Entry Criteria**:
- [ ] Design gate (Stage 2) is GREEN
- [ ] All in_scope_files are understood and accessible
- [ ] No open design questions remain

**Work**:
- [ ] Implement changes only in in_scope_files (do not touch out_of_scope)
- [ ] Follow all Constraints from handoff contract
- [ ] Target each Acceptance Criterion with concrete code
- [ ] Add/update tests for each criterion
- [ ] Run `pytest tests/unit/ -v --tb=short` before exit
- [ ] Verify no regressions in unrelated tests
- [ ] Use clear, domain-revealing names in new/changed code
- [ ] Avoid adding unnecessary helper layers or wrappers

**Exit Criteria**:
- [ ] All code changes in place in in_scope_files
- [ ] All required tests written and green
- [ ] Test summary: _____ tests passed, _____ new tests added
- [ ] Any high-risk code areas have comments explaining intent

**Exit Gate**:
- [ ] Implementation complete with passing tests
- [ ] Evidence block filled in (test results, files touched)
- [ ] Acceptance criteria all targeted with code
- **Gate Status**: [ ] GREEN  [ ] YELLOW  [ ] RED

**Gate Rationale**: (if YELLOW or RED, explain why)  
________________________________________

**Blockers**: (if any, address before moving to Stage 4)  
________________________________________

---

## Stage 4: QA Verification

**Agent**: QA Subagent

**Entry Contract**: (Paste updated handoff from Stage 3)  
________________________________________

**Entry Criteria**:
- [ ] Implementation stage is GREEN
- [ ] All required tests are defined in handoff
- [ ] Test evidence is present

**Work**:
- [ ] Run each required test and validate PASS/FAIL
- [ ] For each acceptance criterion, confirm test coverage
- [ ] Check for boundary cases and error handling
- [ ] Verify edge cases identified in Stage 1 risks are tested
- [ ] Produce evidence matrix: criterion → test name → PASS/FAIL
- [ ] Flag naming and maintainability regressions in changed code

**QA Evidence Matrix**:

| Acceptance Criterion | Test Name | Result | Notes |
|---------------------|-----------|--------|-------|
| 1. (from handoff) | test_name_1 | PASS / FAIL | |
| 2. (from handoff) | test_name_2 | PASS / FAIL | |
| 3. (from handoff) | test_name_3 | PASS / FAIL | |
| 4. (from handoff) | test_name_4 | PASS / FAIL | |
| 5. (from handoff) | test_name_5 | PASS / FAIL | |

**Exit Gate**:
- [ ] All required tests PASS
- [ ] Evidence matrix complete
- [ ] No unverified high-risk areas
- [ ] Any failures documented and routed back to Implementation
- **Gate Status**: [ ] GREEN  [ ] YELLOW  [ ] RED

**Gate Rationale**: (if YELLOW or RED, explain why)  
________________________________________

**Blockers / Failures**: (if RED, return to Implementation with only failed acceptance criteria)  
________________________________________

---

## Stage 5: Python Solution Review (Post-Implementation Code Gate)

**Agent**: Python Solution Reviewer

**Entry Contract**: (Paste updated handoff from Stage 4)  
________________________________________

**Entry Criteria**:
- [ ] QA stage is GREEN
- [ ] All required tests pass
- [ ] Implementation is complete

**Work**:
- [ ] Review actual code for correctness, typing, async safety, error handling
- [ ] Audit logging quality and completeness
- [ ] Check for missing docstrings or unclear variable names
- [ ] Validate test code quality: clear names, one assertion per logical concept
- [ ] Challenge any complexity introduced that doesn't earn its keep
- [ ] Suggest or implement fixes for critical findings
- [ ] Confirm naming quality and maintenance cost are acceptable

**Exit Gate**:
- [ ] Code review complete (findings first, ordered by severity)
- [ ] No CRITICAL findings unresolved
- [ ] All high-severity findings either fixed or explicitly accepted with risk notation
- **Gate Status**: [ ] GREEN  [ ] YELLOW  [ ] RED

**Gate Rationale**: (if YELLOW or RED, explain why)  
________________________________________

**Blockers**: (if RED, document findings and route back to Implementation)  
________________________________________

---

## Stage 6: Final Merge Gate (Uncommitted Code Review)

**Agent**: Uncommitted Code Reviewer

**Entry Contract**: (Paste updated handoff from Stage 5)  
________________________________________

**Entry Criteria**:
- [ ] Python code gate (Stage 5) is GREEN
- [ ] All prior stages report completion
- [ ] Changes are ready for commit

**Work**:
- [ ] Inspect the actual git diff (staged or unstaged changes)
- [ ] Check for regressions in unrelated code
- [ ] Validate that only in_scope_files were touched
- [ ] Confirm test coverage is present for all changes
- [ ] Challenge any unnecessary complexity
- [ ] Produce final simplification suggestions if applicable
- [ ] Confirm final naming quality is consistent and maintainable

**Exit Gate**:
- [ ] Diff reviewed for correctness and regression risk
- [ ] No critical findings unresolved
- [ ] Confidence level in merge: HIGH / MEDIUM / LOW
- **Gate Status**: [ ] GREEN  [ ] YELLOW  [ ] RED

**Confidence Rationale**: (if MEDIUM or LOW, explain secondary blockers)  
________________________________________

**Final Findings** (if any):  
________________________________________

**Recommendation**: 
- [ ] APPROVED FOR MERGE
- [ ] APPROVED WITH MINOR NOTES (document in PR)
- [ ] BLOCKED (return to Implementation or prior stage)

---

## Workflow Sign-Off

| Stage | Owner | Status | Date | Notes |
|-------|-------|--------|------|-------|
| 1. Architecture | ______ | GREEN / YELLOW / RED | ____ | |
| 2. Python (Pre) | ______ | GREEN / YELLOW / RED | ____ | |
| 3. Implementation | ______ | GREEN / YELLOW / RED | ____ | |
| 4. QA | ______ | GREEN / YELLOW / RED | ____ | |
| 5. Python (Post) | ______ | GREEN / YELLOW / RED | ____ | |
| 6. Merge Gate | ______ | GREEN / YELLOW / RED | ____ | |

**Overall Workflow Status**: [ ] APPROVED  [ ] BLOCKED  [ ] IN PROGRESS

**Final Approval By**: ________________  
**Date**: __________________

---

## Rework Loop (if any stage returns RED)

**Returning Stage**: (which stage returned RED?)  
________________________________________

**Root Cause**: (what was the issue?)  
________________________________________

**Rework Owner**: (which stage will fix it?)  
________________________________________

**Return to Stage**: (which stage should re-validate after fix?)  
________________________________________

**Rework Completion**: [ ] Done, resubmitted to Stage ______
