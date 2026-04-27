---
description: "Orchestrate a 6-stage multi-agent coding workflow automatically via runSubagent. Architecture → design gate → implementation → QA → code review → merge gate."
model: ["GPT-5 (copilot)", "Claude Opus 4.6 (copilot)"]
tools:
  - read
  - search
  - todo
  - runSubagent
  - execute
  - edit
  - vscode_askQuestions
---

# Run Multi-Agent Workflow

Automated dispatcher that chains all 6 stages via `runSubagent`, passing handoff
contracts between stages automatically. No manual copy-paste required.

## How to Use

```text
Run the multi-agent workflow for this task:
[paste task description]
```

## Stage Map

| Stage | Agent Name                       | Preferred Model              | Prompt Reference                                               |
|-------|----------------------------------|------------------------------|----------------------------------------------------------------|
| 1     | AI Agent Architecture Reviewer   | Claude Opus 4.6 (copilot)   | `.github/prompts/multi-agent-workflow/01-architecture.prompt.md`|
| 2     | Python Solution Reviewer         | Claude Opus 4.6 (copilot)   | `.github/prompts/multi-agent-workflow/02-python-pre.prompt.md`  |
| 3     | BITransposerDev                  | GPT-5 (copilot)             | `.github/prompts/multi-agent-workflow/03-implementation.prompt.md`|
| 4     | QA                               | GPT-5 (copilot)             | `.github/prompts/multi-agent-workflow/04-qa.prompt.md`          |
| 5     | Python Solution Reviewer         | Claude Opus 4.6 (copilot)   | `.github/prompts/multi-agent-workflow/05-python-post.prompt.md` |
| 6     | Uncommitted Code Reviewer        | Claude Opus 4.6 (copilot)   | `.github/prompts/multi-agent-workflow/06-merge-gate.prompt.md`  |

### Model Selection Rationale

The dispatcher selects the model for each `runSubagent` call based on stage needs:

- **Reasoning-heavy stages** (1, 2, 5, 6 — scoping, design review, code review, merge
  gate): prefer **Claude Opus 4.6** for deeper analysis and judgment.
- **Execution-heavy stages** (3, 4 — implementation, QA): prefer **GPT-5** for strong
  code generation, structured output, and tool use.

When calling `runSubagent`, include this in the prompt to each subagent:
`Use model: [preferred model from Stage Map]`

If a preferred model is unavailable, fall back to the other model in the dispatcher's
model list. Both are capable; the preference optimizes for each stage's strength.

## Orchestration Rules

When the user provides a task description, execute the following stages **automatically**
in sequence — no manual copy-paste or handoff is needed between stages.

## Findings Ledger

The dispatcher maintains a **Findings Ledger** — a cumulative list of every CRITICAL,
HIGH, and MEDIUM finding reported by any stage during the workflow. Each entry tracks:

```
- F-NNN [Severity] [Source Stage] [Tag] [Status: OPEN/RESOLVED] Description
```

Finding IDs use a sequential `F-001`, `F-002`, … scheme assigned by the dispatcher when
appending to the ledger. The ID is stable once assigned — it never changes.

### Ledger rules

1. **Collect everything.** After each review stage (2, 4, 5, 6), extract ALL findings
   from the agent's output — both task-related and pre-existing/adjacent — and append
   them to the ledger with status OPEN.
2. **Deduplicate.** Before appending, check whether a finding with the same file, line
   range, and description already exists in the ledger. If it does, keep the existing
   entry (with its ID). If a review stage re-reports a previously RESOLVED finding,
   re-open the existing entry instead of creating a duplicate.
3. **Feed into implementation.** When calling Stage 3 (including re-runs), include the
   full ledger in the prompt so the implementation agent can resolve OPEN items.
4. **Mark resolved.** After Stage 3 completes, mark findings as RESOLVED if the agent
   reports addressing them. Verification happens in the subsequent review stage.
5. **Re-open if not fixed.** If a review stage (4, 5) re-reports a finding that was
   marked RESOLVED, re-open it.
6. **Report to user.** Include the ledger summary (open/resolved counts) in every
   inter-stage report.
7. **Merge gate enforces.** Stage 6 receives the ledger; CRITICAL/HIGH findings still
   OPEN block the merge.

### Scope rule for pre-existing findings

Pre-existing findings discovered in **in-scope files** must be resolved by Stage 3.
Pre-existing findings discovered in **out-of-scope files** are logged in the ledger but
tagged `[Out-of-Scope]` — they do NOT trigger the feedback loop and do NOT block the
merge gate. They are surfaced as APPROVED WITH NOTES for the user to address separately.

