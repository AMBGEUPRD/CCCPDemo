# Multi-Agent Workflow: Orchestration Prompts

Numbered stage prompts for the 6-stage multi-agent coding workflow.

## Primary Usage — Automated Dispatcher

The recommended way to run the full workflow is via the automated dispatcher:

```text
/run-multi-agent-workflow [your task description]
```

The dispatcher (`run-multi-agent-workflow.prompt.md`) automatically chains all 6 stages
via `runSubagent`, passing handoff contracts between stages. No manual agent selection
or copy-paste is needed.

## Individual Stage Prompts

These can also be used standalone for targeted single-stage runs (e.g., running only
QA verification on existing code).

| Prompt | Stage | Agent | Model | Purpose |
|--------|-------|-------|-------|---------|
| [01-architecture.prompt.md](01-architecture.prompt.md) | 1 | AI Agent Architecture Reviewer | Claude Opus 4.6 | Define scope, constraints, acceptance criteria |
| [02-python-pre.prompt.md](02-python-pre.prompt.md) | 2 | Python Solution Reviewer | Claude Opus 4.6 | Validate design approach |
| [03-implementation.prompt.md](03-implementation.prompt.md) | 3 | BITransposerDev | GPT-5 | Write code and tests |
| [04-qa.prompt.md](04-qa.prompt.md) | 4 | QA | GPT-5 | Verify acceptance criteria |
| [05-python-post.prompt.md](05-python-post.prompt.md) | 5 | Python Solution Reviewer | Claude Opus 4.6 | Review code quality |
| [06-merge-gate.prompt.md](06-merge-gate.prompt.md) | 6 | Uncommitted Code Reviewer | Claude Opus 4.6 | Final merge gate |

## Dispatcher

See [../run-multi-agent-workflow.prompt.md](../run-multi-agent-workflow.prompt.md) for
the automated orchestration entrypoint.

## Templates

See [../../templates/](../../templates/) for:
- `agent-handoff-contract.md` — communication protocol between stages
- `multi-agent-stage-checklist.md` — tracking checklist per task

## Examples

See [../../examples/multi-agent-workflow-example.md](../../examples/multi-agent-workflow-example.md) for a complete worked example with realistic outputs.
