---
description: "Resolve a pipeline issue — prefer SKILL.md / agent-prompt fixes over Python code changes unless the Python fix is trivially obvious."
argument-hint: "Describe the failing stage, test, artifact, or workbook involved."
---

# Resolve Issue

You are troubleshooting the **CPG.AI-BITransposer** Tableau-to-Power BI migration pipeline.

## Decision hierarchy

1. **SKILL.md / agent prompt fix first.** Most output-quality problems (wrong TMDL, bad DAX, malformed PBIR JSON, missing fields) originate in the LLM instructions inside `src/Tableau2PowerBI/agents/*/SKILL.md`. Tune the prompt, add examples, tighten constraints, or clarify format rules there.
2. **Python fix only when it's a no-brainer.** Obvious bugs in deterministic code — typos, wrong dict keys, off-by-one, missing `await`, broken imports — should be fixed directly. Don't rewrite logic or refactor unless the issue cannot be solved any other way.
3. **If neither is clear, investigate first.** Reproduce the issue, inspect agent inputs/outputs in `data/output/`, read the relevant SKILL.md, and trace the data flow before proposing a change.

### Quality guardrails

- Prefer the smallest fix that resolves the root cause.
- Prefer clear, domain-specific names when introducing or changing symbols.
- Reject fixes that add avoidable wrappers or complexity without measurable benefit.

## Workflow

1. **Reproduce.** Run the failing test or pipeline stage. Capture the error or diff.
2. **Locate the root cause.** Determine whether the problem is in a SKILL.md prompt, in Python orchestration code, or in test expectations.
3. **Fix.** Apply the smallest change that resolves the issue, following the decision hierarchy above.
4. **Verify.** Run the specific test first (`pytest tests/unit/test_<module>.py::<test> -v`), then the full unit suite (`pytest tests/unit/ -v --tb=short`). The change is not done until the suite is green.

Also verify maintainability outcomes: naming clarity, minimal code footprint, and no
new indirection without a concrete need.

## Context

$ARGUMENTS
