import json
import unittest
from unittest.mock import patch

from Tableau2PowerBI.agents.metadata_extractor import (
    TableauMetadataExtractorAgent,
)
from Tableau2PowerBI.core.agent import DeterministicAgent
from Tableau2PowerBI.core.config import AgentSettings
from tests.support import managed_tempdir


class TableauMetadataExtractorAgentTests(unittest.TestCase):
    def test_metadata_extractor_inherits_deterministic_base(self):
        settings = AgentSettings(
            project_endpoint="https://example.test",
        )

        agent = TableauMetadataExtractorAgent(settings=settings)

        self.assertIsInstance(agent, DeterministicAgent)
        self.assertIn("Tableau Source Understanding", agent.skill_text)

    def test_extract_tableau_metadata_writes_expected_json_outputs(self):
        sample_metadata = {
            "datasources": [
                {
                    "name": "Sales",
                    "caption": "Sales",
                    "connection": {"type": "excel-direct"},
                    "tables": [{"name": "Orders", "physical_table": "[Orders$]", "columns": []}],
                    "joins": [],
                    "relationships": [],
                    "col_mapping": [],
                    "columns": [{"name": "[Sales]", "role": "measure"}],
                    "calculated_fields": [],
                    "groups": [],
                    "sets": [],
                    "metadata_records": [],
                }
            ],
            "worksheets": [],
            "dashboards": [],
            "actions": [],
            "parameters": [],
        }

        with managed_tempdir() as tmpdir:
            settings = AgentSettings(
                project_endpoint="https://example.test",
                output_root=tmpdir,
            )
            agent = TableauMetadataExtractorAgent(settings=settings)
            metadata_json = json.dumps(sample_metadata)

            with patch(
                "Tableau2PowerBI.agents.metadata_extractor.read_twb_file",
                return_value=metadata_json,
            ):
                result = agent.extract_tableau_metadata("example.twb")

            self.assertEqual(result, metadata_json)
            output_dir = tmpdir / "tableau_metadata_extractor_agent" / "example"
            self.assertTrue((output_dir / "tableau_metadata.json").exists())
            self.assertTrue((output_dir / "semantic_model_input.json").exists())
            self.assertTrue((output_dir / "report_input.json").exists())
            self.assertTrue((output_dir / "connections_input.json").exists())
            self.assertTrue((output_dir / "parameters_input.json").exists())
            self.assertTrue((output_dir / "functional_doc_input_slim.json").exists())
