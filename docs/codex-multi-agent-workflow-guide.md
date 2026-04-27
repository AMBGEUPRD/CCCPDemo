# Codex Multi-Agent Workflow Guide

This is the Codex-native equivalent of the Claude Code workflow documented in
[multi-agent-workflow-guide.md](multi-agent-workflow-guide.md).

The goal is the same: take a task from scope definition to merge-ready code with
review gates, test evidence, and a findings ledger. The implementation model is
different because Codex does not work best as a fixed set of always-spawned agents.

## The key design change

Do **not** port the Claude workflow as a 1:1 clone of six permanent subagents.

That would fight Codex's strengths and its tool policy. In Codex, the better pattern
is:

- keep one strong main orchestrator in the current thread
- use `update_plan` for stage tracking
- use `shell_command`, `rg`, and `multi_tool_use.parallel` for repo inspection
- use `apply_patch` for edits
- use `spawn_agent` only when the user explicitly wants delegated or parallel work

That means "agent" in Codex is mostly a **role contract**, not necessarily a spawned
process.

## Claude-to-Codex mapping

| Claude workflow piece | Codex equivalent |
|---|---|
| `/run-multi-agent-workflow` command | A kickoff prompt plus the repo-local skill |
| Fixed agent files in `.claude/agents/` | Logical stage roles captured in prompt templates |
| `runSubagent` | Main-thread stage pass by default |
| `todo` | `update_plan` |
| Hidden stage outputs | Visible stage summaries plus optional state files |
| `vscode_askQuestions` | Plain-text question only when needed |
| `.claude/workflow-state/` | `.codex/workflow-state/` |

## What was added

This Codex workflow now lives in:

- [SKILL.md](../.agents/skills/codex-multi-agent-workflow/SKILL.md)
- [orchestration.md](../.agents/skills/codex-multi-agent-workflow/references/orchestration.md)
- [stage-prompts.md](../.agents/skills/codex-multi-agent-workflow/references/stage-prompts.md)
- [openai.yaml](../.agents/skills/codex-multi-agent-workflow/agents/openai.yaml)

## Recommended execution model

### Default mode

Use the main Codex thread for all six stages:

1. Stage 1 Architecture Review
2. Stage 2 Design Review on full path only
3. Stage 3 Implementation
4. Stage 4 QA Verification
5. Stage 5 Code Review on full path only
6. Stage 6 Merge Gate

This is the preferred path for most work because it keeps scope, edits, and review
context in one place.

### Delegated mode

Use `spawn_agent` only when the user explicitly asks for multi-agent, delegated, or
parallel execution.

Recommended patterns:

- `explorer` for bounded architecture or review questions
- `worker` for disjoint implementation slices after Stage 1 fixes the scope
- main thread remains responsible for routing, integration, tests, and final verdict

## Fast path vs full path

Use the same routing rule as the Claude workflow:

- `fast`: up to 3 files, isolated bug fix, test addition, or config change
- `full`: more than 3 files, new feature, shared-code refactor, architecture change,
  or anything with medium/high risk

Default to `full` if the choice is unclear.

## Findings ledger

Keep the same semantics:

- CRITICAL/HIGH/MEDIUM findings are tracked
- CRITICAL/HIGH findings in in-scope files block approval
- out-of-scope findings are logged as notes, not blockers
- later stages re-open findings that were claimed as fixed but still exist

For long or interruptible runs, persist the ledger and checkpoint in
`.codex/workflow-state/`.

## How to start a Codex run

In a fresh Codex thread, use a kickoff prompt like:

```text
Use the workflow described in .agents/skills/codex-multi-agent-workflow/SKILL.md.
Run the Codex workflow for this task:

<task description>

Expectations:
- decide fast vs full path
- keep a findings ledger
- edit only in-scope files
- run target tests, then the regression suite
- finish with a merge-gate verdict
```

If you later install the skill into your Codex skill home, you can shorten that to:

```text
Use $codex-multi-agent-workflow for this task:
<task description>
```

## Why this is a better Codex port

This version preserves the useful parts of your Claude workflow:

- stage contracts
- acceptance criteria
- findings ledger
- feedback loop
- merge gate

It changes the parts that should change in Codex:

- fixed subagents become logical roles
- command routing becomes `update_plan` plus direct tool use
- delegation becomes optional and explicit
- persistent workflow state becomes optional rather than mandatory

That keeps the workflow portable without copying Claude-specific mechanics that are not
idiomatic in Codex.
