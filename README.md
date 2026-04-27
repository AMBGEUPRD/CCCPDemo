# CPG.AI-BITransposer

## GitHub Copilot Workflow Quick Start

**New to this codebase?** Start here: [WORKFLOW_QUICKSTART.md](WORKFLOW_QUICKSTART.md)

This guide shows how to:
- Invoke the 6-stage multi-agent workflow with a single command
- Use specialized agents for architecture, code review, QA, and more
- Write just your task description and let the agents handle the rest

**TL;DR**: Open Copilot Chat → paste `@AIAgentExpert /run-multi-agent-workflow your-task-here` → done.

---

## Functional Documentation Input Selection

Metadata extraction writes both the full Tableau metadata and a slimmed
functional-documentation payload. When generating functional documentation,
the pipeline uses the full metadata for small inputs and automatically falls
back to the slimmed payload when the full extraction exceeds the configured
size threshold.