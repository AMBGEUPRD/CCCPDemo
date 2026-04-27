"""Smoke tests for thin CLI entry-point modules."""

from __future__ import annotations

import types
import unittest
from unittest.mock import MagicMock, patch


class CliRunnerTests(unittest.TestCase):
    """Verify the thin CLI wrappers parse args and call their agents."""

    def test_run_extraction_invokes_metadata_extractor(self) -> None:
        with (
            patch("sys.argv", ["t2pbi-extract", "Workbook.twbx"]),
            patch("Tableau2PowerBI.cli.run_extraction.setup_logging"),
            patch("Tableau2PowerBI.cli.run_extraction.TableauMetadataExtractorAgent") as agent_cls,
        ):
            from Tableau2PowerBI.cli.run_extraction import main

            main()

        agent_cls.return_value.extract_tableau_metadata.assert_called_once_with("Workbook.twbx")

    def test_run_skeleton_invokes_skeleton_agent(self) -> None:
        with (
            patch("sys.argv", ["t2pbi-skeleton", "Workbook", "--semantic-model-name", "Sales Model"]),
            patch("Tableau2PowerBI.cli.run_skeleton.setup_logging"),
            patch("Tableau2PowerBI.cli.run_skeleton.PBIPProjectSkeletonAgent") as agent_cls,
        ):
            from Tableau2PowerBI.cli.run_skeleton import main

            main()

        agent_cls.return_value.generate_pbip_project_skeleton.assert_called_once_with(
            "Workbook",
            report_name="Workbook",
            semantic_model_name="Sales Model",
        )

    def test_run_semantic_model_invokes_created_agent(self) -> None:
        with (
            patch("sys.argv", ["t2pbi-semantic", "Workbook"]),
            patch("Tableau2PowerBI.cli.run_semantic_model.setup_logging"),
            patch("Tableau2PowerBI.cli.run_semantic_model.PBIPSemanticModelGeneratorAgent") as agent_cls,
        ):
            created_agent = MagicMock()
            agent_cls.return_value.create.return_value = created_agent
            from Tableau2PowerBI.cli.run_semantic_model import main

            main()

        created_agent.generate_pbip_semantic_model.assert_called_once_with(
            "Workbook",
            semantic_model_name="Workbook",
        )

    def test_run_assemble_invokes_assembler_agent(self) -> None:
        with (
            patch("sys.argv", ["t2pbi-assemble", "Workbook"]),
            patch("Tableau2PowerBI.cli.run_assemble_pbip_project.setup_logging"),
            patch("Tableau2PowerBI.cli.run_assemble_pbip_project.PBIPProjectAssemblerAgent") as agent_cls,
        ):
            from Tableau2PowerBI.cli.run_assemble_pbip_project import main

            main()

        agent_cls.return_value.assemble_pbip_project.assert_called_once_with("Workbook")

    def test_run_functional_doc_invokes_context_managed_agent(self) -> None:
        with (
            patch("sys.argv", ["t2pbi-funcdoc", "Workbook", "--data-folder", "data/golden/Workbook"]),
            patch("Tableau2PowerBI.cli.run_functional_doc.setup_logging"),
            patch("Tableau2PowerBI.cli.run_functional_doc.FunctionalDocAgent") as agent_cls,
        ):
            agent = agent_cls.return_value
            agent.generate_documentation.return_value = ("out.md", "out.html")
            from Tableau2PowerBI.cli.run_functional_doc import main

            main()

        agent.create.assert_called_once_with()
        agent.generate_documentation.assert_called_once_with(
            "Workbook",
            data_folder_path="data/golden/Workbook",
        )

    def test_run_target_technical_doc_invokes_context_managed_agent(self) -> None:
        with (
            patch("sys.argv", ["t2pbi-tdd", "Workbook"]),
            patch("Tableau2PowerBI.cli.run_target_technical_doc.setup_logging"),
            patch("Tableau2PowerBI.cli.run_target_technical_doc.TargetTechnicalDocAgent") as agent_cls,
        ):
            agent = agent_cls.return_value
            agent.generate_tdd.return_value = types.SimpleNamespace(
                semantic_model=types.SimpleNamespace(tables=[1, 2]),
                dax_measures=types.SimpleNamespace(measures=[1]),
                report=types.SimpleNamespace(pages=[1, 2, 3]),
            )
            from Tableau2PowerBI.cli.run_target_technical_doc import main

            main()

        agent.create.assert_called_once_with()
        agent.generate_tdd.assert_called_once_with("Workbook", data_folder_path=None)

    def test_cancel_stuck_responses_cancels_active_response(self) -> None:
        azure_module = types.ModuleType("azure")
        azure_ai_module = types.ModuleType("azure.ai")
        azure_projects_module = types.ModuleType("azure.ai.projects")
        azure_projects_module.AIProjectClient = object
        azure_identity_module = types.ModuleType("azure.identity")
        azure_identity_module.DefaultAzureCredential = object

        project_client = MagicMock()
        openai_client = MagicMock()
        response = types.SimpleNamespace(status="in_progress")
        cancelled = types.SimpleNamespace(status="cancelling")
        project_client.get_openai_client.return_value = openai_client
        openai_client.responses.retrieve.return_value = response
        openai_client.responses.cancel.return_value = cancelled

        with (
            patch.dict(
                "sys.modules",
                {
                    "azure": azure_module,
                    "azure.ai": azure_ai_module,
                    "azure.ai.projects": azure_projects_module,
                    "azure.identity": azure_identity_module,
                },
            ),
            patch("sys.argv", ["t2pbi-cancel-stuck-response", "resp_123"]),
            patch("Tableau2PowerBI.cli.cancel_stuck_responses._create_project_client", return_value=project_client),
        ):
            from Tableau2PowerBI.cli.cancel_stuck_responses import main

            main()

        openai_client.responses.retrieve.assert_called_once_with(response_id="resp_123")
        openai_client.responses.cancel.assert_called_once_with(response_id="resp_123")