### Feedback loop

The feedback loop triggers after **any** review stage (4 or 5) that returns **RED or
YELLOW** and the ledger contains OPEN findings at CRITICAL or HIGH severity (excluding
`[Out-of-Scope]` tagged items). It does NOT wait until the last review stage.

1. Loop back: **Stage 3 → Stage 4 → Stage 5** (full path) or **Stage 3 → Stage 4**
   (fast path).
2. Pass all OPEN findings to Stage 3 as a `## Findings to Resolve` section.
3. Cap at **2 feedback iterations** per review stage (the initial pass + 2 fix cycles).
   If findings remain OPEN after the cap, report them to the user and proceed to the
   next stage — the merge gate will flag them.
4. MEDIUM findings do NOT trigger a loop on their own, but if a loop is already
   triggered by CRITICAL/HIGH items, MEDIUM findings are included in the
   `## Findings to Resolve` section for best-effort resolution.
5. Each re-run rebuilds the context bundle from the modified files.
6. A **GREEN** gate with a clean ledger (no OPEN CRITICAL/HIGH) skips the loop and
   proceeds normally.

---

### Path Selection

After Stage 1 completes (step 4 below), classify the task as **fast** or **full**:

| Signal | Fast path | Full path |
|--------|-----------|-----------|
| Files in scope | ≤ 3 | > 3 |
| Nature | bug fix, small refactor, config change, test addition | new feature, cross-cutting change, architecture change |
| Risk | low — isolated, well-tested area | medium/high — touches shared code, public API, or untested area |

**Fast path** (4 stages): Stage 1 → Stage 3 → Stage 4 → Stage 6.
Skips Stage 2 (pre-review) and Stage 5 (post-review) — their value is low for
small, isolated changes. Saves ~40% time and tokens.

**Full path** (6 stages): Stage 1 → Stage 2 → Stage 3 → Stage 4 → Stage 5 → Stage 6.
Used for anything complex, risky, or multi-file.

If unsure, default to **full path**. The dispatcher reports which path was selected
in the Stage 1 summary so the user can override if needed.

Subagents cannot interact with the user directly (`runSubagent` is stateless). If a
subagent needs clarification, it must include an `## Open Questions` section in its
output. The dispatcher is responsible for relaying those questions to the user via
`vscode_askQuestions` before proceeding to the next stage. If the user's answers change
the direction, feed the answers back into the same stage by re-running that subagent.

### Stage 1 — Architecture Review

0. **Pre-stage check**: before launching the subagent, evaluate the user's task
   description. If it is ambiguous, too broad, or missing key details (e.g. which
   files, what behavior should change, what "done" looks like), use
   `vscode_askQuestions` to clarify with the user first. Only proceed once the task
   is clear enough for the architecture agent to produce a concrete scope.
1. Read `.github/prompts/multi-agent-workflow/01-architecture.prompt.md` for the full
   stage instructions.
2. Call `runSubagent` with `agentName: "AI Agent Architecture Reviewer"`.
   - Prompt must include the user's task description and the full stage instructions.
   - Prompt must instruct the agent to return the completed HANDOFF v1 contract and
     GATE STATUS.
3. Parse the returned GATE STATUS.
   - **GREEN/YELLOW**: save the handoff.
   - **RED**: stop the workflow and report the blocking issues to the user.
4. **Select path**: using the Stage 1 handoff (in-scope files, risk, nature), classify
   the task as **fast** or **full** per the Path Selection table above.
5. **Report to user** before proceeding: print a brief summary including gate status,
   scope decided, key constraints, any YELLOW concerns, and **which path was selected**
   (fast or full). The user may reply to override the path choice.
6. **Build context bundle**: extract the `In-Scope Files` list from the Stage 1 handoff.
   Read each file once using `read_file`. If the total content exceeds ~3 000 lines,
   fall back to paths-only mode (skip injection, let subagents read on demand).
   Otherwise, assemble a `## Context Bundle` block:
   ```
   ## Context Bundle (auto-injected — do NOT re-read these files)
   These files are already included below. You may read OTHER files
   (imports, base classes, configs, test fixtures) if needed for analysis.
   ### path/to/file.py
   ```python
   [file content]
   ```
   ### path/to/other.py
   ...
   ```
   This bundle is injected into **review-stage** prompts (Stages 2, 4, 5, 6).
   Stage 3 (implementation) receives only the file *paths* — it must read the latest
   version itself because it will edit them.
7. Proceed to **Stage 2** (full path) or **Stage 3** (fast path).

### Stage 2 — Python Solution Review (Pre-Implementation)

