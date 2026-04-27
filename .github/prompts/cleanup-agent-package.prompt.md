description: "Audit and mechanically clean up a single agent package — dead code, thin files, redundant post-processing."
agent: "Tableau2PBIHelper"
argument-hint: "Agent folder name, e.g. dax_measures, semantic_model, functional_doc"
model: ["Claude Opus 4.6 (copilot)", "GPT-5 (copilot)"]
tools:
  - search
  - read
  - edit
  - execute
---

# Agent Package Cleanup

You are cleaning up the agent package at `src/Tableau2PowerBI/agents/$ARGUMENTS/`.

Follow this exact sequence:

## 1. Inventory

- List every `.py` file with line counts.
- For each file, summarise its single responsibility in one sentence.
- Flag files under 50 lines — candidates for inlining.
- Flag files over 500 lines — candidates for splitting.

## 2. Dead code

- Identify functions/classes that are defined but never imported or called
  anywhere in the repo (grep across `src/` and `tests/`).
- Identify imports that are unused within each file.
- List any parameters that are accepted but always passed the same value
  or never passed at all (dead options).

## 3. Redundant post-processing

- Trace the data flow from LLM response → validation → disk write.
- List every transformation/fixup/repair pass applied to the LLM output.
- For each pass, classify it:
  - **Deterministic** — could be done in code without seeing LLM output
    (GUIDs, enums, folder structure, schema refs).
  - **Compensating** — fixes something the LLM should have gotten right
    (field names, JSON structure, truncation recovery).
  - **Duplicate** — same logic exists in a sub-agent or earlier stage.
- Report which passes are redundant or misplaced.

## 4. Execute cleanup (Phase 1 only)

Apply ONLY safe, mechanical deletions — no architectural changes:

- Delete files under 50 lines; inline their content into the caller.
- Remove dead functions, dead imports, dead parameters.
- Remove duplicate post-processing passes (keep the one closest to the
  source, i.e. in the sub-agent or generator, not the parent).
- Update `__init__.py` re-exports.
- Update or remove corresponding tests for deleted code.
- Do NOT delete test coverage for functions that still exist.

## 5. Validate

- Run the agent's own tests: `pytest tests/unit/agents/test_$ARGUMENTS*.py -v`
- Run full regression: `pytest tests/unit/ -v --tb=short`
- Both must pass with 0 failures before the task is complete.

## 6. Report

After cleanup, print a table:

| File | Lines Before | Lines After | Change |

Then list what was deleted/inlined and why.

Do NOT proceed to Phase 2 (moving deterministic work out of LLM) or
Phase 3 (evaluating LLM necessity). Only do the mechanical cleanup.
