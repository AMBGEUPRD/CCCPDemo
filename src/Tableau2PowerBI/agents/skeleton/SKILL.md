---
name: pbip-project-skeleton
description: Generate a deterministic empty Power BI PBIP project scaffold that downstream agents can populate with report and semantic model artifacts.
---

# PBIP Project Skeleton

## Mission

Create the first PBIP scaffold for a migration run.
This stage establishes only the project shell:
- the root `.pbip` file
- a `.gitignore` for local PBIP artifacts
- an empty `<ReportName>.Report` folder
- an empty `<SemanticModelName>.SemanticModel` folder
- a `definition.pbir` report shortcut pointing at the semantic model by relative path
- minimal `.platform`, `definition.pbism`, and empty `model.bim` files for the semantic model/report items

Do not invent report internals, semantic model internals, visuals, DAX, or TMDL content here.
Those are owned by downstream specialist agents.

## Output Rules

- Create a valid, deterministic PBIP project shell.
- Keep naming stable and filesystem-safe.
- Use relative artifact paths in the `.pbip` file.
- Prefer empty folders over placeholder implementation files when later agents are expected to fill the content.

## Default Names

- Report folder: `Report.Report`
- Semantic model folder: `<WorkbookName>.SemanticModel`
- Root file: `<WorkbookName>.pbip`

If the caller provides an explicit semantic model name, use that exact value instead.
