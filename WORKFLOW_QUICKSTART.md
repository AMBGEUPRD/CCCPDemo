# Workflow Quick Start — GitHub Copilot Integration

**Goal**: Write task description → Dispatcher routes → Multi-agent workflow executes. Fast and simple.

---

## Quick Workflow (30 seconds)

### Step 1: Open Copilot Chat
- Press `Ctrl+Shift+L` (or click Copilot Chat in Activity Bar)

### Step 2: Type Your Workflow Command
In the chat input field:

```
/run-multi-agent-workflow your-task-description-here
```

**Example**:
```
/run-multi-agent-workflow Add retry logic to metadata extractor with exponential backoff
```

That's it. The dispatcher automatically chains all 6 stages via `runSubagent`, each
with its specialized agent. No manual agent selection needed.

### How Agent Routing Works

**For multi-stage workflows** (via `/run-multi-agent-workflow`):
- Type `/run-multi-agent-workflow` followed by your task description
- The dispatcher automatically calls each stage's specialized agent via `runSubagent`
- Handoff contracts pass between stages automatically — no manual copy-paste
- If any stage returns RED, the dispatcher routes work back for a fix and retries once
- Stage sequence: Architecture Reviewer → Python Reviewer → BITransposerDev → QA → Python Reviewer → Uncommitted Code Reviewer

**For direct, single-purpose tasks** (NOT using a workflow prompt):
- Select a specific agent from the palette: `Python Solution Reviewer`, `QA`, `Uncommitted Code Reviewer`, etc.
- These are for narrow, immediate feedback — not multi-stage work

### Syntax

```
/run-multi-agent-workflow your task description here
     ↑                     ↑
  workflow prompt        objective
```

---

## Available Agents (Quick Reference)

| Agent | When to Use | Pattern |
|-------|-------------|---------|
| **Python Solution Reviewer** | Direct code review (single purpose) | `@Python Solution Reviewer [paste code]` |
| **Uncommitted Code Reviewer** | Direct merge/diff review (single purpose) | `@Uncommitted Code Reviewer` |
| **QA** | Direct test design/edge-case check (single purpose) | `@QA [describe scenario]` |
| **BITransposerDev** | Direct Tableau-to-Power BI Q&A (single purpose) | `@BITransposerDev [paste code/schema]` |
| **AI Agent Architecture Reviewer** | Direct architecture Q&A (single purpose) | `@AI Agent Architecture Reviewer [question]` |

**Rule of thumb**: 
- **Multi-stage workflow** → `/run-multi-agent-workflow ...` (agents are selected automatically)
- **Quick single-purpose task** → Select a specialist directly from the palette

---

## Available Prompts (Quick Reference)

| Prompt | Usage |
|--------|-------|
| `/run-multi-agent-workflow` | Full 6-stage workflow: architecture → design → implementation → QA → review → merge |
| `/review-codebase` | Audit codebase against all coding standards |
| `/resolve-issue` | Troubleshoot and fix a specific issue |
| `/review-logging-quality` | Audit logging practices and patterns |
| `/clean-dead-code` | Identify and suggest removal of unused code |

---

## Typical Tasks

### Multi-Stage Workflow (Primary Method)
1. Type in chat:
```
/run-multi-agent-workflow Add retry logic with exponential backoff to metadata extractor
```
→ Auto-chains through: Architecture → Design → Implementation → QA → Review → Merge

### Quick Code Review (Direct Agent)
1. Select `Python Solution Reviewer` from agent palette
2. Type your code or paste it
```
Review this code:
[paste your code]
```
→ Single-purpose feedback, no workflow stages

### Quick Merge Check (Direct Agent)
1. Select `Uncommitted Code Reviewer` from agent palette
2. Chat (no command needed — agent reviews your current changes)

→ Reviews your uncommitted changes only; no workflow dispatch

### Quick Test Brainstorm (Direct Agent)
1. Select `QA` from agent palette
2. Type:
```
What edge cases should we test for this new payment flow?
```
→ Fast feedback; not a full QA stage

---

## Keyboard Shortcuts

- `Ctrl+Shift+L` — Open Copilot Chat (if configured in VS Code)
- `Ctrl+Shift+A` — Show command palette for quick agent selection
- `Ctrl+I` — Inline edit with Copilot
- `Ctrl+L` — Clear Copilot Chat history

---

## Workflow Stages (What Happens Behind the Scenes)

When you invoke `/run-multi-agent-workflow`, here's what runs:

1. **Stage 1 (Architecture Reviewer)** — Design sanity check, simplicity gate, naming audit
2. **Stage 2 (Python Solution Reviewer)** — Pre-implementation code quality review
3. **Stage 3 (BITransposerDev)** — Code generation and implementation
4. **Stage 4 (QA)** — Testing, edge case validation, regression check
5. **Stage 5 (Python Solution Reviewer)** — Post-implementation review
6. **Stage 6 (Uncommitted Code Reviewer)** — Final merge gate, diff audit

---

## Tips for Faster Workflow

### ✅ DO:
- Keep task descriptions clear and specific
- Reference file paths relative to workspace root
- Include acceptance criteria in task description
- Use agents for specialized reviews (don't ask one agent to do everything)

### ❌ DON'T:
- Paste huge code blocks; use file paths instead
- Ask for multiple unrelated tasks in one prompt
- Skip the multi-agent workflow for complex features
- Ignore agent feedback on simplicity/naming/maintainability

---

## Example: Full Task Lifecycle

**You write**:
```
/run-multi-agent-workflow 
Add cached retry logic to validation service with per-call timeout and exponential backoff (2s, 4s, 8s).
Acceptance criteria:
1. Retries on HTTP 429 with backoff
2. Respects Retry-After header
3. Circuit breaker stops after 3 consecutive failures
4. All retries logged with attempt number
5. Tests cover: max retries, backoff timing, circuit breaker
```

**What happens**:
1. Dispatcher calls each stage's specialized agent via `runSubagent`
2. Each stage reviews, challenges, and improves
3. Handoff contracts pass automatically between stages
4. Final merge-gate agent confirms no regressions
5. You review recommendations and commit

---

## Troubleshooting

**"Hook is taking too long"**
- Repository hooks are currently disabled in this repo.
- Run checks on demand when needed:
	- `.venv\\Scripts\\python -m isort --check-only <changed-files>`
	- `.venv\\Scripts\\python -m black --check <changed-files>`
	- `.venv\\Scripts\\python -m flake8 --max-line-length 120 <changed-files>`

**"Agent gave me bad suggestions"**
- Provide more specific acceptance criteria
- Reference existing code patterns in the codebase
- Ask for tradeoff analysis, not just yes/no

**"Too many files changed"**
- Break the task into smaller pieces and run workflow on each
- Prefer incremental changes over massive refactors

---

## Next Steps

1. **Try the workflow**: Pick a real task and run it
2. **Iterate**: Refine your task descriptions based on feedback
3. **Customize**: Add your own agents or prompts to `.github/agents/` or `.github/prompts/`

For more details, see:
- Coding standards: `.github/instructions/copilot-instructions.md`
- Agent designs: `.github/agents/`
- Workflow stages: `.github/prompts/multi-agent-workflow/`
