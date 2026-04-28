"""Tests for the webapp run-history API endpoints.

Verifies the ``/api/history`` router: listing workbooks, listing runs,
fetching a manifest, restoring a run, deleting a run, enriched responses,
project page route, force_stages validation, and ZIP download.
"""

import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from Tableau2PowerBI.core.config import AgentSettings
from Tableau2PowerBI.core.run_history import RunHistory, StageStatus
from tests.support import managed_tempdir


def _patch_settings(tmp: Path):
    """Return a mock ``get_agent_settings`` pointing at *tmp*."""
    return AgentSettings(
        project_endpoint="https://test",
        output_root=tmp / "output",
        runs_root=tmp / "runs",
        max_runs_per_workbook=10,
    )


class HistoryEndpointTests(unittest.TestCase):
    """Integration-style tests using FastAPI TestClient."""

    def _get_client(self, tmp: Path):
        """Build a test client with settings pointing at tmp."""
        from unittest.mock import patch

        settings = _patch_settings(tmp)
        with (
            patch(
                "Tableau2PowerBI.webapp.history.get_agent_settings",
                return_value=settings,
            ),
            patch(
                "Tableau2PowerBI.webapp.app.get_agent_settings",
                return_value=settings,
            ),
        ):
            from Tableau2PowerBI.webapp.app import app

            return TestClient(app)

    def _create_run(self, tmp: Path, workbook: str = "TestWB"):
        """Create a run via RunHistory and return the manifest."""
        settings = _patch_settings(tmp)
        history = RunHistory(
            runs_root=settings.runs_root,
            output_root=settings.output_root,
        )
        manifest = history.create_run(workbook, f"{workbook}.twb")
        history.update_stage(
            manifest,
            "metadata_extractor",
            status=StageStatus.COMPLETED,
            deterministic=True,
        )
        return manifest

    def test_list_workbooks_empty(self):
        with managed_tempdir() as tmp:
            from unittest.mock import patch

            settings = _patch_settings(tmp)
            with patch(
                "Tableau2PowerBI.webapp.history.get_agent_settings",
                return_value=settings,
            ):
                from Tableau2PowerBI.webapp.app import app

                client = TestClient(app)
                resp = client.get("/api/history")
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(resp.json(), [])

    def test_list_workbooks_with_run(self):
        with managed_tempdir() as tmp:
            self._create_run(tmp)
            from unittest.mock import patch

            settings = _patch_settings(tmp)
            with patch(
                "Tableau2PowerBI.webapp.history.get_agent_settings",
                return_value=settings,
            ):
                from Tableau2PowerBI.webapp.app import app

                client = TestClient(app)
                resp = client.get("/api/history")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertEqual(len(data), 1)
                self.assertEqual(data[0]["workbook_name"], "TestWB")

    def test_list_runs_for_workbook(self):
        with managed_tempdir() as tmp:
            manifest = self._create_run(tmp)
            from unittest.mock import patch

            settings = _patch_settings(tmp)
            with patch(
                "Tableau2PowerBI.webapp.history.get_agent_settings",
                return_value=settings,
            ):
                from Tableau2PowerBI.webapp.app import app

                client = TestClient(app)
                resp = client.get("/api/history/TestWB")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertEqual(len(data), 1)
                self.assertEqual(data[0]["run_id"], manifest.run_id)

    def test_get_run_manifest(self):
        with managed_tempdir() as tmp:
            manifest = self._create_run(tmp)
            from unittest.mock import patch

            settings = _patch_settings(tmp)
            with patch(
                "Tableau2PowerBI.webapp.history.get_agent_settings",
                return_value=settings,
            ):
                from Tableau2PowerBI.webapp.app import app

                client = TestClient(app)
                resp = client.get(f"/api/history/TestWB/{manifest.run_id}")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertEqual(data["run_id"], manifest.run_id)
                self.assertIn("metadata_extractor", data["stages"])

    def test_get_nonexistent_run_returns_404(self):
        with managed_tempdir() as tmp:
            from unittest.mock import patch

            settings = _patch_settings(tmp)
            with patch(
                "Tableau2PowerBI.webapp.history.get_agent_settings",
                return_value=settings,
            ):
                from Tableau2PowerBI.webapp.app import app

                client = TestClient(app)
                resp = client.get("/api/history/TestWB/nonexistent")
                self.assertEqual(resp.status_code, 404)

    def test_delete_run(self):
        with managed_tempdir() as tmp:
            manifest = self._create_run(tmp)
            settings = _patch_settings(tmp)
            from unittest.mock import patch

            with patch(
                "Tableau2PowerBI.webapp.history.get_agent_settings",
                return_value=settings,
            ):
                from Tableau2PowerBI.webapp.app import app

                client = TestClient(app)
                resp = client.delete(f"/api/history/TestWB/{manifest.run_id}")
                self.assertEqual(resp.status_code, 200)
                # Verify it's gone
                resp2 = client.get(f"/api/history/TestWB/{manifest.run_id}")
                self.assertEqual(resp2.status_code, 404)

    def test_invalid_workbook_name_rejected(self):
        """Names with special characters should be rejected."""
        with managed_tempdir() as tmp:
            from unittest.mock import patch

            settings = _patch_settings(tmp)
            with patch(
                "Tableau2PowerBI.webapp.history.get_agent_settings",
                return_value=settings,
            ):
                from Tableau2PowerBI.webapp.app import app

                client = TestClient(app)
                # Name with forbidden path-traversal characters
                resp = client.get("/api/history/bad<>name")
                self.assertEqual(resp.status_code, 400)

    def test_restore_run(self):
        """Restore creates result_id and copies artefacts back."""
        with managed_tempdir() as tmp:
            settings = _patch_settings(tmp)
            history = RunHistory(
                runs_root=settings.runs_root,
                output_root=settings.output_root,
            )
            manifest = history.create_run("RestoreWB", "RestoreWB.twb")
            # Create a fake extraction artefact
            out_dir = settings.output_root / "tableau_metadata_extractor_agent" / "RestoreWB"
            out_dir.mkdir(parents=True)
            (out_dir / "analysis_result.json").write_text('{"key": "value"}')
            history.store_artifacts(manifest, "tableau_metadata_extractor_agent")
            history.update_stage(
                manifest,
                "metadata_extractor",
                status=StageStatus.COMPLETED,
                deterministic=True,
            )
            # Remove from output to simulate a fresh session
            import shutil

            shutil.rmtree(out_dir)

            from unittest.mock import patch

            with (
                patch(
                    "Tableau2PowerBI.webapp.history.get_agent_settings",
                    return_value=settings,
                ),
                patch(
                    "Tableau2PowerBI.webapp.app.get_agent_settings",
                    return_value=settings,
                ),
            ):
                from Tableau2PowerBI.webapp.app import app

                client = TestClient(app)
                resp = client.post(f"/api/history/RestoreWB/{manifest.run_id}/restore")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertIn("result_id", data)
                self.assertEqual(data["run_id"], manifest.run_id)

                # Verify artefacts were restored
                self.assertTrue((out_dir / "analysis_result.json").exists())

    def test_list_workbooks_enriched_fields(self):
        """Enriched /api/history returns completion_pct, total_runs, latest_status."""
        with managed_tempdir() as tmp:
            self._create_run(tmp)
            from unittest.mock import patch

            settings = _patch_settings(tmp)
            with patch(
                "Tableau2PowerBI.webapp.history.get_agent_settings",
                return_value=settings,
            ):
                from Tableau2PowerBI.webapp.app import app

                client = TestClient(app)
                resp = client.get("/api/history")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                item = data[0]
                # completion_pct: 1 completed out of 3 total stages
                self.assertIn("completion_pct", item)
                self.assertEqual(item["completion_pct"], 33)  # round(1/3*100) = 33
                self.assertIn("total_runs", item)
                self.assertEqual(item["total_runs"], 1)
                self.assertIn("latest_status", item)
                self.assertEqual(item["latest_status"], "in_progress")

    def test_list_runs_enriched_stages_full(self):
        """Enriched /api/history/{wb} returns stages_full with all 8 stages."""
        with managed_tempdir() as tmp:
            self._create_run(tmp)
            from unittest.mock import patch

            settings = _patch_settings(tmp)
            with patch(
                "Tableau2PowerBI.webapp.history.get_agent_settings",
                return_value=settings,
            ):
                from Tableau2PowerBI.webapp.app import app

                client = TestClient(app)
                resp = client.get("/api/history/TestWB")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                run = data[0]
                self.assertIn("stages_full", run)
                stages_full = run["stages_full"]
                # All 3 STAGE_GRAPH stages are present
                self.assertEqual(len(stages_full), 3)
                self.assertEqual(stages_full["metadata_extractor"]["status"], "completed")
                # Upstream dependency info is present
                self.assertEqual(stages_full["metadata_extractor"]["upstream"], [])
                self.assertEqual(stages_full["functional_doc"]["upstream"], ["metadata_extractor"])
                self.assertEqual(
                    sorted(stages_full["target_technical_doc"]["upstream"]),
                    ["functional_doc", "metadata_extractor"],
                )
                self.assertIn("completion_pct", run)
                self.assertIn("download_available", run)
                self.assertFalse(run["download_available"])

    def test_restore_returns_redirect_to(self):
        """Restore endpoint includes redirect_to field."""
        with managed_tempdir() as tmp:
            settings = _patch_settings(tmp)
            history = RunHistory(
                runs_root=settings.runs_root,
                output_root=settings.output_root,
            )
            manifest = history.create_run("RedirectWB", "RedirectWB.twb")
            history.update_stage(
                manifest,
                "metadata_extractor",
                status=StageStatus.COMPLETED,
                deterministic=True,
            )
            from unittest.mock import patch

            with (
                patch(
                    "Tableau2PowerBI.webapp.history.get_agent_settings",
                    return_value=settings,
                ),
                patch(
                    "Tableau2PowerBI.webapp.app.get_agent_settings",
                    return_value=settings,
                ),
            ):
                from Tableau2PowerBI.webapp.app import app

                client = TestClient(app)
                resp = client.post(f"/api/history/RedirectWB/{manifest.run_id}/restore")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertIn("redirect_to", data)

    def test_download_returns_404_when_no_assembler(self):
        """Download endpoint returns 404 if no assembled output exists."""
        with managed_tempdir() as tmp:
            manifest = self._create_run(tmp)
            from unittest.mock import patch

            settings = _patch_settings(tmp)
            with patch(
                "Tableau2PowerBI.webapp.history.get_agent_settings",
                return_value=settings,
            ):
                from Tableau2PowerBI.webapp.app import app

                client = TestClient(app)
                resp = client.get(f"/api/history/TestWB/{manifest.run_id}/download")
                self.assertEqual(resp.status_code, 404)

    def test_download_returns_zip_when_assembler_exists(self):
        """Download endpoint streams a valid ZIP when assembler output exists."""
        import io
        import zipfile

        with managed_tempdir() as tmp:
            manifest = self._create_run(tmp)
            settings = _patch_settings(tmp)
            # Create fake assembler output in the run folder
            assembler_dir = settings.runs_root / "TestWB" / manifest.run_id / "pbip_project_assembler_agent"
            assembler_dir.mkdir(parents=True)
            (assembler_dir / "test.pbip").write_text('{"version": "1.0"}')
            (assembler_dir / "Report").mkdir()
            (assembler_dir / "Report" / "page.json").write_text("{}")

            from unittest.mock import patch

            with patch(
                "Tableau2PowerBI.webapp.history.get_agent_settings",
                return_value=settings,
            ):
                from Tableau2PowerBI.webapp.app import app

                client = TestClient(app)
                resp = client.get(f"/api/history/TestWB/{manifest.run_id}/download")
                self.assertEqual(resp.status_code, 200)
                self.assertIn("application/zip", resp.headers.get("content-type", ""))
                # Verify it's a valid ZIP with expected files
                zf = zipfile.ZipFile(io.BytesIO(resp.content))
                names = zf.namelist()
                self.assertTrue(any("test.pbip" in n for n in names))
                self.assertTrue(any("page.json" in n for n in names))

    def test_project_page_returns_404_for_unknown_workbook(self):
        """GET /project/{name} returns 404 when no runs exist."""
        with managed_tempdir() as tmp:
            from unittest.mock import patch

            settings = _patch_settings(tmp)
            with (
                patch(
                    "Tableau2PowerBI.webapp.history.get_agent_settings",
                    return_value=settings,
                ),
                patch(
                    "Tableau2PowerBI.webapp.app.get_agent_settings",
                    return_value=settings,
                ),
            ):
                from Tableau2PowerBI.webapp.app import app

                client = TestClient(app)
                resp = client.get("/project/NonExistent")
                self.assertEqual(resp.status_code, 404)

    def test_project_page_returns_200_for_existing_workbook(self):
        """GET /project/{name} returns 200 when runs exist."""
        with managed_tempdir() as tmp:
            self._create_run(tmp, workbook="ProjectWB")
            from unittest.mock import patch

            settings = _patch_settings(tmp)
            with (
                patch(
                    "Tableau2PowerBI.webapp.history.get_agent_settings",
                    return_value=settings,
                ),
                patch(
                    "Tableau2PowerBI.webapp.app.get_agent_settings",
                    return_value=settings,
                ),
            ):
                from Tableau2PowerBI.webapp.app import app

                client = TestClient(app)
                resp = client.get("/project/ProjectWB")
                self.assertEqual(resp.status_code, 200)
                self.assertIn("Project Dashboard", resp.text)

    def test_restore_falls_back_to_tableau_metadata(self):
        """Restore loads tableau_metadata.json when analysis_result.json is absent."""
        with managed_tempdir() as tmp:
            settings = _patch_settings(tmp)
            history = RunHistory(
                runs_root=settings.runs_root,
                output_root=settings.output_root,
            )
            manifest = history.create_run("FallbackWB", "FallbackWB.twb")
            # Write only tableau_metadata.json (no analysis_result.json)
            out_dir = settings.output_root / "tableau_metadata_extractor_agent" / "FallbackWB"
            out_dir.mkdir(parents=True)
            (out_dir / "tableau_metadata.json").write_text('{"datasources": []}')
            history.store_artifacts(manifest, "tableau_metadata_extractor_agent")
            history.update_stage(
                manifest,
                "metadata_extractor",
                status=StageStatus.COMPLETED,
                deterministic=True,
            )
            import shutil

            shutil.rmtree(out_dir)

            from unittest.mock import patch

            with (
                patch(
                    "Tableau2PowerBI.webapp.history.get_agent_settings",
                    return_value=settings,
                ),
                patch(
                    "Tableau2PowerBI.webapp.app.get_agent_settings",
                    return_value=settings,
                ),
            ):
                from Tableau2PowerBI.webapp.app import app

                client = TestClient(app)
                resp = client.post(f"/api/history/FallbackWB/{manifest.run_id}/restore")
                self.assertEqual(resp.status_code, 200)
                data = resp.json()
                self.assertIn("result_id", data)

                # Verify the result store has the metadata content
                from Tableau2PowerBI.webapp.app import _result_store

                result_id = data["result_id"]
                self.assertIn(result_id, _result_store)
                import json

                payload = json.loads(_result_store[result_id][1])
                self.assertIn("datasources", json.loads(payload["result"]))
