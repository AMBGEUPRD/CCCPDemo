# Multi-Agent Workflow — How-To Guide

A practical guide to running the PM-orchestrated multi-agent workflow in Claude Code
for CPG.AI-BITransposer.

---

## What Is This Workflow?

A **Project Manager** agent drives the entire process. After each specialist completes
their work, the PM reads structured summaries and decides which agent to invoke next.
You describe what to build; the PM handles sequencing.

**Three things the PM always enforces:**

- Solution Architect defines scope and the TDD contract before any code is written.
- Developer writes failing tests first (Red phase), then production code (Green phase).
- Release Manager is the mandatory final gate before commit.

**Three things the PM decides based on context:**

- Business Analyst requirements brief — for vague or ambiguous tasks.
- Tech Lead design review — when the SA flags architectural ambiguity.
- BA coverage check and Code Reviewer quality pass — for complex tasks or after
  multiple fix cycles.

---

## Prerequisites

### 1. Claude Code CLI installed and running

The workflow uses the Agent tool to spawn subagents. You need the Claude Code CLI
or the VS Code extension active in this workspace.

### 2. Agents registered in `.claude/agents/`

| File | Agent | Used for |
|---|---|---|
| `.claude/agents/project-manager.md` | Project Manager | PM loop — every iteration |
| `.claude/agents/business-analyst.md` | Business Analyst | Requirements brief, coverage review |
| `.claude/agents/solution-architect.md` | Solution Architect | Scope + TDD contract |
| `.claude/agents/developer.md` | Developer | Red phase, Green phase, Fix iterations |
| `.claude/agents/code-reviewer.md` | Code Reviewer | Design review, quality review |
| `.claude/agents/release-manager.md` | Release Manager | Final merge gate |

### 3. Stage prompt files in `.claude/commands/multi-agent-workflow/`

`00-requirements-brief.md`, `01-architecture.md`, `02-python-pre.md`,
`03a-implementation.md`, `03b-testing.md`, `04-qa.md`, `05-python-post.md`,
`06-merge-gate.md`, `pm-loop.md`

### 4. Python environment with pytest

The Developer runs pytest during the Green phase. If missing:
`pip install pytest pytest-asyncio`

---

## Running the Workflow

### Step 1 — Invoke the workflow

With a task description:

```text
/run-multi-agent-workflow Add retry logic with exponential backoff to the DAX
measures agent. When the LLM call fails with HTTP 429 or a timeout, retry up to
3 times with jitter. Log each failed attempt at WARNING level.
```

Without (you will be asked):

```text
/run-multi-agent-workflow
```

> Be specific: which file, what current behaviour, what desired behaviour, what
> done looks like. Vague tasks trigger the Business Analyst brief step.

### Step 2 — Open the progress file in VS Code

The orchestrator prints this tip before the first PM iteration:

```text
Tip: open .claude/workflow-state/progress.md in a VS Code tab to watch live progress.
```

Do this immediately. Each agent appends updates in real time — this is your only
visibility into what is happening during the otherwise-silent thinking periods.

### Step 3 — Watch the PM decisions

Before each agent is spawned you see a one-liner:

```text
PM → solution-architect: Define scope and TDD contract for the retry logic task — SA contract required before any implementation can begin.
```

These lines show you what the PM decided, which agent is running, and why. No
confirmation needed — the PM loop proceeds automatically.

### Step 4 — Answer clarifying questions if asked

If the BA brief step runs and the task is ambiguous, the orchestrator will relay
the BA's questions directly in the chat. Answer in plain text — the orchestrator
feeds your answers back into the BA re-run before continuing.

Similarly, if any agent's `OPEN_QUESTIONS` field is `YES`, the orchestrator relays
those questions before the PM loop advances.

---

## What the PM Loop Looks Like

A typical run for a medium-complexity task:

```text
PM Loop — Iteration 1
PM → solution-architect: Define scope, acceptance criteria, and TDD test contract.

PM Loop — Iteration 2
PM → developer/red: Write all 6 required tests as failing tests.

PM Loop — Iteration 3
PM → developer/green: Implement production code to make all 6 failing tests pass.

PM Loop — Iteration 4
PM → release-manager/final: Review all uncommitted changes for scope compliance, open findings, and regressions.

Workflow complete — 4 PM iterations. Reason: All tests passing, findings clean, Release Manager approved.
```

A more complex run might include `tech-lead/design` before `developer/red`,
`developer/fix` after a failing green phase, `business-analyst/coverage` for a
large feature, and a second RM invocation after a fix.