> **Fast path**: skip this stage entirely. Proceed to Stage 3.

1. Read `.github/prompts/multi-agent-workflow/02-python-pre.prompt.md` for the full
   stage instructions.
2. Call `runSubagent` with `agentName: "Python Solution Reviewer"`.
   - Prompt must include the Stage 1 handoff output, the **context bundle**, and the
     full stage instructions.
   - Prompt must instruct the agent to return its DESIGN REVIEW and GATE STATUS.
3. Parse the returned GATE STATUS.
   - **GREEN/YELLOW**: save the review, proceed to Stage 3.
   - **RED**: call Stage 1 agent again with the review feedback. Retry once, then stop.
4. **Update the Findings Ledger**: extract all findings from the review output. Append
   new items as OPEN (these are the first entries in the ledger). Deduplicate per
   ledger rules.
5. **Report to user** before proceeding: print gate status, design approach confirmed,
   any concerns or alternatives raised, and Findings Ledger summary (open/resolved
   counts).

### Stage 3 — Implementation

1. Read `.github/prompts/multi-agent-workflow/03-implementation.prompt.md` for the full
   stage instructions.
2. Call `runSubagent` with `agentName: "BITransposerDev"`.
   - Prompt must include handoff outputs from prior stages (Stages 1–2 on full path,
     Stage 1 only on fast path), the **in-scope file paths** (not the bundle), the
     **Findings Ledger** (if non-empty), and the full stage instructions.
   - Prompt must instruct the agent to write code and tests, resolve OPEN findings,
     run `pytest tests/unit/ -v --tb=short`, and return IMPLEMENTATION COMPLETE with
     GATE STATUS.
3. Parse the returned GATE STATUS.
   - **GREEN**: save the implementation output, proceed to Stage 4.
   - **RED**: the implementation agent should self-fix. If still RED after its own
     retries, stop the workflow and report.
4. **Report to user** before proceeding: print gate status, files changed, tests
   written, and test pass/fail results.
5. **Rebuild context bundle**: re-read the in-scope files (they may have been modified).
   Apply the same ~3 000 line guard. This refreshed bundle is used for Stages 4–6.

### Stage 4 — QA Verification

1. Read `.github/prompts/multi-agent-workflow/04-qa.prompt.md` for the full stage
   instructions.
2. Call `runSubagent` with `agentName: "QA"`.
   - Prompt must include handoff outputs from Stages 1–3, the **context bundle**, the
     **Findings Ledger**, and the full stage instructions.
   - Prompt must instruct the agent to report ALL findings (task-related and
     pre-existing) and return QA VERIFICATION with GATE STATUS.
3. **Update the Findings Ledger**: extract all findings from the QA output. Append new
   items as OPEN. Re-open any previously RESOLVED finding that the QA agent re-reports.
4. Parse the returned GATE STATUS and check the Findings Ledger.
   - **GREEN with clean ledger** (no OPEN CRITICAL/HIGH): save the QA output.
     - **Fast path**: proceed to Stage 6.
     - **Full path**: proceed to Stage 5.
   - **GREEN/YELLOW/RED with OPEN CRITICAL/HIGH findings**: trigger the feedback loop
     (Stage 3 → Stage 4, max 2 iterations). Pass failed acceptance criteria (if RED)
     plus all OPEN findings from the ledger to Stage 3. After Stage 3 re-run, re-run
     Stage 4. If clean after the loop, proceed to Stage 5 (full) or Stage 6 (fast).
     If still unresolved after 2 iterations, report to user and proceed.
5. **Report to user** before proceeding: print gate status, acceptance-criteria
   evidence matrix (pass/fail per criterion), YELLOW findings, and Findings Ledger
   summary (open/resolved counts).

### Stage 5 — Python Solution Review (Post-Implementation)

> **Fast path**: skip this stage entirely. Proceed to Stage 6.

1. Read `.github/prompts/multi-agent-workflow/05-python-post.prompt.md` for the full
   stage instructions.
2. Call `runSubagent` with `agentName: "Python Solution Reviewer"`.
   - Prompt must include handoff outputs from Stages 1–4, the **context bundle**, the
     **Findings Ledger**, and the full stage instructions.
   - Prompt must instruct the agent to report ALL findings (task-related and
     pre-existing) and return CODE REVIEW FINDINGS with GATE STATUS.
3. **Update the Findings Ledger**: extract all findings from the review output. Append
   new items as OPEN. Re-open any previously RESOLVED finding that is re-reported.
