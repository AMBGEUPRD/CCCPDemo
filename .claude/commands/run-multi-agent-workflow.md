---
description: "PM-orchestrated multi-agent workflow. Project Manager drives all agent
  sequencing dynamically — SA contract, TDD (Red→Green), and RM final gate are enforced
  as PM constraints. Run with /run-multi-agent-workflow."
argument-hint: "Describe the task: bug fix, feature, or refactor."
---

# Run Multi-Agent Workflow

Dynamic PM-orchestrated workflow. A Project Manager agent reads structured state
summaries after each agent run and decides which agent to invoke next. The PM adapts
to current state — BA/brief, design review, and coverage checks are invoked only when
warranted. SA contract, TDD sequencing, and Release Manager final gate are enforced
as hard PM constraints, not fixed pipeline stages.

Workflow state is persisted to files so the pipeline survives context window pressure
and can be resumed after interruption.

---

## How to Use

Run the command with or without a task description:

```text
/run-multi-agent-workflow Add a validate_column_names function to src/validators.py
```

```text
/run-multi-agent-workflow
```

If no description is provided, you will be asked for one before anything runs.

### What happens next

1. The orchestrator collects your task and checks for a prior run's checkpoint.
2. A **Project Manager** agent decides which specialist to invoke first (usually the
   Solution Architect to define the scope and TDD contract).
3. After each agent completes, the PM reads structured summaries and emits a task card
   naming the next agent and exactly what it must do.
4. The loop continues — adapting to findings, failed tests, and coverage gaps — until
   the **Release Manager** approves all changes and the PM signals `COMMIT_READY`.

### What the PM always enforces (non-negotiable)

- Business Analyst brief always runs first — provides scope signals for all routing decisions.
- TDD: failing tests (Red) before production code (Green), always.
- Release Manager is the mandatory last gate before commit.

### What the PM decides based on context (optional)

- Solution Architect vs. direct-to-DEV-red (PM skips SA for simple 1-file bug fixes).
- Tech Lead design review (when SA flags design ambiguity or HIGH complexity).
- BA coverage check and Code Reviewer quality pass (for complex tasks, after multiple fix cycles, or when ≥3 files modified).

### Progress visibility

Open `.claude/workflow-state/<task-id-slug>/progress.md` in a VS Code tab before
starting — each agent appends live updates as it works. The exact path is announced
at Step 0 once the task-id-slug is derived.

---

## Workflow State Files

Each run gets its own folder under `.claude/workflow-state/<task-id-slug>/`.
Completed runs are archived to `.claude/workflow-archive/<task-id-slug>/`.
All paths below use `<task-id-slug>` as derived at Step 0.

| File | Purpose |
|------|---------|
| `.claude/workflow-state/<slug>/findings-ledger.md` | Canonical Findings Ledger (append after each review stage) |
| `.claude/workflow-state/<slug>/checkpoint.md` | Status, Feature Branch, PM_ITERATIONS, PM_EXIT_REASON, Last Action |
| `.claude/workflow-state/<slug>/progress.md` | Live cumulative append log — watch in VS Code |
| `.claude/workflow-state/<slug>/handoff-S-PM-state.md` | PM loop state: iteration, history, sa_in_scope_files, workflow_state_dir |
| `.claude/workflow-state/<slug>/handoff-S-PM-N.md` | PM task card output for iteration N |
| `.claude/workflow-state/<slug>/handoff-S0.md` | BA/brief output (overwritten on two-phase re-run) |
| `.claude/workflow-state/<slug>/handoff-S1.md` | Solution Architect output |
| `.claude/workflow-state/<slug>/handoff-S2.md` | Tech Lead/Design output |
| `.claude/workflow-state/<slug>/handoff-S3a.md` | Developer/Red output |
| `.claude/workflow-state/<slug>/handoff-S3b.md` | Developer/Green output (never overwritten by fix) |
| `.claude/workflow-state/<slug>/handoff-S3b-fix-N.md` | Developer/Fix output for attempt N (N = 2, 3, ...) |
| `.claude/workflow-state/<slug>/handoff-S4.md` | BA/Coverage output |
| `.claude/workflow-state/<slug>/handoff-S5.md` | Code Reviewer/Quality output |
| `.claude/workflow-state/<slug>/handoff-S6.md` | Release Manager/Final output (overwritten on re-invocation) |

