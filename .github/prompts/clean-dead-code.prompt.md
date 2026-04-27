description: "Find and remove dead code — temp files, unused imports, unreachable functions, orphaned modules, and other remnants of past changes."
agent: "Python Solution Reviewer"
argument-hint: "Optional: path or module to clean (default: workspace root, src/, and tests/)"
model: ["Claude Opus 4.6 (copilot)", "GPT-5 (copilot)"]
tools:
  - search
  - read
   - edit
  - execute
---

# Dead-Code Cleanup

You are a meticulous code janitor for a Python project.
Your single goal is to **find and remove dead code** so the codebase stays lean and readable.

> **Critical instruction:** This prompt has THREE passes. You MUST complete all three.
> Do NOT stop after removing unused imports — that is only Pass 2. Pass 3 (unused
> functions and dead files) is the most valuable part of this cleanup.

## What counts as dead code

| Category | Scope | Examples |
|----------|-------|---------|
| **Temporary / scratch files** | Workspace root | `_*.py` one-off scripts, `*.txt` test output dumps, files with "temporary" or "scratch" in their docstring |
| **Dead / orphaned Python files** | `src/`, `tests/` | `.py` files not imported or invoked by any other file in the project and not a CLI entrypoint |
| **Unused imports** | Per-file | `import os` when `os` is never referenced |
| **Unreachable code** | Per-file | Code after unconditional `return`, `raise`, `break`, or `sys.exit()` |
| **Unused functions / methods** | Cross-project | Defined but never called anywhere in the project |
| **Unused classes** | Cross-project | Defined but never instantiated or subclassed anywhere |
| **Unused variables** | Per-file | Assigned but never read; loop variables that shadow and discard |
| **Unused class attributes** | Cross-project | Set in `__init__` but never accessed by any method or external code |
| **Commented-out code** | Per-file | Blocks of commented-out Python (not explanatory comments) |
| **Leftover debug / temp code** | Per-file | `print()` debugging, `breakpoint()`, obsolete `TODO`-gated stubs |
| **Unused parameters** | Per-file | Params never used in the body (**flag only** — do not remove if part of an ABC/protocol interface) |
| **Stale constants / config keys** | Per-file | Module-level names never referenced |

## What to preserve

- **Public API:** symbols listed in `__all__` or documented as public.
- **Test infrastructure:** fixtures and helpers in `conftest.py`, `support.py`, or files under `tests/` — even if they look unused, pytest discovers them dynamically.
- **ABC / protocol methods** overridden by subclasses.
- **CLI entrypoints** registered in `pyproject.toml` `[project.scripts]` or `[project.gui-scripts]`.
- **Tool directives:** `# noqa`, `# type: ignore`, `# pragma: no cover`.

## Scope

$ARGUMENTS

If no path is given, scan:
- **Workspace root** — for temp files and scratch artifacts.
- **`src/`** and **`tests/`** — for all Python dead code.

If a path is given, limit the scan to that path (but still check cross-project references in `src/` for unused-function analysis).

---

## Workflow — Three passes

Work through these passes **in order**. Complete each pass (present findings → apply
fixes → confirm) before moving to the next. This prevents context exhaustion.

### Pass 1 — Workspace hygiene (temp files & artifacts)

**Goal:** Remove non-source scratch files left over from development or testing.

1. List all files in the **workspace root** (not inside `src/` or `tests/`).
2. Flag files matching any of:
   - `_*.py` — convention for one-off scripts (check for a "temporary" / "scratch" / "one-off" docstring to confirm).
   - `*.txt` that contain test output, logs, or dumps (e.g. `test_results.txt`).
   - Any file whose docstring or first comment says "temporary", "scratch", "one-off", or similar.
3. **Cross-check:** make sure none of these files are imported by source code or referenced in `pyproject.toml`.
4. Present the list and ask the user to **confirm batch deletion**.
5. Delete confirmed files.

### Pass 2 — Per-file dead code (local analysis)

**Goal:** Clean intra-file dead code — fast, low-risk, no cross-project search needed.

**Categories for this pass:** unused imports, unreachable code, unused variables, commented-out code, leftover debug code, stale constants.

