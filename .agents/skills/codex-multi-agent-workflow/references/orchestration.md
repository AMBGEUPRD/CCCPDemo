# Codex Orchestration Reference

## Core translation

The Claude workflow uses fixed named agents plus `runSubagent`. In Codex, the stable
unit is the **main thread**. Keep the workflow deterministic there, and treat agents as
optional sidecars.

Use this mapping:

| Claude concept | Codex equivalent |
|---|---|
| Dispatcher command | Main thread + `update_plan` |
| Agent registry | Logical role + prompt section |
| `runSubagent` | Main-thread pass or `spawn_agent` when explicitly requested |
| Findings Ledger file | `.codex/workflow-state/findings-ledger.md` |
| Checkpoint file | `.codex/workflow-state/checkpoint.md` |
| User questions tool | Plain-text question in chat |

## Recommended role ownership

Use these logical roles even when no subagent is spawned:

| Stage | Logical role | Default owner |
|---|---|---|
| 1 | Architecture Reviewer | Main thread |
| 2 | Design Reviewer | Main thread |
| 3 | Implementer | Main thread |
| 4 | QA Verifier | Main thread |
| 5 | Code Reviewer | Main thread |
| 6 | Merge Gate | Main thread |

When the user explicitly wants parallel work:

- Use `explorer` for Stage 1, 2, or 5 questions that can run independently.
- Use `worker` only for Stage 3 implementation slices with disjoint write sets.
- Keep Stage 6 in the main thread.

## Live orchestration

At workflow start, create a plan with:

1. Stage 1 Architecture Review
2. Stage 2 Design Review
3. Stage 3 Implementation
4. Stage 4 QA Verification
5. Stage 5 Code Review
6. Stage 6 Merge Gate

Mark Stage 2 and Stage 5 as skipped when the task takes the fast path.

Use `multi_tool_use.parallel` for:

- parallel `Get-Content` reads of in-scope files
- parallel `rg` searches in unrelated folders
- parallel static inspections that do not write files

Do not parallelize:

- `apply_patch`
- dependent shell steps
- overlapping write scopes

## Persistent state

Use file-backed state only when the workflow may be interrupted or the findings list is
large enough that you do not want to rebuild it from chat history.

Recommended files:

```text
.codex/workflow-state/
├── checkpoint.md
├── findings-ledger.md
├── handoff-S1.md
├── handoff-S2.md
├── handoff-S3.md
├── handoff-S4.md
└── handoff-S5.md
```

Checkpoint template:

```md
# Workflow Checkpoint

Task ID: task-<slug>-<timestamp>
Path: fast | full
Last Stage Completed: 1-6 | NONE
Verdict: IN_PROGRESS | APPROVED | APPROVED_WITH_NOTES | BLOCKED

## In-Scope Files
- src/path.py
- tests/unit/test_path.py

## Gate History
- Stage 1: GREEN
- Stage 2: YELLOW

## Findings Summary
CRITICAL_OPEN: 0
HIGH_OPEN: 1
MEDIUM_OPEN: 2
RESOLVED: 3
```

Findings ledger template:

```md
# Findings Ledger

| ID | Sev | Stage | Tag | Status | File | Description |
|----|-----|-------|-----|--------|------|-------------|
| F-001 | HIGH | 2 | Task | OPEN | src/example.py | Timeout is not bounded |
```

Tags:

- `Task`: caused by or directly related to the requested change
- `Pre-existing`: already present in the in-scope code
- `Out-of-Scope`: outside the approved Stage 1 scope

## Feedback loop

Trigger a fix loop after Stage 4 or Stage 5 when either condition is true:

- an acceptance criterion is unverified or failing
- the ledger still contains OPEN CRITICAL or HIGH findings in in-scope files

Loop shape:

- fast path: Stage 3 -> Stage 4
- full path: Stage 3 -> Stage 4 -> Stage 5

Cap the loop at two fix iterations. On the second iteration, prepend a root-cause
section before coding:

```md
## Root Cause Analysis Required

The previous fix did not resolve:
- F-00X ...

Explain why the prior attempt failed and what will change this time.
```

## Delegation patterns

Use delegation only when the user explicitly asks for it.

### Pattern A: architecture sidecar

- Main thread reads the task and identifies candidate files.
- Spawn one `explorer` to answer a narrow question such as "Which modules would this
  change touch and what is the smallest safe scope?"
- Continue reading code locally while the explorer runs.

### Pattern B: review sidecar

- Main thread implements the change.
- Spawn one `explorer` to review a specific code slice or test strategy.
- Wait only once the implementation is ready for that review result.

### Pattern C: split implementation

- Main thread owns the orchestration and one write slice.
- Spawn `worker` agents only for non-overlapping write scopes.
- Each worker prompt must name the files it owns and remind the worker that other
  agents may also be changing the repo.

## Merge gate

Stage 6 should always verify:

- only in-scope files changed
- targeted tests passed
- no OPEN CRITICAL or HIGH findings remain in-scope
- no temporary files or scratch artifacts remain
- the diff is simpler than the next obvious alternative
