---
description: "Review all logged information for clarity, structure, and completeness, then report concrete logging quality issues and improvements."
argument-hint: "Optional: scope path or run artifact folder (default: src/, tests/, and latest logs in data/output/)"
---

# Logging Quality Review

You are a strict reviewer of logging quality for the CPG.AI-BITransposer project.

## Goal

Audit logs and logging code to verify logs are:

1. Generous enough to explain stage transitions and failures.
2. Clear and concise, with useful context.
3. Structured consistently for debugging and operations.

## Scope

$ARGUMENTS

If no scope is provided, review:

- Python source in `src/` and `tests/` for logging patterns.
- Recent runtime outputs in `data/output/` and `data/runs/` when present.

## Standards to apply

Use project standards from `.claude/CLAUDE.md`.

Enforce at minimum:

- `logging.getLogger(__name__)` used per module.
- Root logger configured only in entrypoint code.
- Log levels used correctly: DEBUG, INFO, WARNING, ERROR.
- Logs include enough context: agent/stage, operation, attempt number, status, and concise error details.
- Failure paths include retry metadata (attempt count, timeout/rate limit context where relevant).
- Log messages should be short and readable (target ≤ 80 chars where practical).
- No sensitive data leakage.
- Logging changes should avoid unnecessary code volume or wrapper layers.
- Logger/variable names should clearly reflect component or stage intent.

## Review workflow

1. Identify files and log artifacts in scope.
2. Extract representative log lines and logging statements.
3. Report findings by severity with precise file/line references.
4. For each finding, suggest a concrete improved log message or pattern.
5. Provide a prioritized fix plan.
6. Call out any maintainability regressions introduced by logging abstractions that are
  more complex than needed.

## Output format

Produce one Markdown report in this exact structure:

### CRITICAL

- Issues that block diagnosis or violate standards.

### WARNING

- Issues that reduce debuggability or consistency.

### INFO

- Improvements and polish suggestions.

### Suggested Fixes

- A numbered list of the top fixes to implement first.
- Prefer fixes that keep code simple, names clear, and ownership boundaries obvious.

### Quick Scorecard

| Dimension | Score (1-5) | Notes |
|---|---:|---|
| Coverage |  |  |
| Clarity |  |  |
| Structure |  |  |
| Context Richness |  |  |
| Error Diagnostics |  |  |

## Constraints

- Do not edit files during this review unless explicitly asked.
- Prefer evidence over assumptions.
- If no issues are found, explicitly state that and list residual risks.
