"""PBIPProjectSkeletonAgent — creates the deterministic empty PBIP project scaffold."""

from __future__ import annotations

from pathlib import Path

from Tableau2PowerBI.agents.skeleton.skeleton_file_builder import SkeletonFileBuilder
from Tableau2PowerBI.core.agent import Agent
from Tableau2PowerBI.core.config import AgentSettings
from Tableau2PowerBI.core.output_dirs import (
    ensure_output_dir,
    get_output_dir,
    reset_output_dir,
    resolve_safe_path,
    validate_name,
)


class PBIPProjectSkeletonAgent(Agent):
    """Generate an empty PBIP project scaffold for a Tableau workbook.

    The scaffold establishes folder structure, schema-compliant metadata
    files, and placeholder artefacts.  The semantic model generator and
    assembler agents fill in the real content later.

    File content construction is delegated to :class:`SkeletonFileBuilder`
    for separation of concerns and testability.
    """

    def __init__(self, settings: AgentSettings | None = None):
        super().__init__(
            skill_name="pbip_project_skeleton_agent",
            settings=settings,
        )
        self._builder = SkeletonFileBuilder()

    def generate_pbip_project_skeleton(
        self,
        workbook_name: str,
        report_name: str = "Report",
        semantic_model_name: str | None = None,
        *,
        reset_output: bool = True,
    ) -> Path:
        """Create the PBIP scaffold on disk and return the output directory.

        Args:
            workbook_name: Used as the root folder and ``.pbip`` filename.
            report_name: Folder name for the report artefact.
            semantic_model_name: Folder name for the semantic model artefact.
                Defaults to *workbook_name* if not provided.
        """
        workbook_name = validate_name("Workbook name", workbook_name)
        report_name = validate_name("Report name", report_name)
        semantic_model_name = validate_name(
            "Semantic model name",
            semantic_model_name or workbook_name,
        )

        output_dir = get_output_dir(self.skill_name, workbook_name, self.settings)
        if reset_output:
            reset_output_dir(output_dir)
        else:
            ensure_output_dir(output_dir)

        # ── Root files ─────────────────────────────────────────────────
        self._write_file(output_dir, f"{workbook_name}.pbip", self._builder.pbip_manifest(report_name))
        self._write_file(output_dir, ".gitignore", self._builder.gitignore())

        # ── Report folder ──────────────────────────────────────────────
        report_dir = resolve_safe_path(output_dir, f"{report_name}.Report")
        report_dir.mkdir(parents=True, exist_ok=True)
        self._write_file(report_dir, ".platform", self._builder.platform(report_name, "Report"))
        self._write_file(report_dir, "definition.pbir", self._builder.report_definition_pbir(semantic_model_name))

        # ── Semantic model folder ──────────────────────────────────────
        sm_dir = resolve_safe_path(output_dir, f"{semantic_model_name}.SemanticModel")
        sm_dir.mkdir(parents=True, exist_ok=True)
        self._write_file(sm_dir, ".platform", self._builder.platform(semantic_model_name, "SemanticModel"))
        self._write_file(sm_dir, "definition.pbism", self._builder.semantic_model_definition_pbism())
        self._write_file(sm_dir, "model.bim", self._builder.semantic_model_bim(semantic_model_name))

        self.logger.info("PBIP project skeleton created at %s", output_dir)
        return output_dir

    @staticmethod
    def _write_file(base_path: Path, filename: str, content: str) -> None:
        """Write *content* to *filename* under *base_path* safely."""
        target = resolve_safe_path(base_path, filename)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
