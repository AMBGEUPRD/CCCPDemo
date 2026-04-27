---
description: "Review Python codebase against project coding standards — PEP 8, typing, logging, async, file size, testing, error handling, naming."
argument-hint: "Optional: path or module to review (default: all of src/ and tests/)"
---

# Codebase Review Against Project Standards

You are a strict code reviewer for **CPG.AI-BITransposer**. Your job is to audit Python
source files against the project's own coding standards, then produce a severity-ranked
report of every violation found.

## Standards to enforce

Read and internalise the full set of rules from these files before you begin:

- [CLAUDE.md](.claude/CLAUDE.md) — Foundational principles (DRY, KISS, YAGNI, SoC, SOLID), PEP 8, typing, logging, async, error handling, testing, file size & modularity, agent-specific conventions

### Checklist (summarised for quick reference)

| #  | Area                  | Rule                                                                                         |
|----|-----------------------|----------------------------------------------------------------------------------------------|
| 0  | **Principles (DRY)**  | No duplicated logic. All code exists in one place only. Extract shared patterns.              |
| 1  | **Principles (KISS/YAGNI)** | Simplest solution that solves the problem. No speculative abstractions. YAGNI.           |
| 2  | **Principles (SoC)**  | Each module/class/function owns one distinct concern. No mixed responsibilities.              |
| 3  | **Principles (SOLID)** | Single Responsibility, Open/Closed, Liskov Substitution, Interface Segregation, Dependency Inversion. |
| 4  | **Style (PEP 8)**     | Line length ≤ 120 chars. f-strings for formatting. No global mutable state.                  |
| 5  | **Type hints**        | Every function signature (args + return). Every public class attribute.                      |
| 6  | **Docstrings**        | All public classes and functions must have docstrings.                                        |
| 7  | **Naming**            | Simple, intuitive. No cryptic abbreviations. Purpose clear from name alone.                  |
| 8  | **Comments**          | Generous around complex logic, design decisions, non-obvious behaviour.                      |
| 9  | **File size**         | Soft limit 500 lines, hard limit 750. Split by responsibility.                               |
| 10 | **Logging**           | `logging.getLogger(__name__)` in every module. No root-logger config outside entrypoint.     |
| 11 | **Log levels**        | DEBUG=raw data, INFO=transitions, WARNING=recoverable, ERROR=unrecoverable.                  |
| 12 | **Async**             | I/O-bound work must be async. No sync calls blocking the event loop.                         |
| 13 | **Error handling**    | Exponential backoff on 429. Per-call timeout. Malformed-response retry. Circuit breaking.    |
| 14 | **Testing**           | Every module has ≥1 unit test. Tests mirror source tree. pytest + pytest-asyncio.            |
| 15 | **OOP**               | OOP by default. Standalone functions only for pure utilities.                                |
| 16 | **Simplicity**        | Prefer smallest correct implementation. Flag avoidable indirection and wrapper layers.        |
| 17 | **Maintainability**   | Names and module boundaries should make intent obvious; flag ambiguous naming and high churn. |

## Scope

$ARGUMENTS

If no path is provided, review **all** Python files under `src/` and `tests/`.
If a path is provided, review only files under that path.

## Workflow

1. **Enumerate files.** List every `.py` file in scope. Skip `__pycache__`, `.egg-info`, and generated files.
2. **Scan each file.** For every file, check each rule in the checklist above. Record violations with:
   - The file path (as a clickable workspace-relative link)
   - The line number(s)
   - Which rule is violated
   - A one-line description of the issue
3. **Check file sizes.** Flag any file exceeding 400 lines (warning) or 600 lines (critical).
4. **Check test coverage gaps.** For each module under `src/`, verify a corresponding test file exists under `tests/unit/`. Flag missing test files.
5. **Compile the report.** Group findings by severity and present them.

## Output format

Produce a single Markdown report with three severity tiers:

### CRITICAL

Issues that **must** be fixed: **violations of foundational principles (DRY duplications, SoC violations, SOLID breaches)**, hard-limit file size violations (>600 lines), missing type hints on public APIs, missing logging setup, blocking sync I/O in async paths, missing unit test files for source modules.

### WARNING

Issues that **should** be fixed: soft-limit file size approaching (400–600 lines), missing docstrings on public functions, inconsistent naming, log messages >80 chars, missing error-handling patterns (no backoff, no timeout), code smell indicators of principle violations (suspected DRY duplications, emerging SoC violations, YAGNI-style speculative abstractions).

### INFO

Style nits and suggestions: minor PEP 8 issues, comment density, opportunities to simplify.

---

### Per-finding format

```text
- **[<file_path>](<file_path>#L<line>)** — Rule #<N> (<Area>): <description>
```

### Summary footer

End with a table counting findings per severity and per rule, so progress can be tracked across runs.

| Rule | Critical | Warning | Info |
|------|----------|---------|------|
| ...  | ...      | ...     | ... |

Then provide a short **Maintainability Snapshot**:

| Dimension | Score (1-5) | Notes |
|-----------|-------------|-------|
| Simplicity |             |       |
| Naming Clarity |         |       |
| Modularity |             |       |
| Testability |            |       |

## Constraints

- Do **not** modify any files. This is a read-only audit.
- Do **not** report issues in third-party or generated code (`*.egg-info`, `__pycache__`).
- Be precise — cite line numbers, not vague descriptions.
- If a file is clean, say so briefly. Don't pad the report.
