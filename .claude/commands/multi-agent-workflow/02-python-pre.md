---
description: "Stage 2 of 6: Python Solution Review (Pre-Implementation). Validate design approach before coding."
---

# Stage 2: Python Solution Review (Pre-Implementation)

## Input

Receive the complete handoff from **Stage 1** (provided by the dispatcher or pasted manually).

## Design-Only Scope â€” Read This First

**Your scope in this stage is design-level analysis only.** You are reviewing an
approach that has not been implemented yet. Restrict your findings to:

- Algorithmic correctness
- Async/await pattern soundness
- Error handling strategy
- Type hint strategy and feasibility
- Test plan coverage of acceptance criteria
- Simpler implementation alternatives
- Symbol naming clarity in the proposed design

**Do NOT report** implementation-level issues (missing docstrings on existing code,
log message length, code style, unused imports, file size) â€” those belong to Stage 5,
which reviews actual code. Flagging them now creates duplicate Findings Ledger entries
and inflates the feedback loop.

## Reasoning Mode

Adapt behavior to the `reasoning_level` in the task card:

**LOW** — fast path: read only focus_files, trust prior stage outputs, concise output.

**MEDIUM** — standard path: full verification, all checks, complete output.

**HIGH** — exhaustive path: re-read all relevant files, challenge prior stage assumptions, maximum scrutiny.

## Work

1. Validate handoff completeness (all required fields present).
2. Review the proposed approach against the Design-Only Scope above.
3. Challenge the design:
   - Are there hidden assumptions?
   - Will the typing strategy actually work?
   - Is error handling sufficient for the failure modes in Stage 1 risks?
   - Is there a simpler implementation with fewer moving parts?
   - Are proposed symbol names clear and domain-specific?
4. **Report all design-level findings** â€” including pre-existing design issues
   discovered in the in-scope files. Tag each as **[Task]** or **[Pre-existing]**.

## Output Format

```markdown
## DESIGN REVIEW

**Contract Status**: âœ“ COMPLETE

**CRITICAL Findings** (design-level only):
(if any, list with concrete fix â€” tag each as [Task] or [Pre-existing])

**HIGH Findings** (design-level only):
(if any, list with concrete fix â€” tag each as [Task] or [Pre-existing])

**MEDIUM Findings** (design-level only):
(if any, list with mitigation â€” tag each as [Task] or [Pre-existing])

**Assessment**: [Summary of design soundness]

Open Questions:
(list any clarifications needed from the user, or "none")

---

## GATE STATUS: ðŸŸ¢ GREEN / ðŸŸ¡ YELLOW / ðŸ”´ RED

**Rationale**: [Explanation of gate decision]

<!-- WORKFLOW_GATE: GREEN | CRITICAL_OPEN: 0 | HIGH_OPEN: 0 | MEDIUM_OPEN: 0 -->
```

> Replace GREEN with YELLOW or RED as appropriate. Fill finding counts accurately â€”
> the orchestrator reads this comment to decide routing.

## Gate Criteria

- [ ] Contract from Stage 1 is complete
- [ ] Design approach is algorithmically sound
- [ ] Async patterns align with codebase
- [ ] Error handling is explicit
- [ ] Type hints strategy is feasible
- [ ] Test plan covers acceptance criteria
- [ ] Proposed implementation is minimal for the requirement
- [ ] Proposed naming is clear and maintainable

**Return GREEN if sound. Return YELLOW if sound with logged findings. Return RED if
design has blockers.**

## Gate Rules

- **GREEN**: Proceed to Stage 3.
- **YELLOW**: Proceed to Stage 3, but log findings.
- **RED**: Return contract to Stage 1 for revision. Do not proceed to Stage 3.

## Progress Tracking

Append to `.claude/workflow-state/progress.md` — do not overwrite. Write at least
three entries: START, one per major step, and DONE. Format:

```text
[Stage 2 — Design Review] START → <one-sentence task description>
[Stage 2 — Design Review] <Verb> — <what you are doing>
[Stage 2 — Design Review] DONE → GATE: {GATE} | FINDINGS: {CRITICAL}/{HIGH}/{MEDIUM} | AMBIGUITY: YES|NO
```

Examples:

```text
[Stage 2 — Design Review] START → Pre-implementation review of retry logic design
[Stage 2 — Design Review] Read — reviewing SA handoff and in-scope files
[Stage 2 — Design Review] Analyse — checking async patterns, error handling, type hints
[Stage 2 — Design Review] DONE → GATE: GREEN | FINDINGS: 0/1/2 | AMBIGUITY: NO
```

## AGENT_SUMMARY Block

The PM reads only this block — not the full handoff prose. Append this as the
**absolute last output**, after the `<!-- WORKFLOW_GATE -->` comment.

Field derivation:

- `STAGE`: always `TD-design`
- `GATE`: match the WORKFLOW_GATE value
- `AC_TOTAL`, `AC_WITH_TESTS`, `TESTS_PASSING`, `TESTS_FAILING`: carry forward from
  the SA AGENT_SUMMARY (no tests written or run at this stage)
- `OPEN_CRITICAL/HIGH/MEDIUM`: from the WORKFLOW_GATE finding counts
- `FILES_MODIFIED`: always `none` (design reviewer does not modify code files)
- `OPEN_QUESTIONS`: `YES` if Open Questions section has content; `NO` otherwise
- `FAILURE_SUMMARY`: describe blocking design issues; `none` if GATE=GREEN
- `DESIGN_AMBIGUITY_RESOLVED`: `YES` if all design ambiguities flagged in the SA
  AGENT_SUMMARY have a clear, specific recommendation in this review; `NO` if any
  ambiguity remains unresolved or has an "either/or" with no recommendation
- `APPROVED_TO_PROCEED`: `YES` if GATE is GREEN or YELLOW; `NO` if GATE is RED

```text
<!-- AGENT_SUMMARY
STAGE: TD-design
AGENT: Code Reviewer
GATE: GREEN | YELLOW | RED
AC_TOTAL: [carry forward from SA]
AC_WITH_TESTS: 0
TESTS_PASSING: 0
TESTS_FAILING: 0
OPEN_CRITICAL: [count]
OPEN_HIGH: [count]
OPEN_MEDIUM: [count]
FILES_MODIFIED: none
OPEN_QUESTIONS: YES | NO
FAILURE_SUMMARY: [blocking design issues, or "none" if GATE=GREEN]
DESIGN_AMBIGUITY_RESOLVED: YES | NO
APPROVED_TO_PROCEED: YES | NO
-->
```

## Next

When run via the PM loop, output is passed automatically.
For standalone use, copy this review into the next stage prompt.

If RED, the PM will not proceed to developer/red until design issues are resolved.
