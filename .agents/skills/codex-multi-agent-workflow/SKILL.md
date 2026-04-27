---
name: codex-multi-agent-workflow
description: Stage and run a Codex-native multi-agent coding workflow for this repository. Use when Codex needs to replicate or replace the Claude Code runSubagent workflow, especially for architecture review, scoped implementation, QA verification, code review, merge gating, prompt design, agent-role mapping, or workflow orchestration with a findings ledger.
---

# Codex Multi-Agent Workflow

Treat the Claude workflow as a set of **logical roles** and **handoff contracts**.
Do not mirror it as six always-on spawned agents.

## Default operating model

- Keep the **main Codex thread** as the orchestrator, primary implementer, and final
  decision-maker.
- Use `update_plan` as the live stage tracker for the current session.
- Use `.codex/workflow-state/` only when the run is long, interruptible, or needs a
  durable findings ledger.
- Use `multi_tool_use.parallel` for independent reads and inspections.
- Use `apply_patch` for edits and `shell_command` for `rg`, tests, and `git diff`.

## Delegation rule

- Only use `spawn_agent` when the user explicitly asks for multi-agent, delegated, or
  parallel work.
- Keep immediate blocking work in the main thread.
- Use `explorer` for bounded codebase questions.
- Use `worker` for disjoint write scopes after Stage 1 has fixed the scope.
- Reuse agents with `send_input` only when the follow-up is tightly related.
- Call `wait_agent` only when the next critical-path step is blocked on that result.
- Close finished agents with `close_agent`.

## Tool translation

- Claude `runSubagent` -> main-thread stage pass by default; `spawn_agent` only under
  the delegation rule.
- Claude `todo` -> `update_plan`.
- Claude `read` and `search` -> `shell_command` with `rg`, `Get-Content`, and
  `Get-ChildItem`; parallelize with `multi_tool_use.parallel`.
- Claude `edit` -> `apply_patch`.
- Claude `execute` -> `shell_command`.
- Claude `vscode_askQuestions` -> ask one concise plain-text question only when a
  reasonable assumption would be risky.

## Stage flow

1. Run Stage 1 to define objective, in-scope files, out-of-scope files, constraints,
   acceptance criteria, required tests, and risks. Select `fast` or `full`.
2. Run Stage 2 only on `full` path. Challenge the plan and log findings.
3. Run Stage 3 to implement only in-scope changes, update tests, run the target test,
   then run the regression suite.
4. Run Stage 4 to verify each acceptance criterion with evidence and to re-open any
   unfixed findings.
5. Run Stage 5 only on `full` path. Review the written code, not the design.
6. Run Stage 6 to inspect `git diff`, confirm scope discipline, and decide merge
   readiness.

## Findings discipline

- Track CRITICAL, HIGH, and MEDIUM findings in a ledger.
- CRITICAL and HIGH findings in in-scope files must be resolved before approval.
- Findings in out-of-scope files are notes, not blockers.
- Re-open any finding that a later review still detects.

## Path selection

- `fast`: up to 3 files, low risk, isolated bug fix, test addition, or config change.
- `full`: more than 3 files, new feature, shared-code refactor, architecture change,
  or medium/high risk.
- Default to `full` when uncertain.

## References

- Read [references/orchestration.md](references/orchestration.md) for tool-specific
  orchestration, delegation patterns, feedback loops, and state templates.
- Read [references/stage-prompts.md](references/stage-prompts.md) for ready-to-use
  stage prompts and a Claude-to-Codex role mapping.