4. Parse the returned GATE STATUS and check the Findings Ledger.
   - **GREEN with clean ledger** (no OPEN CRITICAL/HIGH): proceed to Stage 6.
   - **GREEN/YELLOW/RED with OPEN CRITICAL/HIGH findings**: trigger the feedback loop
     (Stage 3 → Stage 4 → Stage 5, max 2 iterations). Pass critical/high findings
     plus all OPEN findings from the ledger to Stage 3. Re-run Stage 4 and Stage 5
     after. If clean after the loop, proceed to Stage 6. If still unresolved after
     2 iterations, report to user and proceed.
5. **Report to user** before proceeding: print gate status, findings count by severity,
   code-quality issues flagged, and Findings Ledger summary (open/resolved counts).

### Stage 6 — Final Merge Gate

1. Read `.github/prompts/multi-agent-workflow/06-merge-gate.prompt.md` for the full
   stage instructions.
2. Call `runSubagent` with `agentName: "Uncommitted Code Reviewer"`.
   - Prompt must include handoff outputs from Stages 1–5, the **context bundle**, the
     **Findings Ledger**, and the full stage instructions.
   - Prompt must instruct the agent to inspect the git diff and return FINAL MERGE GATE
     REVIEW with RECOMMENDATION.
3. Parse the returned status.
   - **APPROVED / APPROVED WITH NOTES**: workflow complete. Report the final summary.
   - **BLOCKED**: report the blockers to the user and stop.

## Cross-Cutting Rules

- **Handoff passing**: each stage receives the **full output from the immediately
  preceding stage** plus a **structured summary** of all earlier stages plus the
  **current Findings Ledger**. The summary uses this compact format per prior stage:
  ```
  Stage N ([Agent]): GATE [GREEN/YELLOW/RED]
  Key decisions: [1-2 sentences]
  Files: [list of paths]
  Tests: [list of test names]
  Findings: [CRITICAL/HIGH items only, or "none"]
  ```
  This prevents context window bloat while preserving traceability. Each subagent can
  use `read_file` to inspect actual code when it needs full detail.
- **Context injection**: after Stage 1, the dispatcher builds a context bundle from the
  in-scope files (see Stage 1 step 6). Review stages (2, 4, 5, 6) receive this bundle
  in their prompt so they do **not** need to call `read_file` for in-scope files.
  Stage 3 (implementation) receives file *paths only* — it reads files itself since it
  edits them. If the bundle exceeds ~3 000 lines, all stages receive paths only.
  After Stage 3 completes, **rebuild the bundle** by re-reading the modified files so
  Stages 4–6 see the latest content.
- **Feedback routing**: both RED and YELLOW gates trigger the feedback loop when the
  Findings Ledger has OPEN CRITICAL/HIGH findings. GREEN gates with a clean ledger
  proceed normally. The maximum retry depth is 2 iterations per loop trigger. If still
  unresolved after 2 iterations, report to user and proceed to the next stage.
- **Temp file cleanup**: before each stage handoff and at workflow end, ensure no
  temporary files remain (smoke tests, scratch scripts, debug dumps).
- **Conciseness**: pass file paths and test names, not full file contents, in handoff
  summaries. File contents are provided via the context bundle, not repeated in handoffs.
- **Stage prompts are authoritative**: the numbered `.prompt.md` files define all stage
  behavior. This dispatcher only controls sequencing and routing.
- **Inter-stage reporting**: after every stage, **print a visible summary to the user**
  before calling the next subagent. Use this format:
  ```
  ---
  ## Stage N Complete: [Stage Title]
  **Gate**: 🟢 GREEN / 🟡 YELLOW / 🔴 RED
  **Summary**: [2-3 sentence recap of what this stage decided or found]
  **Key outputs**: [file paths, test names, findings count — whatever is relevant]
  **Concerns**: [any YELLOW items or none]
  **Findings Ledger**: [X OPEN (C/H/M breakdown), Y RESOLVED] or "empty"
  ---
  ```
  This is critical — `runSubagent` results are not visible to the user, so the
  dispatcher must surface them explicitly.
- **Question relay**: after parsing each stage's output, check for an `## Open Questions`
  section. If present, use `vscode_askQuestions` to present the questions to the user
  with selectable options where possible. Feed answers back by re-running the same
  subagent with the original prompt plus the user's answers. Only proceed to the next
  stage once open questions are resolved or the user explicitly says to skip them.

## Notes

- Use `.github/prompts/multi-agent-workflow/README.md` as the index.
- Individual stage prompts can still be used standalone for targeted runs.
- The `agent:` field in individual stage prompts is retained for documentation and
  standalone use but is not used by this dispatcher (routing is explicit here).