---

## What Happens at Each PM Action

### `business-analyst/brief` (optional)

Runs when the task description is vague. The BA identifies the problem, expected
behaviour, scope signals, and definition of done — producing a structured brief
that the Solution Architect uses to write a precise contract.

If the BA has follow-up questions, the orchestrator relays them to you within the
same PM iteration before advancing.

---

### `solution-architect`

**Model: Opus** — always the first substantive action.

Produces the SA contract: in-scope files, ≥5 acceptance criteria, a TDD test
contract with Given/When/Then specs for each required test, and a risk section.

If the SA flags `DESIGN_AMBIGUITY: YES` (competing implementation approaches or
high-risk design choices), the PM will insert `tech-lead/design` before any
developer action.

---

### `tech-lead/design` (optional)

Runs when the SA flags design ambiguity. The Code Reviewer reviews the proposed
approach at design level only — algorithmic correctness, async patterns, error
handling strategy, naming. No code is written or run at this stage.

---

### `developer/red` — Red Phase

Writes **all required tests** from the SA contract as failing tests. No production
code is touched. Every required test must fail for an acceptable reason
(ImportError, AttributeError, AssertionError) before the PM advances to Green.

---

### `developer/green` — Green Phase

Writes **production code** to make all failing tests pass. Test bodies are never
modified — they are the specification. The Developer runs `pytest tests/unit/` and
confirms the full suite is green before signalling complete.

---

### `developer/fix` — Fix Iteration

Runs when tests are still failing after Green, or when open findings remain. Each
fix iteration gets a specific task card naming the failing tests or F-IDs to
address. Fix iterations write to `handoff-S3b-fix-N.md` — the original Green
handoff is never overwritten.

---

### `business-analyst/coverage` (optional)

Runs for complex tasks (≥5 ACs, large scope, or integration risk). The BA reviews
whether the implemented tests cover all acceptance criteria from a user-scenario
perspective — not whether they pass. Reports gaps in plain business English.

---

### `code-reviewer/quality` (optional)

Runs after multiple fix cycles, or if the RM blocks on quality-related reasons.
Reviews type hints, async patterns, error handling, logging, docstrings, naming,
and PEP 8 compliance in the written code only.

---

### `release-manager/final` — Mandatory Final Gate

Always the last action before `COMMIT_READY`. The RM checks:

1. **Scope** — every changed file is in the SA's in-scope list.
2. **Findings** — no open CRITICAL/HIGH/MEDIUM findings in the ledger.
3. **Regressions** — no test that was passing is now failing.

| Gate | Meaning |
|---|---|
| `APPROVED` | All checks pass. PM emits `COMMIT_READY`. |
| `BLOCKED` | One or more checks failed. PM injects a `developer/fix` or `code-reviewer/quality` to resolve, then retries RM. |

If the RM blocks twice on the same reason, the PM escalates with a quality review
insertion before retrying.

---

## The Findings Ledger

All findings are tracked in `.claude/workflow-state/findings-ledger.md`:

```text
| ID    | Sev      | Stage     | Tag          | Status   | File              | Description         |
|-------|----------|-----------|--------------|----------|-------------------|---------------------|
| F-001 | CRITICAL | SA        | Task         | RESOLVED | src/agents/foo.py | Missing retry cap   |
| F-002 | HIGH     | CR-quality| Pre-existing | OPEN     | src/core/base.py  | No timeout on call  |
| F-003 | MEDIUM   | TD-design | Task         | OPEN     | src/agents/bar.py | Unclear error path  |
```

**Zero-tolerance policy:** `COMMIT_READY` requires zero open findings. There is no
APPROVED_WITH_NOTES verdict. MEDIUM findings block the workflow just as CRITICAL
and HIGH do. Pre-existing findings must be resolved.

---

## The Progress File

Every agent appends live updates to `.claude/workflow-state/progress.md`.

```text
[Stage 1 — Architecture] Starting — reading task description
[Stage 1 — Architecture] Complete — 6 acceptance criteria, 6 required tests
[PM Loop — Iteration 2] constraint_check: PASS
[Stage 3a — Red Phase] Starting — reading test contract
[Stage 3a — Red Phase] Writing failing tests — 6 tests
[Stage 3a — Red Phase] Complete — 6 tests failing (RED)
[Stage 3b — Green Phase] Starting — reading failing tests
[Stage 3b — Green Phase] Implementing retry logic in DaxAgent.call_llm()
[Stage 3b — Green Phase] Running pytest — confirming GREEN
[Stage 3b — Green Phase] Complete — 8 passed, 0 failed
[Release Manager — Final Gate] Starting review — iteration 1
[Release Manager — Final Gate] Complete — APPROVED
[PM Loop] Iteration 4 — COMMIT_READY.
```

