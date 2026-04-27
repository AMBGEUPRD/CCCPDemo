import unittest

from Tableau2PowerBI.agents.assembler import (
    PBIPProjectAssemblerAgent,
)
from Tableau2PowerBI.core.agent import DeterministicAgent
from Tableau2PowerBI.core.config import AgentSettings
from tests.support import managed_tempdir


class PBIPProjectAssemblerAgentTests(unittest.TestCase):
    def test_project_assembler_agent_inherits_deterministic_base(self):
        settings = AgentSettings(
            project_endpoint="https://example.test",
        )

        agent = PBIPProjectAssemblerAgent(settings=settings)

        self.assertIsInstance(agent, DeterministicAgent)
        self.assertTrue(callable(agent.assemble_pbip_project))
        self.assertIn("PBIP Project Assembler", agent.skill_text)

    def test_assemble_pbip_project_merges_skeleton_and_generated_model(self):
        with managed_tempdir() as tmpdir:
            settings = AgentSettings(
                project_endpoint="https://example.test",
                output_root=tmpdir,
            )
            agent = PBIPProjectAssemblerAgent(settings=settings)

            skeleton_dir = tmpdir / "pbip_project_skeleton_agent" / "SalesWorkbook"
            report_dir = skeleton_dir / "Report.Report"
            semantic_skeleton_dir = skeleton_dir / "SalesWorkbook.SemanticModel"
            report_dir.mkdir(parents=True, exist_ok=True)
            semantic_skeleton_dir.mkdir(parents=True, exist_ok=True)
            (skeleton_dir / "SalesWorkbook.pbip").write_text("{}", encoding="utf-8")
            (skeleton_dir / ".gitignore").write_text("cache", encoding="utf-8")
            (report_dir / "definition.pbir").write_text("report", encoding="utf-8")
            (semantic_skeleton_dir / "model.bim").write_text("placeholder", encoding="utf-8")

            generated_dir = (
                tmpdir / "pbip_semantic_model_generator_agent" / "SalesWorkbook" / "SalesWorkbook.SemanticModel"
            )
            (generated_dir / "definition").mkdir(parents=True, exist_ok=True)
            (generated_dir / ".platform").write_text("platform", encoding="utf-8")
            (generated_dir / "definition.pbism").write_text("pbism", encoding="utf-8")
            (generated_dir / "definition" / "model.tmdl").write_text(
                "semantic-model",
                encoding="utf-8",
            )
            (generated_dir / "definition" / "expressions.tmdl").write_text(
                "expression TaxRate = 0.2 meta [IsParameterQuery=true]\n",
                encoding="utf-8",
            )

            output_dir = agent.assemble_pbip_project("SalesWorkbook")

            self.assertTrue((output_dir / "SalesWorkbook.pbip").exists())
            self.assertTrue((output_dir / ".gitignore").exists())
            self.assertTrue((output_dir / "Report.Report" / "definition.pbir").exists())
            self.assertTrue((output_dir / "SalesWorkbook.SemanticModel" / "definition" / "model.tmdl").exists())
            self.assertFalse((output_dir / "SalesWorkbook.SemanticModel" / "model.bim").exists())
            self.assertTrue((output_dir / "SalesWorkbook.SemanticModel" / "definition" / "expressions.tmdl").exists())

    def test_assemble_pbip_project_warns_when_retargeting_model_folder(self):
        with managed_tempdir() as tmpdir:
            settings = AgentSettings(
                project_endpoint="https://example.test",
                output_root=tmpdir,
            )
            agent = PBIPProjectAssemblerAgent(settings=settings)

            skeleton_dir = tmpdir / "pbip_project_skeleton_agent" / "SalesWorkbook"
            (skeleton_dir / "SalesWorkbook.pbip").parent.mkdir(parents=True, exist_ok=True)
            (skeleton_dir / "SalesWorkbook.pbip").write_text("{}", encoding="utf-8")
            (skeleton_dir / "Report.Report").mkdir(parents=True, exist_ok=True)
            (skeleton_dir / "SalesWorkbook.SemanticModel").mkdir(parents=True, exist_ok=True)

            generated_dir = (
                tmpdir / "pbip_semantic_model_generator_agent" / "SalesWorkbook" / "ChosenModel.SemanticModel"
            )
            generated_dir.mkdir(parents=True, exist_ok=True)
            (generated_dir / "definition.pbism").write_text("pbism", encoding="utf-8")

            with self.assertLogs("Tableau2PowerBI.pbip_project_assembler_agent", level="WARNING") as captured:
                agent.assemble_pbip_project("SalesWorkbook")

            self.assertTrue(
                any(
                    "Retargeting 'ChosenModel.SemanticModel' to 'SalesWorkbook.SemanticModel'" in message
                    for message in captured.output
                )
            )

    def test_assemble_pbip_project_requires_existing_inputs(self):
        with managed_tempdir() as tmpdir:
            settings = AgentSettings(
                project_endpoint="https://example.test",
                output_root=tmpdir,
            )
            agent = PBIPProjectAssemblerAgent(settings=settings)

            with self.assertRaises(FileNotFoundError):
                agent.assemble_pbip_project("SalesWorkbook")

    def test_assemble_pbip_project_copies_extracted_data_files(self):
        with managed_tempdir() as tmpdir:
            settings = AgentSettings(
                project_endpoint="https://example.test",
                output_root=tmpdir,
            )
            agent = PBIPProjectAssemblerAgent(settings=settings)

            # Set up skeleton
            skeleton_dir = tmpdir / "pbip_project_skeleton_agent" / "SalesWorkbook"
            (skeleton_dir / "SalesWorkbook.pbip").parent.mkdir(parents=True, exist_ok=True)
            (skeleton_dir / "SalesWorkbook.pbip").write_text("{}", encoding="utf-8")
            (skeleton_dir / "Report.Report").mkdir(parents=True, exist_ok=True)
            (skeleton_dir / "SalesWorkbook.SemanticModel").mkdir(parents=True, exist_ok=True)

            # Set up generated semantic model
            generated_dir = (
                tmpdir / "pbip_semantic_model_generator_agent" / "SalesWorkbook" / "SalesWorkbook.SemanticModel"
            )
            generated_dir.mkdir(parents=True, exist_ok=True)
            (generated_dir / "definition.pbism").write_text("pbism", encoding="utf-8")

            # Set up extracted data files (mimicking TWBX extraction)
            extracted_dir = tmpdir / "tableau_metadata_extractor_agent" / "SalesWorkbook" / "extracted_data"
            (extracted_dir / "Data" / "Superstore").mkdir(parents=True, exist_ok=True)
            (extracted_dir / "Data" / "Superstore" / "Sales.xlsx").write_bytes(b"fake-excel")
            (extracted_dir / "Data" / "Superstore" / "Commission.csv").write_bytes(b"a,b\n1,2")

            output_dir = agent.assemble_pbip_project("SalesWorkbook")

            # Data files should be copied preserving archive internal structure
            self.assertTrue((output_dir / "Data" / "Superstore" / "Sales.xlsx").exists())
            self.assertTrue((output_dir / "Data" / "Superstore" / "Commission.csv").exists())
            self.assertEqual(
                (output_dir / "Data" / "Superstore" / "Sales.xlsx").read_bytes(),
                b"fake-excel",
            )

    def test_assemble_pbip_project_strips_ghost_tables_from_measures_tmdl(self):
        """measures.tmdl table sections for tables not in the model are removed."""
        with managed_tempdir() as tmpdir:
            settings = AgentSettings(project_endpoint="https://example.test", output_root=tmpdir)
            agent = PBIPProjectAssemblerAgent(settings=settings)

            # Skeleton
            skeleton_dir = tmpdir / "pbip_project_skeleton_agent" / "SalesWorkbook"
            (skeleton_dir / "SalesWorkbook.pbip").parent.mkdir(parents=True, exist_ok=True)
            (skeleton_dir / "SalesWorkbook.pbip").write_text("{}", encoding="utf-8")
            (skeleton_dir / "Report.Report").mkdir(parents=True, exist_ok=True)
            (skeleton_dir / "SalesWorkbook.SemanticModel").mkdir(parents=True, exist_ok=True)

            # Semantic model with two known tables: Orders, Returns
            gen_dir = tmpdir / "pbip_semantic_model_generator_agent" / "SalesWorkbook" / "SalesWorkbook.SemanticModel"
            tables_dir = gen_dir / "definition" / "tables"
            tables_dir.mkdir(parents=True, exist_ok=True)
            (gen_dir / "definition.pbism").write_text("pbism", encoding="utf-8")
            (tables_dir / "Orders.tmdl").write_text("table Orders\n", encoding="utf-8")
            (tables_dir / "Returns.tmdl").write_text("table Returns\n", encoding="utf-8")

            # measures.tmdl references a ghost table 'RawSource' that was split by the model agent
            measures_content = (
                "table Orders\n\n"
                "\tmeasure Sales = SUM(Orders[Amount])\n\n"
                "table 'RawSource'\n\n"
                "\tmeasure Days = DATEDIFF(MAX('RawSource'[Start]), MAX('RawSource'[End]), DAY)\n\n"
                "table Parameters\n\n"
                "\tmeasure Rate = 0.05\n"
            )
            dax_dir = tmpdir / "tmdl_measures_generator_agent" / "SalesWorkbook"
            dax_dir.mkdir(parents=True, exist_ok=True)
            (dax_dir / "measures.tmdl").write_text(measures_content, encoding="utf-8")

            agent.assemble_pbip_project("SalesWorkbook")

            result = (
                tmpdir
                / "pbip_project_assembler_agent"
                / "SalesWorkbook"
                / "SalesWorkbook.SemanticModel"
                / "definition"
                / "measures.tmdl"
            ).read_text(encoding="utf-8")

            # Ghost table 'RawSource' must be gone
            self.assertNotIn("RawSource", result)
            # Known table and Parameters must survive
            self.assertIn("table Orders", result)
            self.assertIn("table Parameters", result)

    def test_parse_tmdl_table_name_handles_quoted_and_unquoted(self):
        self.assertEqual(
            PBIPProjectAssemblerAgent._parse_tmdl_table_name("table 'Order Lines'\n"),
            "Order Lines",
        )
        self.assertEqual(
            PBIPProjectAssemblerAgent._parse_tmdl_table_name("table Orders\n"),
            "Orders",
        )
        self.assertEqual(
            PBIPProjectAssemblerAgent._parse_tmdl_table_name("table 'Vendite superiori all''obiettivo'\n"),
            "Vendite superiori all'obiettivo",
        )

    def test_strip_unknown_table_sections_removes_ghost_only(self):
        content = (
            "table Orders\n\n\tmeasure M1 = 1\n\n"
            "table 'Ghost Source'\n\n\tmeasure M2 = 2\n\n"
            "table Parameters\n\n\tmeasure Rate = 0.1\n"
        )
        result, stripped = PBIPProjectAssemblerAgent._strip_unknown_table_sections(content, {"Orders"})
        self.assertEqual(stripped, ["Ghost Source"])
        self.assertIn("table Orders", result)
        self.assertIn("table Parameters", result)
        self.assertNotIn("Ghost Source", result)

    def test_strip_unknown_table_sections_keeps_all_when_all_known(self):
        content = "table Orders\n\n\tmeasure M = 1\n\ntable Returns\n\n\tmeasure N = 2\n"
        result, stripped = PBIPProjectAssemblerAgent._strip_unknown_table_sections(content, {"Orders", "Returns"})
        self.assertEqual(stripped, [])
        self.assertEqual(result, content)

    def test_assemble_creates_stub_partition_for_measures_only_tables(self):
        """tables not in the model but kept in measures.tmdl get a stub partition file."""
        with managed_tempdir() as tmpdir:
            settings = AgentSettings(project_endpoint="https://example.test", output_root=tmpdir)
            agent = PBIPProjectAssemblerAgent(settings=settings)

            skeleton_dir = tmpdir / "pbip_project_skeleton_agent" / "SalesWorkbook"
            (skeleton_dir / "SalesWorkbook.pbip").parent.mkdir(parents=True, exist_ok=True)
            (skeleton_dir / "SalesWorkbook.pbip").write_text("{}", encoding="utf-8")
            (skeleton_dir / "Report.Report").mkdir(parents=True, exist_ok=True)
            (skeleton_dir / "SalesWorkbook.SemanticModel").mkdir(parents=True, exist_ok=True)

            gen_dir = tmpdir / "pbip_semantic_model_generator_agent" / "SalesWorkbook" / "SalesWorkbook.SemanticModel"
            tables_dir = gen_dir / "definition" / "tables"
            tables_dir.mkdir(parents=True, exist_ok=True)
            (gen_dir / "definition.pbism").write_text("pbism", encoding="utf-8")
            (tables_dir / "Orders.tmdl").write_text("table Orders\n", encoding="utf-8")
            # model.tmdl with a ref table for the existing table
            (gen_dir / "definition").mkdir(parents=True, exist_ok=True)
            (gen_dir / "definition" / "model.tmdl").write_text(
                "model Model\n\tculture: en-US\n\nref table Orders\n",
                encoding="utf-8",
            )

            # measures.tmdl references Parameters (not in model)
            measures_content = "table Orders\n\n\tmeasure M1 = 1\n\ntable Parameters\n\n\tmeasure Rate = 0.05\n"
            dax_dir = tmpdir / "tmdl_measures_generator_agent" / "SalesWorkbook"
            dax_dir.mkdir(parents=True, exist_ok=True)
            (dax_dir / "measures.tmdl").write_text(measures_content, encoding="utf-8")

            agent.assemble_pbip_project("SalesWorkbook")

            output_model_dir = tmpdir / "pbip_project_assembler_agent" / "SalesWorkbook" / "SalesWorkbook.SemanticModel"
            stub = output_model_dir / "definition" / "tables" / "Parameters.tmdl"
            self.assertTrue(stub.exists(), "Stub Parameters.tmdl should be created")
            stub_text = stub.read_text(encoding="utf-8")
            self.assertIn("partition", stub_text)
            self.assertIn("mode: import", stub_text)
            self.assertIn("__placeholder__", stub_text)

            model_text = (output_model_dir / "definition" / "model.tmdl").read_text(encoding="utf-8")
            self.assertIn("ref table 'Parameters'", model_text)

    def test_render_stub_table_tmdl_contains_required_fields(self):
        stub = PBIPProjectAssemblerAgent._render_stub_table_tmdl("Parameters")
        self.assertTrue(stub.startswith("table 'Parameters'"))
        self.assertIn("mode: import", stub)
        self.assertIn("__placeholder__", stub)

    def test_render_stub_table_tmdl_escapes_apostrophes(self):
        stub = PBIPProjectAssemblerAgent._render_stub_table_tmdl("It's a Table")
        self.assertIn("table 'It''s a Table'", stub)

    def test_assemble_pbip_project_works_without_extracted_data(self):
        with managed_tempdir() as tmpdir:
            settings = AgentSettings(
                project_endpoint="https://example.test",
                output_root=tmpdir,
            )
            agent = PBIPProjectAssemblerAgent(settings=settings)

            # Set up skeleton
            skeleton_dir = tmpdir / "pbip_project_skeleton_agent" / "SalesWorkbook"
            (skeleton_dir / "SalesWorkbook.pbip").parent.mkdir(parents=True, exist_ok=True)
            (skeleton_dir / "SalesWorkbook.pbip").write_text("{}", encoding="utf-8")
            (skeleton_dir / "Report.Report").mkdir(parents=True, exist_ok=True)
            (skeleton_dir / "SalesWorkbook.SemanticModel").mkdir(parents=True, exist_ok=True)

            # Set up generated semantic model (no extracted_data dir)
            generated_dir = (
                tmpdir / "pbip_semantic_model_generator_agent" / "SalesWorkbook" / "SalesWorkbook.SemanticModel"
            )
            generated_dir.mkdir(parents=True, exist_ok=True)
            (generated_dir / "definition.pbism").write_text("pbism", encoding="utf-8")

            # Should not raise — no extracted data is fine (e.g. .twb with SQL sources)
            output_dir = agent.assemble_pbip_project("SalesWorkbook")
            self.assertTrue((output_dir / "SalesWorkbook.pbip").exists())
