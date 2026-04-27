# Python Coding Standards

These instructions apply to all Python code generated or reviewed by GitHub Copilot
in this workspace.

---

## 0. Foundational Design Principles

All code in this workspace is guided by these foundational principles. Every design decision should be evaluated against them.

### Classic Principles

- **DRY (Don't Repeat Yourself)** — Every piece of logic or knowledge should exist in one place only. If you find yourself copying code, extract it into a function or module.
- **KISS (Keep It Simple, Stupid)** — Always prefer the simplest solution that solves the problem. Complexity is a liability; introduce it only when truly necessary.
- **YAGNI (You Aren't Gonna Need It)** — Don't build features or abstractions "just in case". Build what is needed now, when it's needed.
- **SoC (Separation of Concerns)** — Each module, class, or function should address one distinct concern. Mixing unrelated responsibilities makes code harder to understand and change.

### SOLID Principles

- **S — Single Responsibility** — A class or module should have one, and only one, reason to change. If it does two things, split it.
- **O — Open/Closed** — Code should be open for extension but closed for modification. Add new behaviour by extending, not by editing existing code.
- **L — Liskov Substitution** — A subclass should be usable anywhere its parent class is expected, without breaking the program.
- **I — Interface Segregation** — Don't force a class to implement methods it doesn't use. Prefer several small, focused interfaces over one large general one.
- **D — Dependency Inversion** — High-level modules should not depend on low-level modules. Both should depend on abstractions (interfaces), not concrete implementations.

---

## 1. Programming Style

- **PEP 8** as the style guide. Line length ≤ 120 characters.
- Type hints everywhere. Docstrings for all public classes and functions.
- f-strings for formatting. Avoid global state. Keep functions small and focused.
- **Object-oriented** by default. Use standalone functions or static methods for
  utilities and pure functions where OOP adds no value.
- Use simple, intuitive names for variables, functions, classes, and modules. Avoid
  abbreviations unless widely understood. The name should clearly convey purpose and
  intent.
- Comment generously — especially around complex logic, design decisions, and any
  non-obvious behaviour. Assume the reader may be new to the codebase.
- Review the existing folder structure and naming conventions before adding new files.
  Follow established patterns. Refactors should improve consistency across the project.

---

## 1A. Scope Control and Minimality

- Default to the **smallest change that fully solves the stated problem**.
- Prefer modifying existing code over introducing new files, modules, classes,
  wrappers, configuration layers, or helper utilities.
- Do not add architecture for anticipated future needs unless the user explicitly asks
  for extensibility or the current requirement cannot be solved cleanly without it.
- Avoid adjacent cleanup, opportunistic refactors, and broad renames unless they are
  required for correctness.
- If a problem can be solved with:
  1. a local edit in an existing function or class,
  2. a small helper in the same file, or
  3. a new abstraction,
  choose the first viable option.
- Keep diffs narrow. For small fixes, avoid spreading changes across many files unless
  there is a clear technical reason.
- Before creating a new file or public abstraction, verify that an existing location
  cannot accommodate the change cleanly.
- When there is a trade-off between reuse and simplicity, prefer simplicity unless the
  duplication is already causing a concrete problem in this codebase.
- If extra hardening, debug plumbing, deployment setup, or broader refactoring would be
  helpful but is not required, stop and ask before adding it.

---

## 1B. Simplicity, Naming, and Maintainability Gates

- Prefer the implementation with the **fewest moving parts** when two options satisfy
  the same requirements.
- Keep functions and classes focused; if code needs lengthy comments to explain basic
  flow, simplify the flow first.
- Use descriptive names that explain intent (`retry_delay_seconds`) instead of
  abbreviations (`rds`) unless the abbreviation is standard in the domain.
- Avoid speculative helpers or wrapper layers created "for future reuse" unless a real
  current duplication problem exists.
- Every change should preserve or improve maintainability by making at least one of
  these better: readability, testability, or responsibility boundaries.
- During reviews, explicitly flag:
  1. avoidable complexity,
  2. ambiguous names,
  3. high-churn code patterns that will be costly to maintain.

---

## 1C. Temporary File Cleanup

- **Always clean up temporary files** created for a specific task before the work is
  considered complete.
- Temporary files include: smoke tests, scratch scripts, debug dumps, intermediate
  builds, test fixtures created for one-off validation, or any artifact generated
  during development that is not part of the final deliverable.
- Cleanup is **mandatory**: do not leave temporary files in the workspace after a task
  finishes or before marking work complete.
- If deletion is blocked by system policy (e.g. permission error), use Python cleanup
  (`Path('file').unlink()`) or flag the issue explicitly to the user.
- Prefer running verification logic inline (e.g. in existing test suite) rather than
  creating throwaway scripts.
- When in doubt: if you created it for testing/debugging and it's not part of the
  delivered codebase, remove it.

---

## 1D. Task Completion Format

When marking a task as complete, present a **clear, readable summary** before the
formal completion marker. Use this format:

```markdown
## ✅ Task Complete

**What was accomplished:**
- Bullet point 1: Clear description
- Bullet point 2: Clear description
- Bullet point 3: Clear description (if applicable)

**Files modified:** List of key files touched

**Verification:** Brief note on how completion was verified (tests run, file checks, etc.)
```

Then mark complete with the formal tool call. This ensures users see a **clean, readable
summary** rather than machine-readable XML tags.

- Never print tool-call wrappers in chat output (e.g., `<task_complete>`,
  `</task_complete>`, `<parameter ...>`). Those are internal and must not appear in
  user-visible responses.

---

## 1E. Clarification Protocol

When you encounter **ambiguity, open questions, or multiple valid approaches**, do not
guess or assume. Use the `vscode_askQuestions` tool to ask the user before proceeding.

- Present **one question at a time** (or a small focused batch if they are closely
  related).
- Always provide **selectable options** with `options` and set `multiSelect: true` when
  more than one choice may apply.
- Set `allowFreeformInput: false` when the choices are exhaustive and free text would
  not add value. Leave it `true` only when the user may need to provide context beyond
  the listed options.
- Keep option labels short and self-explanatory; use the `description` field for extra
  detail.
- Mark the recommended default with `recommended: true` when you have a clear
  preference.

**When to ask:**
- The task description is vague or could be interpreted in multiple ways.
- Multiple implementation strategies exist with meaningfully different trade-offs.
- Scope is unclear (which files, which behaviour, which edge cases).
- A design decision has lasting consequences (new public API, schema change, naming).

**When NOT to ask:**
- The task is unambiguous and has a single obvious solution.
- The answer is already documented in coding standards or prior handoff.
- You can resolve the ambiguity by reading existing code or tests.

---

## 2. File Size & Modularity (Python)

- **Soft limit: 500 lines.** If a file is approaching this, consider whether it has
  grown beyond a single responsibility.
- **Hard limit: 750 lines.** Files exceeding this must be split before merging.
- **Split by responsibility, not by line count.** Line count is a proxy — the real
  signal is when a file contains unrelated classes, functions, or concerns.
- **Prefer domain-based splits.** Instead of one large `utils.py`, use
  `utils/formatting.py`, `utils/validation.py`, etc.
- **Test files may be longer** (up to ~750–1000 lines) given their repetitive nature,
  but should still be split by the module they test.

When in doubt, ask: could a new developer understand the purpose of this file from its
name and first 20 lines? If not, it needs to be refactored.

---

---

## 3. Logging

- Use the standard Python `logging` module throughout.
- `logging.getLogger(__name__)` in every module.
- `logging.basicConfig` and root logger setup only in the entrypoint (e.g. `main.py`).
- Never configure logging inside library code or reusable classes.
- Subclasses never redefine `self.logger` — the base class owns it.
- Logs must be short — aim for ≤ 80 characters per line.

### Log levels

| Level     | Use for                                                        |
|-----------|----------------------------------------------------------------|
| `DEBUG`   | Raw inputs, intermediate data structures, verbose detail       |
| `INFO`    | Stage transitions, operation start/finish, validation results  |
| `WARNING` | Recoverable issues: retry triggered, fallback used             |
| `ERROR`   | Unrecoverable failures: operation gave up, write failed        |

---

## 4. Async

- Prefer **async** for any I/O-bound work: network requests, file reads, external APIs.
- Use `asyncio` and `async`/`await` throughout. Avoid mixing sync and async code in the
  same execution path.
- If a component wraps a sync-only library, isolate it with `asyncio.to_thread()` so
  it does not block the event loop. Keep these wrappers thin and clearly documented.

---

## 5. Error Handling and Resilience

- **Rate limits (HTTP 429)**: use exponential backoff with jitter. Respect the
  `Retry-After` header if present.
- **Timeouts**: set a per-call timeout in config; on timeout, retry once before failing.
- **Malformed responses**: treat unparseable output as a transient error and retry once.
- **Circuit breaking**: if an operation fails N consecutive times (configurable), stop
  retrying and surface a clear error rather than looping indefinitely.
- Log every failure with enough context to diagnose: status, response (truncated),
  elapsed time, attempt number.

---

## 6. Testing

### Test categories

- **Unit tests**: test validators, deterministic transforms, and logic with mocked
  dependencies. Use `pytest` + `pytest-asyncio`. Fast — run on every change.
- **Integration tests**: test full round-trips against real external services. Run on a
  schedule, not on every commit. Mark with `@pytest.mark.integration`.
- **Snapshot tests**: compare generated output against a known-good baseline. Update
  baselines deliberately. Mark with `@pytest.mark.snapshot`.

Every new module or function should ship with at least one unit test.

### Test layout

Tests mirror the source tree under `tests/`:

```
tests/
├── unit/          # fast, no network, mocked dependencies
├── integration/   # real services, slow
├── snapshots/     # baseline files for snapshot tests
└── conftest.py    # shared fixtures
```

### Mandatory test-on-every-change protocol

Every code change — new feature, bug fix, refactor — must go through this sequence
before it is considered complete:

1. **Identify the test.** Determine which test covers the change. If one exists, review
   and update it. If none exists, create one.
2. **Write or update the test.** It must exercise the specific behaviour being changed.
   For bug fixes, it must reproduce the bug (fail before the fix, pass after).
3. **Run the target test** to confirm it passes:
   `pytest tests/unit/test_<module>.py::<test_function> -v`
4. **Run the full regression suite** to catch regressions:
   `pytest tests/unit/ -v --tb=short`
5. **Fix any failures.** Do not leave the suite red.

The change is not done until step 5 passes clean.

### Running tests

```bash
# Single test
pytest tests/unit/test_<module>.py::<test_function> -v

# All unit tests
pytest tests/unit/ -v --tb=short

# Integration tests
pytest tests/integration/ -v -m integration

# Snapshot tests
pytest tests/ -v -m snapshot
```