Create base directories at Step 0: `mkdir -p .claude/workflow-state .claude/workflow-archive`

---

## Checkpoint Format

```text
Status: IN_PROGRESS | APPROVED | BLOCKED
Task ID: [task-id-slug]
Feature Branch: feature/[task-id-slug]
PM_ITERATIONS: [N]
PM_EXIT_REASON: [COMMIT_READY | ITERATION_CAP_REACHED | LOOP_DETECTED_OVERRIDE | PM_OUTPUT_PARSE_ERROR | IN_PROGRESS]
Last Action: [agent/phase]
```

**Stale checkpoint handling:**

Scan all `checkpoint.md` files under `.claude/workflow-state/*/checkpoint.md`.

- Any folder with Status `APPROVED` or `BLOCKED` → skip (already archived or abandoned).
- Any folder with Status `IN_PROGRESS` → ask:
  `"A workflow run is in progress: [task-id-slug] (Last Action: [value]). Resume? [Y/N] (default: N)"`
  - **Y** = restore `WORKFLOW_STATE_DIR` to that folder and continue.
  - **N** = leave that folder in place (do not delete); start a new run with a new slug.
- If multiple IN_PROGRESS folders exist, list all and let the user choose one to resume
  or decline all (start fresh).

---

## Findings Ledger

The Findings Ledger is stored in `<WORKFLOW_STATE_DIR>/findings-ledger.md`
(where `WORKFLOW_STATE_DIR = .claude/workflow-state/<task-id-slug>`).
Read it from the file before each stage; write it back after each update.
Never rely solely on in-context text — always sync to/from the file.

### File format

```markdown
# Findings Ledger

| ID | Sev | Stage | Tag | Status | File | Description |
|----|-----|-------|-----|--------|------|-------------|
| F-001 | CRITICAL | SA | Task | OPEN | src/agents/foo.py | Missing retry cap |
| F-002 | HIGH | TD-design | Pre-existing | RESOLVED | src/core/base.py | No timeout |
| F-003 | MEDIUM | CR-quality | Task | OPEN | src/agents/bar.py | Docstring missing |
```

### Ledger rules

1. **Append after each review stage.** Assign sequential IDs (F-001, F-002…).
2. **Deduplicate**: same file + same description = same entry. Grep the file before appending.
3. **Mark RESOLVED** after a developer stage reports fixing a finding. Never delete resolved entries.
4. **Re-open** any RESOLVED entry that a subsequent review stage reports as still present.
5. **`[Out-of-Scope]` tag**: findings in out-of-scope files get this tag. They appear in
   the ledger but do NOT block the merge gate.
6. **Pre-existing findings are NOT exempt.** The `[Pre-existing]` tag is informational only.
   Pre-existing findings must be resolved before APPROVED can be issued.
7. Parse finding counts from the `<!-- WORKFLOW_GATE: ... -->` comment in each stage's
   output — do NOT count manually from prose.

---

## Dispatch Table

Model is resolved dynamically from the `reasoning_level` in the PM task card (see Model
Selection below). The table shows the persona and stage file only.

| agent/phase | Stage file | Handoff output | Persona |
|-------------|-----------|----------------|---------|
| `business-analyst/brief` | `00-requirements-brief.md` | `handoff-S0.md` | Business Analyst |
| `solution-architect` | `01-architecture.md` | `handoff-S1.md` | Solution Architect |
| `tech-lead/design` | `02-python-pre.md` | `handoff-S2.md` | Code Reviewer |
| `developer/red` | `03a-implementation.md` | `handoff-S3a.md` | Developer |
| `developer/green` | `03b-testing.md` | `handoff-S3b.md` | Developer |
| `developer/fix` | `03b-testing.md` | `handoff-S3b-fix-N.md` | Developer |
| `business-analyst/coverage` | `04-qa.md` | `handoff-S4.md` | Business Analyst |
| `code-reviewer/quality` | `05-python-post.md` | `handoff-S5.md` | Code Reviewer |
| `release-manager/final` | `06-merge-gate.md` | `handoff-S6.md` | Release Manager |

