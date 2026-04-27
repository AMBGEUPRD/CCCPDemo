---
description: "Stage 3 of 6: Implementation. Write code and tests targeting acceptance criteria."
---

# Stage 3: Implementation

## Input

Receive handoff from prior stages (provided by the dispatcher or pasted manually).
If a **Findings Ledger** or **Findings to Resolve** section is provided, treat every
OPEN CRITICAL/HIGH finding as an additional requirement to fix alongside the acceptance
criteria.

## Hard Scope Constraint â€” Read This First

**You may ONLY modify files listed under `In-Scope Files` in the Stage 1 handoff.**

The out-of-scope files are listed explicitly in the handoff. Do not touch them even
if it seems convenient. If you believe a file must be modified that is not in scope,
add it to your `Open Questions` section â€” do not edit it unilaterally.

Before reporting IMPLEMENTATION COMPLETE, run `git diff --name-only` (or equivalent)
and verify every changed file appears in the In-Scope Files list. If any out-of-scope
file was modified, undo the change or explain it explicitly.

## Work

1. Read the in-scope files.
2. Implement changes **only** in in-scope files.
3. Target each acceptance criterion with code.
4. **Resolve all OPEN findings** from the Findings Ledger (CRITICAL and HIGH are
   mandatory; MEDIUM is best-effort). For each resolved finding, note exactly what
   was changed.
5. Add/update tests for each criterion and each resolved finding.
6. Run: `pytest tests/unit/ -v --tb=short`
7. Run `git diff --name-only` and verify only in-scope files were modified.
8. Keep naming explicit and domain-oriented; avoid ambiguous abbreviations.

## Output Format

```markdown
## IMPLEMENTATION COMPLETE

Files Modified:
- [path]: [lines added/modified]
- [path]: [lines added/modified]

Scope Check (git diff --name-only):
- [path] â€” IN SCOPE âœ“
- [path] â€” IN SCOPE âœ“

Test Results:
âœ“ test_1_name
âœ“ test_2_name
âœ“ test_3_name
âœ“ test_4_name
âœ“ test_5_name

Full Test Suite: [N] passed, [0] failed

Acceptance Criteria Mapping:
1. [Criterion] â†’ [Code location/test]
2. [Criterion] â†’ [Code location/test]
3. [Criterion] â†’ [Code location/test]
4. [Criterion] â†’ [Code location/test]
5. [Criterion] â†’ [Code location/test]

Findings Resolved:
- [F-NNN] [Description]: [What was changed to fix it]
(or "No findings in ledger")

Unresolved Findings:
- [F-NNN] [Description]: [Why it could not be resolved â€” be specific]
(or "none")

Unresolved Risks:
(from Stage 1 handoff; are they still active?)

Open Questions:
(list any clarifications or files that need scope expansion, or "none")

---

## GATE STATUS: ðŸŸ¢ GREEN / ðŸŸ¡ YELLOW / ðŸ”´ RED

**Rationale**: [Explanation]

<!-- WORKFLOW_GATE: GREEN | CRITICAL_OPEN: 0 | HIGH_OPEN: 0 | MEDIUM_OPEN: 0 -->
```

> Fill OPEN counts with unresolved findings from the Findings Ledger that you could
> not fix. GREEN requires all tests passing and all CRITICAL/HIGH resolved.

## Gate Criteria

- [ ] All changes are in in-scope files only (verified by git diff)
- [ ] Each acceptance criterion targeted with code
- [ ] All required tests are written
- [ ] All required tests pass
- [ ] No new regressions in existing tests
- [ ] Names for new/changed symbols are clear and intention-revealing
- [ ] No unnecessary helper/wrapper layers were introduced
- [ ] All CRITICAL/HIGH findings from the Findings Ledger are resolved or justified

**Return GREEN if all tests pass and all CRITICAL/HIGH findings are resolved. Return
YELLOW if minor items remain. Return RED if tests fail, criteria not met, or CRITICAL
findings unresolved.**

## Progress Tracking

Write brief progress updates to `.claude/workflow-state/progress.md` as you work.
Append each line — do not overwrite. Format:

```text
[Stage 3 — Implementation] <what you are doing or just completed>
```

Write at least one update when you start and one when you finish. For multi-step work,
write one update per major step (e.g., "Reading files", "Implementing retry logic",
"Running pytest"). This lets the user watch the file live in their editor.

## Next

When run via the dispatcher, the output is passed automatically.
For standalone use, copy this output into the next stage prompt.

If RED, fix the failures and re-run. Do not proceed to Stage 4 until GREEN.
