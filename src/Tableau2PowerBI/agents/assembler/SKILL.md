---
name: pbip-project-assembler
description: Assemble the deterministic PBIP skeleton project with the generated semantic model output to produce a PBIP project tree that can be opened in Power BI Desktop.
---

# PBIP Project Assembler

## Mission

Produce the final local PBIP project for a workbook by merging:
- the root `.pbip` project scaffold from the skeleton stage
- the report folder from the skeleton stage
- the fully generated semantic model folder from the semantic model stage

This step is deterministic file composition. Do not invent new report content or semantic model logic here.

## Output Rules

- Keep the root `.pbip` file and report folder from the skeleton output.
- Replace the skeleton's placeholder semantic model folder with the generated semantic model folder.
- Preserve filesystem-safe names and PBIP-relative paths so the result can be opened directly in Power BI Desktop.
- Write the assembled project into this agent's own output directory.