For `developer/fix`: N = FIX_ATTEMPT value from last DEV-green or DEV-fix AGENT_SUMMARY + 1.

### Model Selection

Read `reasoning_level` from the PM task card. Map to model per agent:

| reasoning_level | Default model | Override |
|-----------------|---------------|---------|
| LOW | haiku | DEV-red/green/fix → sonnet (minimum) |
| MEDIUM | sonnet | DEV-green/fix → opus; BA/coverage → haiku |
| HIGH | opus | BA/brief, BA/coverage → haiku (never opus) |

Apply the override column when the agent/phase matches — it takes precedence.
If `reasoning_level` is missing from the task card, default to MEDIUM (sonnet).

---

## Stage Execution

### Step 0 — Task Collection (one time, before PM loop)

1. If the user provided a task description with the command, use it. Otherwise ask:

   ```text
   What would you like to work on?
   Describe the bug fix, feature, or refactor (one paragraph is enough):
   ```

   Do not proceed until a non-empty response is received.

2. Store as `task_description`. Derive `task_id_slug`:

   ```text
   task_id_slug = task_description
     → lowercase
     → strip punctuation and stop words (a, an, the, to, in, for, of, and, or, with)
     → take the fewest words that uniquely identify the task (target 1 word, then 2, then 3, max 5)
     → join with hyphens, truncate to 40 characters
   ```

   Set `WORKFLOW_STATE_DIR = .claude/workflow-state/<task_id_slug>`.

3. Scan `.claude/workflow-state/*/checkpoint.md` for stale runs (see Checkpoint Format section).
   If resuming, restore `WORKFLOW_STATE_DIR` to the chosen folder and skip to the PM loop.

4. Create directories: `mkdir -p .claude/workflow-state/<task_id_slug> .claude/workflow-archive`

5. **Create feature branch** (before any code changes):

   ```bash
   git checkout main
   git checkout -b feature/<task_id_slug>
   ```

   If `git checkout main` fails (dirty working tree or other error), stop immediately and
   report the error — do not proceed. If the branch already exists (resume scenario),
   run `git checkout feature/<task_id_slug>` instead. Announce:
   `"Feature branch ready: feature/<task_id_slug>"`

6. Write initial PM state to `<WORKFLOW_STATE_DIR>/handoff-S-PM-state.md`:

   ```text
   pm_iteration: 0
   pm_history: []
   last_task_card: none
   sa_in_scope_files: []
   workflow_state_dir: .claude/workflow-state/<task_id_slug>
   feature_branch: feature/<task_id_slug>
   ```

7. Initialize `<WORKFLOW_STATE_DIR>/findings-ledger.md`:

   ```markdown
   # Findings Ledger

   | ID | Sev | Stage | Tag | Status | File | Description |
   |----|-----|-------|-----|--------|------|-------------|
   ```

8. Append a run header to `<WORKFLOW_STATE_DIR>/progress.md`
   (never overwrite — this file is cumulative if the run is resumed):

   ```text
   ---
   ## Run: [task_id_slug] | [datetime UTC]
   Task: [task description]
   Branch: feature/[task_id_slug]
   ---
   [Step 0] Task collected. Feature branch created. Starting PM loop.
   ```

   Tell the user:
   `"Tip: open .claude/workflow-state/<task_id_slug>/progress.md in a VS Code tab to watch live progress."`

