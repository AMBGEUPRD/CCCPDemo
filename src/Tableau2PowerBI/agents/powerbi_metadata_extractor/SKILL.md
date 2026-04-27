---
name: powerbi-source-understanding
description: Extract canonical metadata from a zipped PBIP project using deterministic parsing of the PBIP manifest, report definition JSON, and semantic model TMDL files. Use for Power BI source understanding, PBIP inventory extraction, report/visual inspection, and semantic model metadata capture. Do not use for Tableau extraction or for generating new PBIP artifacts.
---

# Power BI Source Understanding

## Mission

Produce deterministic metadata for a PBIP project package (`.zip` containing exactly one `.pbip` root).

## Scope

In scope:
- Validate the uploaded ZIP as a PBIP package.
- Parse the root `.pbip` manifest.
- Parse report metadata from `.Report/definition.pbir` and report definition JSON.
- Parse semantic model metadata from `.SemanticModel/definition.pbism` and `.tmdl` files.
- Emit structured warnings for missing, unsupported, or ambiguous PBIP constructs.

Out of scope:
- Generating or modifying PBIP projects.
- Power BI to Tableau conversion.
- Any LLM-backed interpretation or recommendation step.

## Workflow

1. Validate the ZIP archive and locate exactly one `.pbip`.
2. Extract the archive safely to a temporary workspace.
3. Parse the PBIP manifest and resolve artifact paths.
4. Parse report pages, visuals, field bindings, and filters.
5. Parse semantic model tables, columns, measures, partitions, relationships, cultures, and expressions when present.
6. Emit deterministic JSON only.

## Constraints

- Do not read machine-local cache files under `.pbi/`.
- Reject path traversal when resolving extracted archive entries and PBIP-relative paths.
- Preserve missing/unsupported constructs as structured warnings instead of guessing.