---

## Workflow State Files

```text
.claude/workflow-state/
├── checkpoint.md           # Status, PM_ITERATIONS, PM_EXIT_REASON, Last Action
├── findings-ledger.md      # Cumulative findings table
├── progress.md             # Live log — never overwritten, cumulative across runs
├── handoff-S-PM-state.md   # PM loop state: iteration, history, in-scope files
├── handoff-S-PM-N.md       # PM task card output for iteration N
├── handoff-S0.md           # BA/brief output
├── handoff-S1.md           # Solution Architect output
├── handoff-S2.md           # Tech Lead/Design output
├── handoff-S3a.md          # Developer/Red output
├── handoff-S3b.md          # Developer/Green output (never overwritten by fix)
├── handoff-S3b-fix-N.md    # Developer/Fix output (numbered — N = 2, 3, ...)
├── handoff-S4.md           # BA/Coverage output
├── handoff-S5.md           # Code Reviewer/Quality output
└── handoff-S6.md           # Release Manager output
```

This directory is in `.gitignore` — run artifacts are not committed.

### Resuming an interrupted workflow

On the next invocation, the orchestrator checks `checkpoint.md`:

- **Status: APPROVED or BLOCKED** — prior run is complete. Starts fresh automatically.
- **Status: IN_PROGRESS** — a run was interrupted. You are asked:
  `"Resume? [Y/N] (default: N)"`. Default is to start fresh.

> If you close Claude Code while a stage is running, the in-progress subagent is
> killed immediately. Completed stages are safe — their handoff files are on disk.
> The PM will re-run only what is needed.

---

## Subagent Questions

Subagents run silently and cannot ask questions mid-execution. If they have a
question, it appears in `## Open Questions` at the end of their output. The
orchestrator relays these to you in chat before the next PM iteration.

Answer directly in chat — your answer is injected into the next agent's context bundle.

---

## Standalone Stage Usage

Each stage can still be run independently for targeted work:

```text
/multi-agent-workflow:01-architecture
[task description]

/multi-agent-workflow:05-python-post
[paste prior stage outputs]
```

---

## Other Workflow Commands

| Command | Purpose |
|---|---|
| `/resolve-issue` | Troubleshoot a pipeline failure |
| `/review-codebase` | Full audit of `src/` and `tests/` against coding standards |
| `/review-logging-quality` | Audit logging quality |
| `/clean-dead-code` | Remove temp files, unused imports, orphaned functions |
| `/cleanup-agent-package` | Mechanical cleanup of a single agent package |

---

## Quick Reference

```text
/run-multi-agent-workflow
[task — be specific about files, behaviour, and done criteria]
```

The PM loop runs up to 12 iterations. Typical clean runs: 4–5 iterations.
Complex runs with fix cycles and reviews: 7–9 iterations.

---

## Troubleshooting

### Agent not found when spawning a subagent

Restart Claude Code (or reload the VS Code window) after adding new agent files.

### A changed file is flagged as out-of-scope by the RM

The RM checks changed files against the SA's in-scope list. If a file slipped in
accidentally, revert it: `git checkout -- <file>`. If it legitimately needs to
change, the PM will not be able to help — the SA contract is one-shot. You can
add the file to scope by restarting the workflow with a more complete task description.

### pytest not found

Activate your virtual environment before starting Claude Code:

```bash
source .venv/bin/activate   # or: .venv\Scripts\activate on Windows
```

### Stale workflow state from a previous run

```bash
rm -rf .claude/workflow-state/
```

Then invoke `/run-multi-agent-workflow` again.

### A stage outputs RED but seems wrong

Read the handoff file to see the full reasoning:

```bash
cat .claude/workflow-state/handoff-S1.md   # or S3a, S3b, S5, S6, etc.
```

For PM output: `cat .claude/workflow-state/handoff-S-PM-N.md` (where N is the iteration).

### Progress file is empty during a stage run

The first update appears after the agent reads its input files — wait 10–15 seconds.

### PM emits the same action twice (loop detected)

The orchestrator detects this and overrides to `COMMIT_READY` with reason
`LOOP_DETECTED_OVERRIDE`. Check `progress.md` — the log will show which action
repeated. If the workflow ended prematurely, restart with a more specific task description.
