"""Tests for Tableau2PowerBI.cli.run_pipeline.MigrationPipeline."""

import unittest

from tests.support import managed_tempdir


class MigrationPipelineTests(unittest.TestCase):
    """Test the deterministic parts of MigrationPipeline (no Azure calls)."""

    def _make_pipeline(self, path: str, **kwargs):
        """Import and create a MigrationPipeline instance."""
        from Tableau2PowerBI.cli.run_pipeline import MigrationPipeline

        return MigrationPipeline(path, **kwargs)

    def test_raises_when_workbook_not_found(self):
        from Tableau2PowerBI.cli.run_pipeline import MigrationPipeline

        with self.assertRaises(FileNotFoundError):
            MigrationPipeline("nonexistent_file.twb")

    def test_workbook_name_from_path(self):
        with managed_tempdir() as tmpdir:
            twb = tmpdir / "Workbook.twb"
            twb.touch()
            pipeline = self._make_pipeline(str(twb))
            self.assertEqual(pipeline.workbook_name, "Workbook")

    def test_semantic_model_name_defaults_to_workbook_name(self):
        with managed_tempdir() as tmpdir:
            twb = tmpdir / "SalesReport.twb"
            twb.touch()
            pipeline = self._make_pipeline(str(twb))
            self.assertEqual(pipeline.semantic_model_name, "SalesReport")

    def test_semantic_model_name_override(self):
        with managed_tempdir() as tmpdir:
            twb = tmpdir / "Workbook.twb"
            twb.touch()
            pipeline = self._make_pipeline(str(twb), semantic_model_name="Custom Name")
            self.assertEqual(pipeline.semantic_model_name, "Custom Name")

    def test_run_stage_returns_result(self):
        from Tableau2PowerBI.cli.run_pipeline import MigrationPipeline

        result = MigrationPipeline._run_stage("1/1", "Test stage", lambda: "result")
        self.assertEqual(result, "result")

    def test_run_parallel_phase_executes_all_tasks(self):
        from Tableau2PowerBI.cli.run_pipeline import MigrationPipeline

        results = []
        MigrationPipeline._run_parallel_phase(
            "T",
            "Test parallel",
            [
                ("Ta", "task a", lambda: results.append("a")),
                ("Tb", "task b", lambda: results.append("b")),
            ],
        )
        self.assertEqual(sorted(results), ["a", "b"])

    def test_run_parallel_phase_raises_on_failure(self):
        from Tableau2PowerBI.cli.run_pipeline import MigrationPipeline

        def failing():
            raise ValueError("boom")

        with self.assertRaises(RuntimeError) as ctx:
            MigrationPipeline._run_parallel_phase(
                "T",
                "Test fail",
                [
                    ("Ta", "ok", lambda: None),
                    ("Tb", "bad", failing),
                ],
            )
        self.assertIn("Tb", str(ctx.exception))

    def test_settings_propagated_to_pipeline(self):
        from Tableau2PowerBI.core.config import AgentSettings

        with managed_tempdir() as tmpdir:
            twb = tmpdir / "W.twb"
            twb.touch()
            s = AgentSettings(
                project_endpoint="https://test",
                model_dax_measures="o3",
            )
            pipeline = self._make_pipeline(str(twb), settings=s)
            self.assertEqual(pipeline.settings.model_dax_measures, "o3")

    def test_run_returns_assembler_output_dir_when_all_stages_cached(self):
        from unittest.mock import patch

        from Tableau2PowerBI.core.config import AgentSettings

        with managed_tempdir() as tmpdir:
            twb = tmpdir / "Workbook.twb"
            twb.touch()
            settings = AgentSettings(
                project_endpoint="https://test",
                output_root=tmpdir / "output",
                runs_root=tmpdir / "runs",
            )
            output_dir = settings.output_root / "pbip_project_assembler_agent" / "Workbook"
            output_dir.mkdir(parents=True)
            pipeline = self._make_pipeline(str(twb), settings=settings)

            with (
                patch.object(pipeline, "_load_or_create_manifest") as load_manifest,
                patch("Tableau2PowerBI.cli.pipeline.resolve_stages_to_run", return_value=set()),
            ):
                from Tableau2PowerBI.core.run_history import RunManifest

                load_manifest.return_value = RunManifest(
                    run_id="r1",
                    workbook_name="Workbook",
                    workbook_file=str(twb),
                    created_at="t0",
                    updated_at="t0",
                )
                result = pipeline.run()

            self.assertEqual(result, output_dir)


class BuildSettingsTests(unittest.TestCase):
    """Tests for _build_settings() (CLI --models flag)."""

    def test_no_overrides_returns_default(self):
        from Tableau2PowerBI.cli.run_pipeline import _build_settings

        settings = _build_settings(None)
        self.assertEqual(settings.model_dax_measures, "gpt-5.4")

    def test_single_override(self):
        from Tableau2PowerBI.cli.run_pipeline import _build_settings

        settings = _build_settings('{"dax_measures": "o3"}')
        self.assertEqual(settings.model_dax_measures, "o3")
        # Other agents unchanged
        self.assertEqual(settings.model_semantic_model, "gpt-5.4")

    def test_multiple_overrides(self):
        from Tableau2PowerBI.cli.run_pipeline import _build_settings

        settings = _build_settings('{"dax_measures": "o3", "semantic_model": "gpt-4.1"}')
        self.assertEqual(settings.model_dax_measures, "o3")
        self.assertEqual(settings.model_semantic_model, "gpt-4.1")

    def test_unknown_agent_name_raises(self):
        from Tableau2PowerBI.cli.run_pipeline import _build_settings

        with self.assertRaises(ValueError) as ctx:
            _build_settings('{"nonexistent": "gpt-4.1"}')
        self.assertIn("nonexistent", str(ctx.exception))

    def test_invalid_json_raises(self):
        import json

        from Tableau2PowerBI.cli.run_pipeline import _build_settings

        with self.assertRaises(json.JSONDecodeError):
            _build_settings("not json")