9. Write initial checkpoint to `<WORKFLOW_STATE_DIR>/checkpoint.md`:

   ```text
   Status: IN_PROGRESS
   Task ID: [task_id_slug]
   Feature Branch: feature/[task_id_slug]
   PM_ITERATIONS: 0
   PM_EXIT_REASON: IN_PROGRESS
   Last Action: none
   ```

---

### PM Loop (max 12 iterations)

Repeat the following steps until a break condition is reached.

---

#### Loop Step 1 — Increment and check cap

```text
pm_iteration += 1

If pm_iteration > 12:
  Read open finding counts from <WORKFLOW_STATE_DIR>/findings-ledger.md.
  Read last developer AGENT_SUMMARY for SUITE_CLEAN and TESTS_FAILING values.
  Write to <WORKFLOW_STATE_DIR>/progress.md:
    "[PM Loop] ITERATION_CAP_REACHED after 12 iterations.
     Open findings: [N]. Suite clean: [YES|NO]. Tests failing: [N]."
  Announce to user:
    "PM iteration cap reached (12). Workflow cannot proceed further automatically.
     Unresolved: [N] open findings, [N] failing tests.
     Review the findings ledger and handoff files, then re-run the workflow to continue."
  Write checkpoint: Status=BLOCKED, PM_EXIT_REASON=ITERATION_CAP_REACHED
  Archive: move <WORKFLOW_STATE_DIR>/ → .claude/workflow-archive/<task_id_slug>/
  Announce: "Run archived to .claude/workflow-archive/<task_id_slug>/"
  BREAK
```

---

#### Loop Step 2 — Build PM input bundle

Assemble 4 parts. Read all files in parallel.

**Part 1 — Latest AGENT_SUMMARY per stage:**
For each STAGE identifier that has appeared in pm_history
(`BA-brief`, `SA`, `TD-design`, `DEV-red`, `DEV-green`, `DEV-fix`, `BA-coverage`,
`CR-quality`, `RM-final`):

- Read the corresponding handoff file.
- Extract the `<!-- AGENT_SUMMARY ... -->` block (everything between the delimiters).
- If DEV-fix ran multiple times, include only the one with the highest FIX_ATTEMPT.
- Render as:

  ```text
  === [STAGE identifier] — Iteration [pm_iteration when it ran] ===
  [key: value, one per line]
  ```

**Part 2 — Full findings ledger:**
Read `<WORKFLOW_STATE_DIR>/findings-ledger.md` verbatim.

**Part 3 — PM loop state:**
Read `<WORKFLOW_STATE_DIR>/handoff-S-PM-state.md` verbatim.
(This file includes `workflow_state_dir` so the PM knows where to append progress.md.)

**Part 4 — SA test contract (only if SA has run):**
If `SA` appears in pm_history: read `<WORKFLOW_STATE_DIR>/handoff-S1.md`, extract
the "Required Tests" section only (test names and Given/When/Then specs — no prose).
If SA has not run: omit Part 4 entirely.

---

#### Loop Step 3 — Announce iteration

Output to conversation:

```text
PM Loop — Iteration [pm_iteration]
```

---

#### Loop Step 4 — Spawn PM agent

Read `.claude/commands/multi-agent-workflow/pm-loop.md`.

```text
Agent(subagent_type="Project Manager", model="sonnet",
      prompt = [pm-loop.md content]
             + "\n\n## PM Input Bundle\n"
             + "### Latest Agent Summaries\n" + [Part 1]
             + "\n\n### Findings Ledger\n" + [Part 2]
             + "\n\n### PM Loop State\n" + [Part 3]
             + ("\n\n### SA Test Contract\n" + [Part 4] if SA has run else ""))
```

Write the full PM output to `<WORKFLOW_STATE_DIR>/handoff-S-PM-[pm_iteration].md`.

---

#### Loop Step 5 — Parse task card

Locate the fenced block with label `pm-task-card` in the PM output.

