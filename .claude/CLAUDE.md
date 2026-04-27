# Coding Standards — CPG.AI-BITransposer

These standards apply to all agents and code in this repository. Agent-specific
instructions live in `.claude/agents/`.

---

## 1. Programming Style

- **PEP 8** as the style guide. Line length ≤ 120 characters.
- Type hints everywhere. Docstrings for all public classes and functions.
- f-strings for formatting. Avoid global state. Keep functions small and focused.
- **Object-oriented** by default — the agent class is the natural unit of
  encapsulation. Use standalone functions or static methods for utilities and pure
  functions where OOP adds no value.
- Use Microsoft AI best practices for Azure SDK usage, error handling, and async
  programming.
- Be mindful of performance and cost: batch LLM calls when possible, avoid unnecessary
  calls, cache results if they will be reused.
- Review the existing folder structure and naming conventions before adding new files.
  Follow established patterns for agent design, prompt construction, and output
  validation. Refactors should improve consistency across the project.
- Use simple, intuitive names for variables, functions, classes, and modules. Avoid
  abbreviations unless widely understood. The name should clearly convey purpose and
  intent.
- Comment generously — especially around complex logic, design decisions, and any
  non-obvious use of Azure services or LLM features. Assume the reader may be new to
  Azure AI Foundry or the specific challenges of Tableau → Power BI migration.

---

## 1A. Scope Control and Minimality

- Default to the **smallest change that fully solves the stated problem**.
- Prefer modifying existing code over introducing new files, modules, classes,
  wrappers, orchestration layers, or helper utilities.
- Do not add architecture for speculative future requirements unless the user
  explicitly asks for extensibility or the current requirement cannot be solved cleanly
  without it.
- Avoid adjacent cleanup, opportunistic refactors, and broad renames unless they are
  required for correctness.
- For implementation choices, prefer this order:
  1. a local edit in an existing function or class,
  2. a small helper in the same file,
  3. a new abstraction only if the first two are insufficient.
- Keep diffs narrow. Small fixes should usually stay local rather than propagating
  through multiple files.
- Before creating a new public abstraction, file, or configuration surface, verify that
  an existing location cannot hold the change cleanly.
- When there is a trade-off between generality and simplicity, prefer simplicity
  unless the broader design is required by the current task.
- Additional hardening, observability, deployment setup, or production scaffolding must
  be justified by the request, not added by default.

---

## File Size & Modularity

Keep Python files focused and appropriately sized:

- **Soft limit: 500 lines.** If a file is approaching this, consider whether it has grown beyond a single responsibility.
- **Hard limit: 750 lines.** Files exceeding this must be split before merging.
- **Split by responsibility, not by line count.** Line count is a proxy — the real signal is when a file contains unrelated classes, functions, or concerns.
- **Prefer domain-based splits.** Instead of one large `utils.py`, use `utils/formatting.py`, `utils/validation.py`, etc.
- **Test files may be longer** (up to ~750–1000 lines) given their repetitive nature, but should still be split by the module they test.

> When in doubt, ask: *could a new developer understand the purpose of this file from its name and first 20 lines?* If not, it's time to refactor.

---

## 2. Logging

Use the standard Python `logging` module throughout.

- `logging.getLogger(__name__)` in every module.
- `logging.basicConfig` and any root logger setup only in the entrypoint (`main.py`).
- Never configure logging inside library code or agent classes.
- Subclasses never redefine `self.logger` — the base class owns it.

### Format and length
- Logs must be short — aim for ≤80 characters per line; split longer messages across
  multiple log calls.
- Align to the uvicorn format style:
  `INFO:     Waiting for application startup.`
- Use short paths — file name or last 2–3 directory levels:
  `Tableau2PowerBI/core/config.py`
  not
  `C:\Users\salvatore.a.bono\CPG.AI-BITransposer\src\Tableau2PowerBI\core\config.py`

### Log levels

| Level     | Use for                                                        |
|-----------|----------------------------------------------------------------|
| `DEBUG`   | Raw prompts, raw LLM responses, intermediate data structures   |
| `INFO`    | Stage transitions, agent start/finish, validation pass/fail    |
| `WARNING` | Recoverable issues: retry triggered, fallback used, slow call  |
| `ERROR`   | Unrecoverable failures: agent gave up, file write failed       |

---

## 3. Async

Prefer **async** for any I/O-bound work: LLM calls, file reads, network requests.
Use `asyncio` and `async`/`await` throughout. Avoid mixing sync and async code in the
same execution path.

If a component wraps a sync-only library (e.g., an XML parser), isolate it with
`asyncio.to_thread()` so it does not block the event loop. Keep these wrappers thin and
clearly documented.

---

## 4. Error Handling and Resilience

Beyond validation retries, handle infrastructure-level failures explicitly:

- **Rate limits (HTTP 429)**: use exponential backoff with jitter. Respect the
  `Retry-After` header if present.
- **Timeouts**: set a per-call timeout in config; on timeout, retry once with the same
  prompt before failing.
- **Malformed responses** (not a validation failure but unparseable output — e.g.,
  truncated JSON): treat as a transient error and retry once.
- **Circuit breaking**: if an agent fails N consecutive calls (configurable), stop
  retrying and surface a clear error to the orchestrator rather than burning tokens.

Log every failure with enough context to diagnose: HTTP status, response body
(truncated), elapsed time, attempt number.

---

## 5. Testing

### Test categories

- **Unit tests**: test validators, deterministic transforms, and prompt-assembly logic
  with mocked LLM responses. Use `pytest` + `pytest-asyncio`. These are fast and run
  on every change.
- **Integration tests**: test full agent round-trips against a real model endpoint for
  a small set of representative workbooks. These run in CI on a schedule, not on every
  commit. Mark them with `@pytest.mark.integration`.
- **Snapshot tests**: for TMDL and PBIP output — compare generated output against a
  known-good baseline. Update baselines deliberately, not silently. Mark them with
  `@pytest.mark.snapshot`.

Every new agent or validator should ship with at least one unit test.

### Test layout

Tests mirror the source tree under `tests/`:
```
tests/
├── unit/          # fast, no network, mocked LLM
├── integration/   # real model endpoint, slow
├── snapshots/     # baseline files for snapshot tests
└── conftest.py    # shared fixtures
```

### Mandatory test-on-every-change protocol

**This is a hard rule.** Every code change — new feature, bug fix, refactor — must go
through this sequence before it is considered complete:

1. **Identify the test.** Before writing any production code, determine which test file
   and test function covers the change. If one exists, it will be reviewed and updated.
   If none exists, a new one will be created.
2. **Write or update the test.** The test must exercise the specific behaviour being
   added or changed. For bug fixes, the test must reproduce the bug (fail before the
   fix, pass after).
3. **Run the target test.** Execute only the new/updated test to confirm it passes:
   `pytest tests/unit/test_<module>.py::<test_function> -v`
4. **Run the full regression suite.** Once the target test passes, run all unit tests
   to catch regressions:
   `pytest tests/unit/ -v --tb=short`
5. **Fix any failures.** If any existing test breaks, fix it before moving on. Do not
   leave the suite red.

The change is not done until step 5 passes clean. No exceptions.

### Running tests

```bash
# Single test
pytest tests/unit/test_validator.py::test_column_names -v

# All unit tests (the regression gate)
pytest tests/unit/ -v --tb=short

# Integration tests (requires live endpoint)
pytest tests/integration/ -v -m integration

# Snapshot tests
pytest tests/ -v -m snapshot
```