import json
import unittest

from Tableau2PowerBI.agents.skeleton import (
    PBIPProjectSkeletonAgent,
)
from Tableau2PowerBI.core.agent import Agent
from Tableau2PowerBI.core.config import AgentSettings
from tests.support import managed_tempdir


class PBIPProjectSkeletonAgentTests(unittest.TestCase):
    def test_project_skeleton_agent_inherits_base_agent(self):
        settings = AgentSettings(
            project_endpoint="https://example.test",
        )

        agent = PBIPProjectSkeletonAgent(settings=settings)

        self.assertIsInstance(agent, Agent)
        self.assertTrue(callable(agent.generate_pbip_project_skeleton))
        self.assertIn("PBIP Project Skeleton", agent.skill_text)

    def test_generate_pbip_project_skeleton_writes_manifest_and_directories(self):
        with managed_tempdir() as tmpdir:
            settings = AgentSettings(
                project_endpoint="https://example.test",
                output_root=tmpdir,
            )
            agent = PBIPProjectSkeletonAgent(settings=settings)

            output_dir = agent.generate_pbip_project_skeleton("SalesWorkbook")

            pbip_file = output_dir / "SalesWorkbook.pbip"
            self.assertTrue(pbip_file.exists())
            self.assertTrue((output_dir / ".gitignore").exists())
            self.assertTrue((output_dir / "Report.Report").is_dir())
            self.assertTrue((output_dir / "SalesWorkbook.SemanticModel").is_dir())
            self.assertTrue((output_dir / "Report.Report" / "definition.pbir").exists())
            self.assertTrue((output_dir / "Report.Report" / ".platform").exists())
            self.assertTrue((output_dir / "SalesWorkbook.SemanticModel" / "definition.pbism").exists())
            self.assertTrue((output_dir / "SalesWorkbook.SemanticModel" / "model.bim").exists())
            self.assertTrue((output_dir / "SalesWorkbook.SemanticModel" / ".platform").exists())

            manifest = json.loads(pbip_file.read_text(encoding="utf-8"))
            self.assertEqual(manifest["version"], "1.0")
            self.assertEqual(
                manifest["artifacts"],
                [
                    {"report": {"path": "Report.Report"}},
                ],
            )

            report_definition = json.loads(
                (output_dir / "Report.Report" / "definition.pbir").read_text(encoding="utf-8")
            )
            self.assertEqual(
                report_definition["datasetReference"]["byPath"]["path"],
                "../SalesWorkbook.SemanticModel",
            )
            semantic_model_bim = json.loads(
                (output_dir / "SalesWorkbook.SemanticModel" / "model.bim").read_text(encoding="utf-8")
            )
            self.assertEqual(semantic_model_bim["name"], "SalesWorkbook")
            self.assertEqual(semantic_model_bim["model"]["tables"], [])

    def test_generate_pbip_project_skeleton_supports_custom_artifact_names(self):
        with managed_tempdir() as tmpdir:
            settings = AgentSettings(
                project_endpoint="https://example.test",
                output_root=tmpdir,
            )
            agent = PBIPProjectSkeletonAgent(settings=settings)

            output_dir = agent.generate_pbip_project_skeleton(
                "SalesWorkbook",
                report_name="ExecutiveReport",
                semantic_model_name="CoreModel",
            )

            manifest = json.loads((output_dir / "SalesWorkbook.pbip").read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["artifacts"],
                [
                    {"report": {"path": "ExecutiveReport.Report"}},
                ],
            )
            self.assertTrue((output_dir / "ExecutiveReport.Report").is_dir())
            self.assertTrue((output_dir / "CoreModel.SemanticModel").is_dir())
            report_definition = json.loads(
                (output_dir / "ExecutiveReport.Report" / "definition.pbir").read_text(encoding="utf-8")
            )
            self.assertEqual(
                report_definition["datasetReference"]["byPath"]["path"],
                "../CoreModel.SemanticModel",
            )

    def test_generate_pbip_project_skeleton_rejects_invalid_names(self):
        with managed_tempdir() as tmpdir:
            settings = AgentSettings(
                project_endpoint="https://example.test",
                output_root=tmpdir,
            )
            agent = PBIPProjectSkeletonAgent(settings=settings)

            with self.assertRaises(ValueError):
                agent.generate_pbip_project_skeleton("../escape")