```text
If block not found:
  Write to <WORKFLOW_STATE_DIR>/progress.md:
    "[PM Loop] PM_OUTPUT_PARSE_ERROR — no pm-task-card block found."
  Announce to user: "PM output malformed (no task card block found). Workflow stopped."
  Write checkpoint: Status=BLOCKED, PM_EXIT_REASON=PM_OUTPUT_PARSE_ERROR
  Archive: move <WORKFLOW_STATE_DIR>/ → .claude/workflow-archive/<task_id_slug>/
  Announce: "Run archived to .claude/workflow-archive/<task_id_slug>/"
  BREAK
```

Parse fields: `action`, `agent`, `task`, `focus_files`, `reason`, `reasoning_level`, `constraint_check`.

Log constraint_check value to progress.md (advisory only — does not stop the loop):

```text
[PM Loop — Iteration N] constraint_check: [value]
```

---

#### Loop Step 6 — Orchestrator loop detection

```text
If pm_iteration > 1 AND agent field == last entry's agent/phase in pm_history:
  Read open findings count from <WORKFLOW_STATE_DIR>/findings-ledger.md.
  Read SUITE_CLEAN from last developer AGENT_SUMMARY (if any developer stage ran).

  IF open_findings > 0 OR SUITE_CLEAN == NO:
    DO NOT override to COMMIT_READY — open issues still require resolution.
    Write to <WORKFLOW_STATE_DIR>/progress.md:
      "[PM Loop] Loop detected — [agent/phase] repeated, but open issues remain
       (findings: [N], SUITE_CLEAN: [value]). Continuing loop."
    Proceed to Loop Step 7 normally (let PM card stand — do not override action).

  ELSE (open_findings == 0 AND (no developer stage ran OR SUITE_CLEAN == YES)):
    Override action to COMMIT_READY
    Override reason to LOOP_DETECTED_OVERRIDE
    Write to <WORKFLOW_STATE_DIR>/progress.md:
      "[PM Loop] Loop detected — [agent/phase] repeated, all gates clean.
       Overriding to COMMIT_READY."
```

---

#### Loop Step 7 — Handle COMMIT_READY

```text
If action == COMMIT_READY:
  Write to <WORKFLOW_STATE_DIR>/progress.md:
    "[PM Loop] Iteration [N] — COMMIT_READY. Reason: [reason]"
  Write checkpoint:
    Status=APPROVED, PM_ITERATIONS=N, PM_EXIT_REASON=COMMIT_READY,
    Last Action=[last agent/phase from pm_history]
  Archive: move <WORKFLOW_STATE_DIR>/ → .claude/workflow-archive/<task_id_slug>/
  Announce to user:
    "Workflow complete — [pm_iteration] PM iterations. Reason: [reason]
     Branch: feature/[task_id_slug] — ready to review and merge.
     Run archived to .claude/workflow-archive/<task_id_slug>/"
  BREAK
```

---

#### Loop Step 8 — Announce PM decision

Output to conversation:

```text
PM → [agent/phase]: [task] — [reason]
```

---

#### Loop Step 9 — Update PM state

Append `{agent/phase: [value], gate: pending}` to pm_history.
Write updated pm_history and current pm_iteration to
`<WORKFLOW_STATE_DIR>/handoff-S-PM-state.md`.

---

#### Loop Step 10 — Look up dispatch

Using the Dispatch Table above, retrieve the stage file path, handoff output path, and
persona name. Then resolve the model using `reasoning_level` from the PM task card and
the Model Selection table:

```text
model = reasoning_level → default model, then apply agent-specific override.
```

For `developer/fix`: N = last DEV-green or DEV-fix `FIX_ATTEMPT` value + 1.

---

#### Loop Step 11 — Build context bundle

Apply tiered injection rules based on the agent/phase:

**`business-analyst/brief`** (if SA not yet run):

- Task description only. No code files — BA must not read code at this stage.
- If SA has run, this action cannot be called (PM constraint 3 blocks it).

**`solution-architect`** (if BA/brief ran):

- Inject Requirements Brief:
  `"## Requirements Brief (BA)\n" + content of handoff-S0.md`
  `+ "\n## Original Task Description\n" + task_description`