1. Enumerate every `.py` file in scope. Skip `__pycache__/`, `.egg-info/`, and generated files.
2. For each file, check every per-file category:
   - **Unused imports:** verify the symbol is not re-exported via `__all__` or used inside `if TYPE_CHECKING`.
   - **Unreachable code:** look for code after unconditional `return`/`raise`/`break`.
   - **Unused variables:** assigned but never read (ignore `_` convention for intentional discard).
   - **Commented-out code:** 3+ consecutive lines of commented Python (not doc comments).
   - **Debug code:** bare `print()`, `breakpoint()`, `pdb.set_trace()`.
   - **Stale constants:** module-level `UPPER_CASE` names never referenced in the file or project.
3. Apply removals directly (these are safe — local scope only).
4. After editing each file, run `ruff check <file>` to confirm no new errors.

### Pass 3 — Cross-project dead code (global analysis) ⭐

**Goal:** Find functions, methods, classes, and entire files that are defined but never used anywhere in the project. **This is the most valuable pass — do not skip it.**

#### Step 3a — Enumerate definitions

Scan all `.py` files under `src/` and collect every:
- Top-level `def <name>` and `async def <name>`
- `class <name>`
- Method definitions inside classes: `def <name>(self, ...)` and `async def <name>(self, ...)`

Record each with its file path and line number.

#### Step 3b — Search for references

For **each** definition found, search the **entire project** (`src/` and `tests/`) for references. A symbol is "referenced" if it appears in any of these patterns **outside its own definition site**:

| Pattern | Meaning |
|---------|---------|
| `name(` | Direct call |
| `.name(` | Method call |
| `.name` (no paren) | Attribute access |
| `import name` or `from module import name` | Import |
| `name,` or `name]` or `name)` | Passed as argument, in a list, etc. |
| `: name` or `-> name` | Type annotation |
| Subclass: `class Foo(name)` | Inheritance |

**Use `grep` or workspace search** for each symbol name. Search for the bare name — this casts a wide net and avoids false negatives. Then verify actual usage from the matching lines.

#### Step 3c — Apply exclusions

Do **not** flag a symbol as dead if any of these apply:
- It is listed in any `__all__`.
- It is a `@pytest.fixture` or used by pytest discovery.
- It is an ABC/protocol method with concrete overrides.
- It is a CLI entrypoint in `pyproject.toml`.
- It is a dunder method (`__init__`, `__str__`, etc.).
- It is a `@property`, `@staticmethod`, or `@classmethod` on a class that is itself used.

#### Step 3d — Check for dead files

For each `.py` file under `src/` (except `__init__.py` and CLI entrypoints):
1. Search the project for `import <module_name>` or `from <package>.<module_name>`.
2. If zero import references and the file is not a CLI entrypoint → flag as dead file.

#### Step 3e — Present and apply

Split findings into two groups:

- **Safe to remove** — zero references found, not in any exclusion list.
- **Likely dead (verify)** — very few references, or referenced only by other dead code, or only called via dynamic dispatch / `getattr`.

Apply "Safe to remove" items:
- For dead functions/methods: delete the definition. If this leaves an unused import, delete that too.
- For dead files: **ask user for individual confirmation before deleting**.
- For dead classes: delete the class. Clean up any imports of it elsewhere.

---

## After all passes

1. Run the full unit test suite: `pytest tests/unit/ -v --tb=short`
2. Fix any failures caused by the cleanup.
3. Produce a **summary table**:

```
| Pass | Category              | Items removed | Files touched |
|------|-----------------------|---------------|---------------|
| 1    | Temp files            | ...           | ...           |
| 2    | Unused imports        | ...           | ...           |
| 2    | Unreachable code      | ...           | ...           |
| 2    | Commented-out code    | ...           | ...           |
| 3    | Unused functions      | ...           | ...           |
| 3    | Unused classes        | ...           | ...           |
| 3    | Dead files            | ...           | ...           |
```

## Rules

- **Temp files and artifacts** (Pass 1): ask for batch confirmation, then delete.
- **Source files** (Pass 3): never delete an entire `.py` file without individual user confirmation.
- If removing a function breaks an import chain, fix the chain (remove the dangling import too).
- Keep diffs minimal: do not reformat or refactor surrounding code — only remove the dead parts.
- If you are unsure whether something is dead, put it in "Likely dead (verify)" — do not silently skip it.
