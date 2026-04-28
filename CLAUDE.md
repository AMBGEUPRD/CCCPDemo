# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Does

**Tableau2PowerBI** is an agentic pipeline that converts Tableau workbooks (`.twb`/`.twbx`) into Power BI Project files (`.pbip`) using LLM-powered agents on Azure AI Foundry. It ships both a CLI and a FastAPI web interface.

Coding standards, logging rules, async patterns, and the mandatory test-on-every-change protocol live in [.claude/CLAUDE.md](.claude/CLAUDE.md). Read that file before writing any code.

---

## Setup

```bash
# Base install (CLI only)
pip install -r requirements.txt

# With web interface
pip install -r requirements-webapp.txt

# With dev/test tools
pip install -r dev-requirements.txt
```

The package is installed in editable mode via `requirements.txt` (`-e .`), so source edits are immediately reflected.

---

## Common Commands

### Run the pipeline
```bash
# Full 8-stage migration
t2pbi-pipeline data/input/MyWorkbook.twbx --semantic-model-name "MyBI"

# Individual stages
t2pbi-extract data/input/MyWorkbook.twbx
t2pbi-funcdoc data/input/MyWorkbook.twbx
t2pbi-semantic data/input/MyWorkbook.twbx
t2pbi-assemble data/input/MyWorkbook.twbx
```

### Web server
```bash
t2pbi-serve          # http://localhost:8000
```

### Tests
```bash
# Single test (run this first after any change)
pytest tests/unit/test_<module>.py::<test_function> -v

# Full regression gate (must pass before a change is done)
pytest tests/unit/ -v --tb=short

# Evaluation tests (require Azure AI Foundry access)
pytest tests/evals/ -m eval -v
```

### Linting and formatting
```bash
black --line-length 120 src/ tests/
isort --profile black --line-length 120 src/ tests/
flake8 --max-line-length 120 src/ tests/
```

---

## Architecture

### Pipeline Flow

`MigrationPipeline` in [src/Tableau2PowerBI/cli/pipeline.py](src/Tableau2PowerBI/cli/pipeline.py) runs these phases:

```
Phase 0  Extract metadata (deterministic XML parsing)
           ↓ — parallel ——————————————————————
Phase 1  Functional doc          Project skeleton
           ↓
Phase 2  Target Technical Doc (TDD) — LLM designs the semantic model, DAX, visuals
           ↓ — parallel ——————————————————————————————————
Phase 3  Semantic model     DAX measures     Report visuals
           ↓
Phase 4  Assemble final PBIP project (deterministic file writer)
```

Phases 1 and 3 use `ThreadPoolExecutor`. Phase 4 is pure Python with no LLM calls. The pipeline tracks completion via `RunHistory`/`RunManifest` and supports `--resume` and `--regenerate` flags.

### Key Directories

| Path | Purpose |
|------|---------|
| `src/Tableau2PowerBI/agents/` | One subdirectory per agent; each contains the agent class and a `SKILL.md` system prompt |
| `src/Tableau2PowerBI/core/agent/` | `BaseAgent` (prompt loading, retry, backoff, circuit breaker), `DeterministicAgent`, validation logic |
| `src/Tableau2PowerBI/core/backends/` | `ModelBackend` abstraction, `ResponsesBackend` (OpenAI Responses API), `MockBackend` for tests |
| `src/Tableau2PowerBI/core/run_history/` | Run manifest, stage caching, resume logic |
| `src/Tableau2PowerBI/core/config.py` | `AgentSettings` dataclass — all config lives here, including per-agent model overrides |
| `src/Tableau2PowerBI/cli/` | CLI entry points (one file per command) |
| `src/Tableau2PowerBI/webapp/` | FastAPI app, SSE streaming routes, ADLS integration |
| `tests/unit/` | Fast mocked tests mirroring `src/` structure |
| `tests/evals/` | Live-agent evaluation tests; marked `@pytest.mark.eval` |

### Adding a New Agent

1. Create `src/Tableau2PowerBI/agents/<name>/` with an agent class and a `SKILL.md` system prompt.
2. Subclass `BaseAgent` (LLM) or `DeterministicAgent` (no LLM).
3. The base class auto-loads `SKILL.md` as the system prompt — no manual wiring needed.
4. Wire the agent into `MigrationPipeline` in `cli/pipeline.py`.
5. Add a unit test in `tests/unit/agents/test_<name>.py` using `MockBackend`.

### Configuration

`AgentSettings` in `core/config.py` is the single source of truth for all runtime config: endpoint, API version, timeouts, retry counts, per-agent model overrides. No scattered `os.getenv` calls outside that file.

### Testing Patterns

- Use `MockBackend` from `core/backends/mock.py` to inject canned LLM responses in unit tests.
- `tests/conftest.py` and `tests/unit/conftest.py` hold shared fixtures.
- Eval tests capture golden inputs with `@pytest.mark.eval_capture` and validate against baselines with `@pytest.mark.eval`.