- If BA/brief did not run: inject task description only.

**`tech-lead/design`**:

- First 60 lines of each file listed in SA AGENT_SUMMARY `FILES_MODIFIED` field.
  Append: `[... N lines omitted — full file available via Read if needed]`
- Full content of SA contract (handoff-S1.md).

**`developer/red`**:

- First 60 lines of each in-scope production file (from SA FILES_MODIFIED).
- Full content of existing test files that mirror the source tree structure.

**`developer/green`**:

- Full content of all test files modified in Stage 3a.
- First 60 lines of each in-scope production file.

**`developer/fix`**:

- Full content of all test files (agent must see failing tests to implement fixes).
- Full content of production files named in the task's `focus_files` field.
- Prepend a Fix Iteration Context block:

  ```text
  ## Fix Iteration Context
  Fix Attempt: [FIX_ATTEMPT — value being written to this handoff]
  Target issues: [task field from PM task card]
  Prior failure: [FAILURE_SUMMARY from last DEV-green or DEV-fix AGENT_SUMMARY]
  Prior attempt summary: AC_WITH_TESTS=[N], TESTS_PASSING=[N], TESTS_FAILING=[N]
  ```

**`business-analyst/coverage`**:

- SA acceptance criteria section ONLY from handoff-S1.md (not full prose).
- Full content of test file(s) modified by developer stages.
- Do NOT inject production code.

**`code-reviewer/quality`**:

- Full content of files returned by `git diff --name-only`.
- File paths only (no content) of other in-scope files.

**`release-manager/final`**:

- Full `git diff` output.
- SA in-scope file list (from SA AGENT_SUMMARY `FILES_MODIFIED` field).
- Full findings ledger (from file, not in-context).

**All agents** also receive:

- Part 1 of the PM bundle (compact latest AGENT_SUMMARY per stage).
- Full findings ledger.

Issue all Read tool calls in parallel — never read files sequentially.

---

#### Loop Step 12 — Spawn agent

Read the stage file to get stage instructions.

Announce before spawning:

```text
---
[agent/phase] Starting — [persona name] | Model: [resolved model] | Level: [reasoning_level]
Task: [task field from PM task card]
Watch: <WORKFLOW_STATE_DIR>/progress.md for live updates
---
```

```text
Agent(subagent_type="[persona]", model="[model]",
      prompt = [stage file content]
             + "\n\n## Context Bundle\n" + [context bundle from Step 11]
             + "\n\n## Prior Stage Summaries\n" + [Part 1 of PM bundle]
             + "\n\n## Findings Ledger\n" + [full ledger from file])
```

Write full agent output to the handoff output path.

---

#### Loop Step 13 — Handle BA/brief two-phase (special case)

```text
If agent/phase was business-analyst/brief:
  Parse BRIEF_STATUS from output.

  If BRIEF_STATUS == NEEDS_ANSWERS:
    Extract numbered questions from output (after "Clarifying questions:" heading).
    Announce to user: "BA has clarifying questions:\n[questions]\nPlease answer:"
    Wait for user response.

    Re-run business-analyst/brief with answers injected:
      Agent(subagent_type="Business Analyst", model="sonnet",
            prompt = [stage file content]
                   + "\n## Task Description\n" + task_description
                   + "\n## User Answers\n" + user_response)

    Overwrite <WORKFLOW_STATE_DIR>/handoff-S0.md with second BA output.
    This re-run is part of the SAME pm_iteration — do NOT increment pm_iteration.
    The second run MUST return BRIEF_STATUS: COMPLETE — do not loop further.
```

---

#### Loop Step 14 — Update ledger and state

1. Parse `<!-- WORKFLOW_GATE: ... -->` from agent output.
2. Parse `<!-- AGENT_SUMMARY ... -->` block from agent output.
3. Extract GATE value from AGENT_SUMMARY.

