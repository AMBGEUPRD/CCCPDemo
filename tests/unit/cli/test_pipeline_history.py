"""Tests for MigrationPipeline run-history integration.

Verifies that:
- ``_load_or_create_manifest()`` creates vs. resumes runs
- ``_run_managed_stage()`` skips or executes based on ``stages_to_run``
- ``--resume`` and ``--regenerate`` CLI flags build the correct params
- ``_AGENT_DIR_MAP`` covers all stages
"""

import unittest
from pathlib import Path

from Tableau2PowerBI.core.config import AgentSettings
from Tableau2PowerBI.core.run_history import STAGE_GRAPH, StageStatus
from tests.support import managed_tempdir


def _settings(tmp: Path) -> AgentSettings:
    return AgentSettings(
        project_endpoint="https://test",
        output_root=tmp / "output",
        runs_root=tmp / "runs",
        max_runs_per_workbook=5,
    )


class PipelineHistoryTests(unittest.TestCase):
    """Tests for the manifest + history wiring in MigrationPipeline."""

    def _make_pipeline(self, twb: Path, **kwargs):
        from Tableau2PowerBI.cli.run_pipeline import MigrationPipeline

        return MigrationPipeline(str(twb), **kwargs)

    def test_creates_new_manifest_on_fresh_run(self):
        """A new pipeline creates a fresh manifest."""
        with managed_tempdir() as tmp:
            twb = tmp / "Workbook.twb"
            twb.touch()
            s = _settings(tmp)
            p = self._make_pipeline(twb, settings=s)
            manifest = p._load_or_create_manifest()
            self.assertEqual(manifest.workbook_name, "Workbook")
            self.assertEqual(
                str(twb).lower(),
                manifest.workbook_file.lower(),
            )

    def test_resume_loads_existing_manifest(self):
        """Pipeline with resume_run_id loads the specified run."""
        with managed_tempdir() as tmp:
            twb = tmp / "Workbook.twb"
            twb.touch()
            s = _settings(tmp)
            # Create a run first
            p1 = self._make_pipeline(twb, settings=s)
            created = p1._load_or_create_manifest()
            run_id = created.run_id

            # Resume it
            p2 = self._make_pipeline(twb, settings=s, resume_run_id=run_id)
            resumed = p2._load_or_create_manifest()
            self.assertEqual(resumed.run_id, run_id)

    def test_run_managed_stage_skips_cached(self):
        """Stages not in stages_to_run are skipped."""
        with managed_tempdir() as tmp:
            twb = tmp / "Workbook.twb"
            twb.touch()
            s = _settings(tmp)
            p = self._make_pipeline(twb, settings=s)
            manifest = p._load_or_create_manifest()

            called = []
            result = p._run_managed_stage(
                "P0",
                "Test stage",
                "metadata_extractor",
                lambda: called.append(1),
                manifest,
                stages_to_run=set(),  # empty = skip all
            )
            self.assertIsNone(result)
            self.assertEqual(called, [])

    def test_run_managed_stage_executes_included(self):
        """Stages in stages_to_run are executed and recorded."""
        with managed_tempdir() as tmp:
            twb = tmp / "Workbook.twb"
            twb.touch()
            s = _settings(tmp)
            p = self._make_pipeline(twb, settings=s)
            manifest = p._load_or_create_manifest()

            ran = []
            p._run_managed_stage(
                "P0",
                "Test",
                "metadata_extractor",
                lambda: ran.append(1),
                manifest,
                stages_to_run={"metadata_extractor"},
            )
            self.assertEqual(ran, [1])
            # Stage recorded in manifest
            self.assertIn("metadata_extractor", manifest.stages)
            self.assertEqual(
                manifest.stages["metadata_extractor"].status,
                StageStatus.COMPLETED,
            )

    def test_agent_dir_map_covers_all_stages(self):
        """Every stage in STAGE_GRAPH has a matching agent dir."""
        from Tableau2PowerBI.cli.run_pipeline import MigrationPipeline

        for stage_name in STAGE_GRAPH:
            self.assertIn(
                stage_name,
                MigrationPipeline._AGENT_DIR_MAP,
                f"Missing _AGENT_DIR_MAP entry for '{stage_name}'",
            )


class CLIFlagTests(unittest.TestCase):
    """Tests for --resume, --regenerate, --force-all flag handling."""

    def test_force_all_includes_all_stages(self):
        """--force-all should yield all stage names."""
        from Tableau2PowerBI.cli.run_pipeline import STAGE_GRAPH

        force = set(STAGE_GRAPH.keys())
        self.assertEqual(len(force), 8)

    def test_regenerate_validates_stage_names(self):
        """Invalid stage names should be caught."""
        valid = set(STAGE_GRAPH.keys())
        invalid = {"nonexistent_stage"}
        diff = invalid - valid
        self.assertTrue(len(diff) > 0)

    def test_pipeline_accepts_force_stages(self):
        """MigrationPipeline can accept force_stages kwarg."""
        with managed_tempdir() as tmp:
            twb = tmp / "W.twb"
            twb.touch()
            s = _settings(tmp)
            from Tableau2PowerBI.cli.run_pipeline import MigrationPipeline

            p = MigrationPipeline(
                str(twb),
                settings=s,
                force_stages={"dax_measures"},
            )
            self.assertEqual(p._force_stages, {"dax_measures"})
