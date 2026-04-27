"""Stage 5 — PBIP Project Assembler Agent.

Merges the outputs of all upstream agents into a single PBIP project
that can be opened directly in Power BI Desktop.

This stage is entirely deterministic — it performs only file copying:

1. Copy the skeleton's root files (``.pbip``, ``.gitignore``)
   and report folder.
2. Replace the skeleton's placeholder ``.SemanticModel/`` folder
   with the LLM-generated semantic model output.
3. Copy ``measures.tmdl`` from the DAX generator into the semantic
   model's ``definition/`` folder.
4. Overlay the PBIR report visuals/pages from the visuals generator
   into the report folder.
5. Copy extracted data files from the TWBX archive (if any)
   preserving their directory structure so relative paths in
   ``File.Contents()`` M expressions resolve correctly.
6. Reconciliation check: cross-validate visual field references
   against actual table/column/measure names in the assembled model.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from Tableau2PowerBI.core.agent import DeterministicAgent
from Tableau2PowerBI.core.config import AgentSettings
from Tableau2PowerBI.core.output_dirs import ensure_output_dir, get_output_dir, reset_output_dir, validate_name


class PBIPProjectAssemblerAgent(DeterministicAgent):
    """Assemble the final PBIP project from skeleton + generated model.

    This stage is deterministic and never calls an LLM backend.
    """

    def __init__(self, settings: AgentSettings | None = None):
        super().__init__(
            skill_name="pbip_project_assembler_agent",
            settings=settings,
        )

    @staticmethod
    def _require_directory(path: Path, description: str) -> Path:
        """Verify *path* exists and is a directory, raising ``FileNotFoundError`` otherwise."""
        if not path.exists() or not path.is_dir():
            raise FileNotFoundError(f"{description} not found at: {path.resolve()}")
        return path

    @staticmethod
    def _find_single_child(base_path: Path, suffix: str) -> Path:
        """Find exactly one subdirectory of *base_path* whose name ends with *suffix*."""
        matches = sorted(child for child in base_path.iterdir() if child.is_dir() and child.name.endswith(suffix))
        if not matches:
            raise FileNotFoundError(f"No '{suffix}' directory found in: {base_path.resolve()}")
        if len(matches) > 1:
            raise ValueError(
                f"Expected exactly one '{suffix}' directory in {base_path.resolve()}, found: "
                + ", ".join(path.name for path in matches)
            )
        return matches[0]

    @staticmethod
    def _find_single_pbip_file(base_path: Path) -> Path:
        """Find exactly one ``.pbip`` file inside *base_path*."""
        matches = sorted(child for child in base_path.iterdir() if child.is_file() and child.suffix == ".pbip")
        if not matches:
            raise FileNotFoundError(f"No '.pbip' file found in: {base_path.resolve()}")
        if len(matches) > 1:
            raise ValueError(
                f"Expected exactly one '.pbip' file in {base_path.resolve()}, found: "
                + ", ".join(path.name for path in matches)
            )
        return matches[0]

    @staticmethod
    def _copy_file(source: Path, target: Path) -> None:
        """Copy a single file, creating parent directories as needed."""
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    @staticmethod
    def _copy_tree(source: Path, target: Path) -> None:
        """Recursively copy a directory tree, merging into *target* if it exists."""
        shutil.copytree(source, target, dirs_exist_ok=True)

    def assemble_pbip_project(self, workbook_name: str, *, reset_output: bool = True) -> Path:
        """Merge skeleton + generated semantic model into the final PBIP output.

        Args:
            workbook_name: Identifies the skeleton and semantic model outputs.

        Returns:
            Path to the assembled output directory.
        """
        workbook_name = validate_name("Workbook name", workbook_name)

        skeleton_dir = self._require_directory(
            get_output_dir("pbip_project_skeleton_agent", workbook_name, self.settings),
            "PBIP skeleton output",
        )
        semantic_model_dir = self._require_directory(
            get_output_dir("pbip_semantic_model_generator_agent", workbook_name, self.settings),
            "PBIP semantic model output",
        )

        self._find_single_pbip_file(skeleton_dir)
        skeleton_semantic_model_dir = self._find_single_child(skeleton_dir, ".SemanticModel")
        generated_semantic_model_dir = self._find_single_child(semantic_model_dir, ".SemanticModel")

        output_dir = get_output_dir(self.skill_name, workbook_name, self.settings)
        if reset_output:
            reset_output_dir(output_dir)
        else:
            ensure_output_dir(output_dir)

        for child in skeleton_dir.iterdir():
            target = output_dir / child.name
            if child.is_file():
                self._copy_file(child, target)
                continue
            if child.is_dir() and child.name != skeleton_semantic_model_dir.name:
                self._copy_tree(child, target)

        target_semantic_model_dir = output_dir / skeleton_semantic_model_dir.name
        if generated_semantic_model_dir.name != skeleton_semantic_model_dir.name:
            self.logger.warning(
                "Semantic model folder name mismatch. Retargeting '%s' to '%s'.",
                generated_semantic_model_dir.name,
                skeleton_semantic_model_dir.name,
            )
        self._copy_tree(generated_semantic_model_dir, target_semantic_model_dir)

        # ── Copy DAX measures into the semantic model ─────────────────
        self._copy_dax_measures(workbook_name, target_semantic_model_dir)

        # ── Overlay PBIR report visuals into the report folder ────────
        self._copy_pbir_report(workbook_name, output_dir)

        # ── Copy extracted data files alongside the PBIP project ─────────
        self._copy_extracted_data(workbook_name, output_dir)

        # ── Reconciliation check ─────────────────────────────────────────
        self._reconcile_field_references(output_dir)

        self.logger.info("Assembled PBIP project created at %s", output_dir)
        return output_dir

    def _copy_extracted_data(self, workbook_name: str, output_dir: Path) -> None:
        """Copy data files extracted from a TWBX archive into the PBIP output.

        The files are placed preserving the archive-internal directory
        structure so that relative paths in M queries (``File.Contents()``)
        resolve correctly when Power BI Desktop opens the project.
        """
        extracted_data_dir = (
            get_output_dir("tableau_metadata_extractor_agent", workbook_name, self.settings) / "extracted_data"
        )
        if not extracted_data_dir.exists() or not extracted_data_dir.is_dir():
            self.logger.info("No extracted data files to copy.")
            return

        file_count = 0
        for source_file in extracted_data_dir.rglob("*"):
            if source_file.is_dir():
                continue
            # Preserve the archive-internal relative path
            relative = source_file.relative_to(extracted_data_dir)
            target = output_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target)
            file_count += 1

        self.logger.info(
            "Copied %d extracted data file(s) to %s",
            file_count,
            output_dir,
        )

    def _get_model_table_names(self, workbook_name: str) -> set[str]:
        """Return the set of table names defined in the generated semantic model.

        Table names are inferred from the ``*.tmdl`` filenames under
        ``definition/tables/`` in the semantic model generator output.
        Returns an empty set if the output directory or tables folder cannot
        be found (the caller treats an empty set as "no filtering").
        """
        model_output_dir = get_output_dir(
            "pbip_semantic_model_generator_agent",
            workbook_name,
            self.settings,
        )
        semantic_dirs = (
            [d for d in model_output_dir.iterdir() if d.is_dir() and d.name.endswith(".SemanticModel")]
            if model_output_dir.exists()
            else []
        )

        if not semantic_dirs:
            return set()
        tables_dir = semantic_dirs[0] / "definition" / "tables"
        if not tables_dir.exists():
            return set()
        return {f.stem for f in tables_dir.glob("*.tmdl")}

    @staticmethod
    def _parse_tmdl_table_name(declaration_line: str) -> str:
        """Extract the table name from a TMDL ``table`` declaration line.

        Handles both quoted (``table 'Name'``) and unquoted (``table Name``)
        forms and unescapes internal ``''`` sequences.
        """
        name_part = declaration_line.strip()[6:].strip()  # strip "table "
        if name_part.startswith("'"):
            i, chars = 1, []
            while i < len(name_part):
                ch = name_part[i]
                if ch == "'":
                    if i + 1 < len(name_part) and name_part[i + 1] == "'":
                        chars.append("'")
                        i += 2
                    else:
                        break
                else:
                    chars.append(ch)
                    i += 1
            return "".join(chars)
        return name_part.rstrip()

    @staticmethod
    def _strip_unknown_table_sections(
        tmdl_content: str,
        known_tables: set[str],
    ) -> tuple[str, list[str]]:
        """Remove ``table`` sections from *tmdl_content* whose names are not in *known_tables*.

        The ``Parameters`` table is always preserved: it holds scalar DAX
        parameter measures that have no physical column references and are
        harmless to keep even when the semantic model has no matching table file.

        Returns ``(sanitized_content, list_of_stripped_table_names)``.
        """
        lines = tmdl_content.splitlines(keepends=True)
        kept_sections: list[list[str]] = []
        stripped_tables: list[str] = []
        current_lines: list[str] = []
        current_table: str | None = None

        for line in lines:
            # A new top-level table declaration starts at column 0.
            if line and not line[0].isspace() and line.startswith("table "):
                # Flush the previous section.
                if current_lines:
                    if current_table is None or current_table in known_tables or current_table == "Parameters":
                        kept_sections.append(current_lines)
                    else:
                        stripped_tables.append(current_table)
                current_table = PBIPProjectAssemblerAgent._parse_tmdl_table_name(line)
                current_lines = [line]
            else:
                current_lines.append(line)

        # Flush the final section.
        if current_lines:
            if current_table is None or current_table in known_tables or current_table == "Parameters":
                kept_sections.append(current_lines)
            elif current_table is not None:
                stripped_tables.append(current_table)

        return "".join("".join(s) for s in kept_sections), stripped_tables

    def _copy_dax_measures(self, workbook_name: str, target_semantic_model_dir: Path) -> None:
        """Copy ``measures.tmdl`` from the DAX generator into the semantic model's ``definition/`` folder.

        Before writing, strips any ``table`` sections that reference tables
        not present in the generated semantic model.  A ghost table — one with
        no M-query partition anywhere in the model — causes Power BI to create
        an implicit entity-based query source, which triggers the validation
        error "A composite model cannot be used with entity based query sources".
        """
        dax_output_dir = get_output_dir(
            "tmdl_measures_generator_agent",
            workbook_name,
            self.settings,
        )
        measures_file = dax_output_dir / "measures.tmdl"
        if not measures_file.exists():
            self.logger.info("No measures.tmdl found — skipping DAX measures.")
            return

        content = measures_file.read_text(encoding="utf-8")

        known_tables = self._get_model_table_names(workbook_name)
        if known_tables:
            content, stripped = self._strip_unknown_table_sections(content, known_tables)
            for name in stripped:
                self.logger.warning(
                    "Stripped ghost table '%s' from measures.tmdl " "(no matching table in semantic model).",
                    name,
                )

        target = target_semantic_model_dir / "definition" / "measures.tmdl"
        target.parent.mkdir(parents=True, exist_ok=True)
        # TMDL requires CRLF — use write_bytes() to avoid
        # write_text() doubling \r\n on Windows.
        target.write_bytes(content.encode("utf-8"))
        self.logger.info("Copied measures.tmdl into %s", target)

        # ── Ensure every kept table has a partition file ──────────────────
        # A table defined only in measures.tmdl (e.g. Parameters) has no
        # corresponding tables/*.tmdl with an M partition.  Power BI treats
        # such a table as an entity-based query source, which causes the
        # "composite model cannot be used with entity based query sources"
        # validation error at load time.  We create a stub tmdl file for each
        # such table with an empty import partition so the model loads cleanly.
        self._create_stub_table_files(content, target_semantic_model_dir)

    def _collect_tmdl_table_names(self, tmdl_content: str) -> list[str]:
        """Return all table names declared in *tmdl_content* (in order)."""
        names: list[str] = []
        for line in tmdl_content.splitlines():
            if line and not line[0].isspace() and line.startswith("table "):
                names.append(self._parse_tmdl_table_name(line))
        return names

    @staticmethod
    def _render_stub_table_tmdl(table_name: str) -> str:
        """Return a minimal TMDL file for a measures-only table.

        Power BI requires every table in the model to have at least one
        partition with an M query.  Measures-only tables (e.g. ``Parameters``)
        that are defined solely in ``measures.tmdl`` have no partition.  This
        method produces a stub partition that imports an empty result set,
        which satisfies the validator without adding any data.
        """
        quoted = "'" + table_name.replace("'", "''") + "'"
        return (
            f"table {quoted}\n"
            "\n"
            f"\tpartition {quoted} = m\n"
            "\t\tmode: import\n"
            "\t\tsource =\n"
            "\t\t\t\tlet\n"
            '\t\t\t\t    Source = #table({"__placeholder__"}, {})\n'
            "\t\t\t\tin\n"
            "\t\t\t\t    Source\n"
            "\n"
            "\tannotation PBI_NavigationStepName = Navigation\n"
            "\tannotation PBI_ResultType = Table\n"
        )

    def _create_stub_table_files(
        self,
        measures_content: str,
        target_semantic_model_dir: Path,
    ) -> None:
        """Create stub ``tables/*.tmdl`` files for tables that exist only in measures.

        Also appends the corresponding ``ref table`` declarations to
        ``definition/model.tmdl`` so Power BI discovers them.
        """
        tables_dir = target_semantic_model_dir / "definition" / "tables"
        existing = {f.stem for f in tables_dir.glob("*.tmdl")} if tables_dir.exists() else set()

        model_tmdl_path = target_semantic_model_dir / "definition" / "model.tmdl"
        new_refs: list[str] = []

        for table_name in self._collect_tmdl_table_names(measures_content):
            if table_name in existing:
                continue  # already has a full definition
            stub_path = tables_dir / f"{table_name}.tmdl"
            tables_dir.mkdir(parents=True, exist_ok=True)
            # TMDL requires CRLF — use write_bytes() to avoid
            # write_text() doubling \r\n on Windows.
            stub_path.write_bytes(self._render_stub_table_tmdl(table_name).encode("utf-8"))
            existing.add(table_name)
            new_refs.append(table_name)
            self.logger.info(
                "Created stub partition for measures-only table '%s'.",
                table_name,
            )

        if new_refs and model_tmdl_path.exists():
            model_text = model_tmdl_path.read_text(encoding="utf-8")
            # Find the last existing `ref table` line and append after it.
            lines = model_text.splitlines(keepends=True)
            insert_idx = None
            for i, line in enumerate(lines):
                if line.startswith("ref table "):
                    insert_idx = i
            if insert_idx is not None:
                for ref_name in reversed(new_refs):
                    quoted = "'" + ref_name.replace("'", "''") + "'"
                    lines.insert(insert_idx + 1, f"ref table {quoted}\n")
                # TMDL requires CRLF — use write_bytes() to avoid
                # write_text() doubling \r\n on Windows.
                model_tmdl_path.write_bytes("".join(lines).encode("utf-8"))
                self.logger.info(
                    "Added ref table entries for: %s",
                    ", ".join(new_refs),
                )

    def _copy_pbir_report(self, workbook_name: str, output_dir: Path) -> None:
        """Overlay the PBIR report from the visuals generator into the assembled report folder."""
        pbir_output_dir = get_output_dir(
            "pbir_report_generator_agent",
            workbook_name,
            self.settings,
        )
        if not pbir_output_dir.exists() or not pbir_output_dir.is_dir():
            self.logger.info("No PBIR report output found — skipping visuals.")
            return

        # Find the <name>.Report/ directory in the PBIR output
        report_dirs = [
            child for child in pbir_output_dir.iterdir() if child.is_dir() and child.name.endswith(".Report")
        ]
        if not report_dirs:
            self.logger.warning("No '.Report' directory in PBIR output at %s", pbir_output_dir)
            return

        generated_report_dir = report_dirs[0]

        # Find the matching report folder in the assembled output
        target_report_dirs = [
            child for child in output_dir.iterdir() if child.is_dir() and child.name.endswith(".Report")
        ]
        if not target_report_dirs:
            self.logger.warning("No '.Report' directory in assembled output at %s", output_dir)
            return

        target_report_dir = target_report_dirs[0]
        self._copy_tree(generated_report_dir, target_report_dir)
        self.logger.info("Overlaid PBIR report visuals into %s", target_report_dir)

    # ── Reconciliation check ─────────────────────────────────────────────

    def _reconcile_field_references(self, output_dir: Path) -> None:
        """Cross-validate visual field references against the assembled model.

        Scans all ``visual.json`` files in the report folder, extracts
        Entity/Property/queryRef references, and checks each against the
        table/column/measure names actually present in the assembled
        ``.tmdl`` files.  Mismatches (where the LLM deviated from the TDD
        spec) are logged as warnings.

        This is purely diagnostic — mismatches do not block assembly.
        """
        # Collect model names from assembled .tmdl files
        col_re = re.compile(r"^\tcolumn '(.+)'$")
        measure_re = re.compile(r"^\tmeasure '(.+)' =")
        table_re = re.compile(r"^table '(.+)'$")

        model_tables: set[str] = set()
        model_columns: set[str] = set()  # "Table.Column"
        model_measures: set[str] = set()  # "Table.Measure"

        sm_dirs = [d for d in output_dir.iterdir() if d.is_dir() and d.name.endswith(".SemanticModel")]
        for sm_dir in sm_dirs:
            tables_dir = sm_dir / "definition" / "tables"
            if tables_dir.exists():
                for tmdl_file in tables_dir.glob("*.tmdl"):
                    tname = tmdl_file.stem
                    model_tables.add(tname)
                    for line in tmdl_file.read_text(encoding="utf-8").splitlines():
                        mc = col_re.match(line)
                        if mc:
                            model_columns.add(f"{tname}.{mc.group(1)}")

            measures_file = sm_dir / "definition" / "measures.tmdl"
            if measures_file.exists():
                current_table = ""
                for line in measures_file.read_text(encoding="utf-8").splitlines():
                    tm = table_re.match(line)
                    if tm:
                        current_table = tm.group(1)
                        model_tables.add(current_table)
                        continue
                    mm = measure_re.match(line)
                    if mm and current_table:
                        model_measures.add(f"{current_table}.{mm.group(1)}")

        known_fields = model_columns | model_measures
        if not known_fields:
            return  # nothing to reconcile

        # Scan visual.json files for field references
        report_dirs = [d for d in output_dir.iterdir() if d.is_dir() and d.name.endswith(".Report")]
        mismatches: list[str] = []
        entity_prop_re = re.compile(r'"Entity"\s*:\s*"([^"]+)"')
        property_re = re.compile(r'"Property"\s*:\s*"([^"]+)"')

        for report_dir in report_dirs:
            for visual_file in report_dir.rglob("visual.json"):
                try:
                    content = visual_file.read_text(encoding="utf-8")
                except OSError:
                    continue
                entities = entity_prop_re.findall(content)
                properties = property_re.findall(content)
                # Match entities+properties as pairs by order
                for entity, prop in zip(entities, properties):
                    qualified = f"{entity}.{prop}"
                    if entity in model_tables and qualified not in known_fields:
                        page = visual_file.parent.parent.name
                        visual = visual_file.parent.name
                        mismatches.append(f"{page}/{visual}: {qualified}")

        if mismatches:
            self.logger.warning(
                "Reconciliation: %d field reference(s) not found " "in assembled model",
                len(mismatches),
            )
            for m in mismatches[:20]:  # cap log volume
                self.logger.warning("  - %s", m)
        else:
            self.logger.info("Reconciliation: all field references verified.")