4. **Update findings ledger** (read → modify → write):
   - Mark previously OPEN findings as RESOLVED if the agent addressed them.
   - Re-open any RESOLVED finding the agent reports as STILL PRESENT.
   - Append any new findings from the agent output (deduplicate by file + description).

5. Update pm_history last entry: replace `gate: pending` with actual GATE value from
   AGENT_SUMMARY.

6. **If agent was `solution-architect`:**
   Update `<WORKFLOW_STATE_DIR>/handoff-S-PM-state.md`: set `sa_in_scope_files` to the
   FILES_MODIFIED field from the SA AGENT_SUMMARY.

7. Write checkpoint to `<WORKFLOW_STATE_DIR>/checkpoint.md`:

   ```text
   Status: IN_PROGRESS
   Task ID: [task_id_slug]
   Feature Branch: feature/[task_id_slug]
   PM_ITERATIONS: [pm_iteration]
   PM_EXIT_REASON: IN_PROGRESS
   Last Action: [agent/phase]
   ```

8. Write to `<WORKFLOW_STATE_DIR>/progress.md`:
   `[PM Loop — Iteration N] [agent/phase] complete. GATE: [value].`

**CONTINUE LOOP** — go to Loop Step 1.

---

## Cross-Cutting Rules

- **Each run gets its own state folder.** `WORKFLOW_STATE_DIR = .claude/workflow-state/<task_id_slug>/`.
  On any exit (COMMIT_READY, BLOCKED, parse error), the folder is moved to
  `.claude/workflow-archive/<task_id_slug>/`. Never reuse a folder across tasks.

- **Progress file is cumulative within a run.** Never overwrite `<WORKFLOW_STATE_DIR>/progress.md`.
  If a run is resumed, append below the existing content with a new resume header.

- **Feature branch is mandatory.** All code changes happen on `feature/<task_id_slug>`,
  created at Step 0 from main. The orchestrator never touches main directly.

- **Announce before every spawn.** Always emit the stage-start banner immediately
  before every `Agent()` call. The user cannot see subagent activity — the banner is
  their only progress signal. Never spawn silently.

- **PM is the sequencing authority.** Do not hardcode stage order in the orchestrator.
  The PM decides what runs next. The orchestrator only enforces loop detection and
  iteration cap independently.

- **State files are ground truth.** Every routing decision reads from files, not
  in-context memory. Context can drift; files do not.

- **Parse gates from comments, not prose.** Always extract `<!-- WORKFLOW_GATE: ... -->`
  and `<!-- AGENT_SUMMARY ... -->` to get gate status and finding counts.
  Never count findings manually from prose.

- **Parallel reads.** When building the context bundle, issue all Read tool calls in
  a single response — never read files sequentially.

- **Zero-tolerance: findings AND test failures.** COMMIT_READY requires zero open
  findings and RM GATE=APPROVED. MEDIUM findings block just as CRITICAL and HIGH do.
  Pre-existing findings must be resolved. The loop detection override (Loop Step 6)
  only fires when both open_findings = 0 AND SUITE_CLEAN = YES — it cannot shortcut
  a dirty suite. SUITE_CLEAN must be YES unconditionally: pre-existing test failures
  discovered during the workflow must be fixed before COMMIT_READY, regardless of
  whether they were introduced by the current task.

- **developer/fix never overwrites developer/green.** Fix iterations write to
  `<WORKFLOW_STATE_DIR>/handoff-S3b-fix-N.md` (N = FIX_ATTEMPT). The original
  `handoff-S3b.md` is preserved as the Green phase reference.

- **Stage prompts are authoritative.** The numbered `.md` files in
  `.claude/commands/multi-agent-workflow/` define all agent behaviour. This orchestrator
  controls only PM loop execution, state management, and routing.

- **Individual stage commands** can still be used standalone for targeted runs.

- **Open Questions relay.** If any stage AGENT_SUMMARY shows `OPEN_QUESTIONS: YES`,
  read the Open Questions section from the handoff file and relay them to the user
  before continuing the PM loop. Feed answers into the next relevant agent's context bundle.
