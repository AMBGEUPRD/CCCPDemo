"""Helper-function tests for the semantic model assembler."""

import unittest

from Tableau2PowerBI.agents.semantic_model.assembler import (
    SemanticModelAssembler,
    _fix_m_csv_quote_style,
    _fix_m_excel_navigation,
    _fix_m_file_paths,
    _fix_m_let_commas,
    _inject_column_types,
    _parameterize_file_paths,
    _quote,
)
from Tableau2PowerBI.agents.semantic_model.models import (
    ColumnDecision,
    SemanticModelDecisions,
    TableDecision,
)


def _minimal_decisions(**overrides) -> SemanticModelDecisions:
    """Build a minimal valid SemanticModelDecisions for testing."""
    defaults = {
        "tables": [
            TableDecision(
                name="TestTable",
                query_group="Fact",
                columns=[
                    ColumnDecision(
                        name="Col1",
                        source_column="Col1",
                        data_type="string",
                        summarize_by="none",
                    ),
                ],
                m_query='let\n    Source = Excel.Workbook(File.Contents("test.xlsx"), null, true)\nin\n    Source',
            ),
        ],
    }
    defaults.update(overrides)
    return SemanticModelDecisions(**defaults)


class TestQuoteHelper(unittest.TestCase):
    def test_simple_name(self):
        self.assertEqual(_quote("Table"), "'Table'")

    def test_name_with_spaces(self):
        self.assertEqual(_quote("Data ordine"), "'Data ordine'")

    def test_name_with_internal_quote(self):
        self.assertEqual(_quote("O'Brien"), "'O''Brien'")


class TestFixMLetCommas(unittest.TestCase):
    """Tests for _fix_m_let_commas."""

    def test_missing_comma_is_added(self):
        m = (
            "let\n"
            '    Source = Excel.Workbook(File.Contents("x.xls"), null, true)\n'
            '    Sheet1 = Source{[Item="Sheet1"]}[Data]\n'
            "in\n"
            "    Sheet1"
        )
        fixed = _fix_m_let_commas(m)
        self.assertIn("true),", fixed)

    def test_already_correct_unchanged(self):
        m = (
            "let\n"
            '    Source = Csv.Document(File.Contents("x.csv"), [Delimiter=","]),\n'
            "    Promoted = Table.PromoteHeaders(Source)\n"
            "in\n"
            "    Promoted"
        )
        self.assertEqual(_fix_m_let_commas(m), m)

    def test_single_step_no_comma_needed(self):
        m = 'let\n    Source = Csv.Document(File.Contents("x.csv"))\nin\n    Source'
        self.assertEqual(_fix_m_let_commas(m), m)

    def test_three_steps_two_missing(self):
        m = "let\n    A = 1\n    B = 2\n    C = 3\nin\n    C"
        fixed = _fix_m_let_commas(m)
        lines = fixed.split("\n")
        self.assertTrue(lines[1].endswith(","))
        self.assertTrue(lines[2].endswith(","))
        self.assertFalse(lines[3].endswith(","))

    def test_empty_string(self):
        self.assertEqual(_fix_m_let_commas(""), "")

    def test_no_let_in_block(self):
        self.assertEqual(_fix_m_let_commas("Source"), "Source")


class TestFixMExcelNavigation(unittest.TestCase):
    """Tests for _fix_m_excel_navigation."""

    def test_item_kind_rewritten_to_name(self):
        m = 'Source{[Item="Persone",Kind="Sheet"]}[Data]'
        self.assertEqual(_fix_m_excel_navigation(m), 'Source{[Name="Persone"]}[Data]')

    def test_already_name_based_unchanged(self):
        m = 'Source{[Name="Persone"]}[Data]'
        self.assertEqual(_fix_m_excel_navigation(m), m)

    def test_full_let_block(self):
        m = (
            "let\n"
            '    Source = Excel.Workbook(File.Contents("test.xls"), null, true),\n'
            '    Ordini = Source{[Item="Ordini",Kind="Sheet"]}[Data]\n'
            "in\n"
            "    Ordini"
        )
        fixed = _fix_m_excel_navigation(m)
        self.assertIn('{[Name="Ordini"]}', fixed)
        self.assertNotIn("Item=", fixed)

    def test_multiple_sheets_in_separate_queries(self):
        m1 = 'Source{[Item="Sheet1",Kind="Sheet"]}[Data]'
        m2 = 'Source{[Item="Sheet2",Kind="Sheet"]}[Data]'
        self.assertEqual(_fix_m_excel_navigation(m1), 'Source{[Name="Sheet1"]}[Data]')
        self.assertEqual(_fix_m_excel_navigation(m2), 'Source{[Name="Sheet2"]}[Data]')

    def test_no_excel_navigation_unchanged(self):
        m = 'Csv.Document(File.Contents("data.csv"), [Delimiter=","])'
        self.assertEqual(_fix_m_excel_navigation(m), m)

    def test_sql_navigation_unchanged(self):
        m = 'Source{[Schema="dbo",Item="Sales"]}[Data]'
        self.assertEqual(_fix_m_excel_navigation(m), m)


class TestFixMFilePaths(unittest.TestCase):
    """Tests for _fix_m_file_paths."""

    def test_forward_slashes_converted_to_backslashes(self):
        m = 'File.Contents("C:/Users/data/file.xlsx")'
        self.assertEqual(_fix_m_file_paths(m), 'File.Contents("C:\\Users\\data\\file.xlsx")')

    def test_already_backslashes_unchanged(self):
        m = 'File.Contents("C:\\Users\\data\\file.xlsx")'
        self.assertEqual(_fix_m_file_paths(m), m)

    def test_mixed_slashes_normalised(self):
        m = 'File.Contents("C:\\Users/data/Superstore\\file.xls")'
        self.assertEqual(_fix_m_file_paths(m), 'File.Contents("C:\\Users\\data\\Superstore\\file.xls")')

    def test_full_let_block(self):
        m = (
            "let\n"
            '    Source = Excel.Workbook(File.Contents("C:/output/Data/Sales.xlsx"), null, true),\n'
            '    Sheet1 = Source{[Name="Sheet1"]}[Data]\n'
            "in\n"
            "    Sheet1"
        )
        fixed = _fix_m_file_paths(m)
        self.assertIn("C:\\output\\Data\\Sales.xlsx", fixed)
        self.assertNotIn("C:/output", fixed)

    def test_no_file_contents_unchanged(self):
        m = 'Sql.Database("myserver", "mydb")'
        self.assertEqual(_fix_m_file_paths(m), m)

    def test_csv_path_normalised(self):
        m = 'Csv.Document(File.Contents("Data/Sales Commission.csv"), [Delimiter=","])'
        self.assertEqual(
            _fix_m_file_paths(m),
            'Csv.Document(File.Contents("Data\\Sales Commission.csv"), [Delimiter=","])',
        )


class TestParameterizeFilePaths(unittest.TestCase):
    """Tests for _parameterize_file_paths."""

    def test_relative_path_gets_parameterized(self):
        m = 'File.Contents("Data\\Superstore\\Sales Target.xlsx")'
        result = _parameterize_file_paths(m)
        self.assertEqual(result, 'File.Contents(DataFolderPath & "\\Data\\Superstore\\Sales Target.xlsx")')

    def test_absolute_path_gets_parameterized(self):
        m = 'File.Contents("C:\\Users\\data\\file.xlsx")'
        self.assertEqual(_parameterize_file_paths(m), m)

    def test_csv_file_contents_parameterized(self):
        m = 'Csv.Document(File.Contents("Data\\Sales Commission.csv"), [Delimiter=","])'
        result = _parameterize_file_paths(m)
        self.assertEqual(
            result,
            'Csv.Document(File.Contents(DataFolderPath & "\\Data\\Sales Commission.csv"), [Delimiter=","])',
        )

    def test_no_file_contents_unchanged(self):
        m = 'Sql.Database("myserver", "mydb")'
        self.assertEqual(_parameterize_file_paths(m), m)

    def test_full_let_block_parameterized(self):
        m = (
            "let\n"
            '    Source = Excel.Workbook(File.Contents("Data\\Sales.xlsx"), null, true),\n'
            '    Sheet1 = Source{[Name="Sheet1"]}[Data]\n'
            "in\n"
            "    Sheet1"
        )
        result = _parameterize_file_paths(m)
        self.assertIn('File.Contents(DataFolderPath & "\\Data\\Sales.xlsx")', result)
        self.assertNotIn('File.Contents("Data', result)

    def test_multiple_file_contents_all_parameterized(self):
        m = 'File.Contents("Data\\file1.xlsx")\n' 'File.Contents("Data\\file2.csv")'
        result = _parameterize_file_paths(m)
        self.assertIn('DataFolderPath & "\\Data\\file1.xlsx"', result)
        self.assertIn('DataFolderPath & "\\Data\\file2.csv"', result)

    def test_path_already_starting_with_backslash_no_double(self):
        m = 'File.Contents("\\\\server\\share\\file.xlsx")'
        self.assertEqual(_parameterize_file_paths(m), m)


class TestFixMCsvQuoteStyle(unittest.TestCase):
    """Tests for _fix_m_csv_quote_style."""

    def test_replaces_quote_style_none(self):
        m = 'Csv.Document(File.Contents("data.csv"), [Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.None])'
        result = _fix_m_csv_quote_style(m)
        self.assertIn("QuoteStyle.Csv", result)
        self.assertNotIn("QuoteStyle.None", result)

    def test_leaves_quote_style_csv_unchanged(self):
        m = 'Csv.Document(File.Contents("data.csv"), [Delimiter=",", QuoteStyle=QuoteStyle.Csv])'
        self.assertEqual(m, _fix_m_csv_quote_style(m))

    def test_no_op_on_excel_query(self):
        m = 'Excel.Workbook(File.Contents("data.xlsx"), true, true)'
        self.assertEqual(m, _fix_m_csv_quote_style(m))

    def test_full_csv_let_block(self):
        m = (
            "let\n"
            '    Source = Csv.Document(File.Contents("Sales Commission.csv"), '
            '[Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.None]),\n'
            "    PromotedHeaders = Table.PromoteHeaders(Source, [PromoteAllScalars=true])\n"
            "in\n"
            "    PromotedHeaders"
        )
        result = _fix_m_csv_quote_style(m)
        self.assertIn("QuoteStyle.Csv", result)
        self.assertNotIn("QuoteStyle.None", result)
        self.assertIn("Csv.Document", result)
        self.assertIn("PromotedHeaders", result)


class TestSafeHeaderHandling(unittest.TestCase):
    """Regression tests for header-related assembler rewrites."""

    def test_assembler_preserves_excel_null_header_argument(self):
        decisions = _minimal_decisions(
            tables=[
                TableDecision(
                    name="ExcelTable",
                    query_group="Fact",
                    columns=[ColumnDecision(name="C", source_column="C", data_type="string")],
                    m_query=(
                        'let\n    Source = Excel.Workbook(File.Contents("data.xlsx"), null, true),'
                        '\n    Sheet1 = Source{[Name="Sheet1"]}[Data]\nin\n    Sheet1'
                    ),
                ),
            ]
        )
        files = self._assemble_from_decisions(decisions)
        table_tmdl = files["Book.SemanticModel/definition/tables/ExcelTable.tmdl"]
        self.assertIn("null, true)", table_tmdl)

    def test_assembler_does_not_inject_csv_header_promotion(self):
        decisions = _minimal_decisions(
            tables=[
                TableDecision(
                    name="CsvTable",
                    query_group="Fact",
                    columns=[ColumnDecision(name="Col1", source_column="Col1", data_type="string")],
                    m_query=(
                        'let\n    Source = Csv.Document(File.Contents("Data/file.csv"),'
                        ' [Delimiter=","])\nin\n    Source'
                    ),
                ),
            ]
        )
        files = self._assemble_from_decisions(decisions)
        table_tmdl = files["Book.SemanticModel/definition/tables/CsvTable.tmdl"]
        self.assertNotIn("Table.PromoteHeaders", table_tmdl)

    @staticmethod
    def _assemble_from_decisions(decisions):
        assembler = SemanticModelAssembler(decisions, "Book")
        return assembler.assemble()


class TestInjectColumnTypes(unittest.TestCase):
    """Tests for _inject_column_types."""

    def _cols(self, *specs):
        return [ColumnDecision(name=name, source_column=name, data_type=data_type) for name, data_type in specs]

    def test_excel_query_gets_type_step(self):
        m = (
            'let\n    Source = Excel.Workbook(File.Contents("t.xlsx"), true, true),'
            '\n    Data = Source{[Name="Sheet1"]}[Data]\nin\n    Data'
        )
        cols = self._cols(("Name", "string"), ("Amount", "double"), ("Date", "dateTime"))
        result = _inject_column_types(m, cols)
        self.assertIn("Table.TransformColumnTypes", result)
        self.assertIn("ChangedType", result)
        self.assertIn('"Name", type text', result)
        self.assertIn('"Amount", type number', result)
        self.assertIn('"Date", type datetime', result)

    def test_csv_query_gets_type_step(self):
        m = (
            'let\n    Source = Csv.Document(File.Contents("t.csv"), [Delimiter=","]),'
            "\n    Promoted = Table.PromoteHeaders(Source)\nin\n    Promoted"
        )
        cols = self._cols(("ID", "int64"), ("Flag", "boolean"))
        result = _inject_column_types(m, cols)
        self.assertIn("Table.TransformColumnTypes", result)
        self.assertIn("Int64.Type", result)
        self.assertIn("type logical", result)

    def test_culture_parameter_is_en_us(self):
        m = (
            'let\n    Source = Csv.Document(File.Contents("t.csv"), [Delimiter=","]),'
            "\n    Promoted = Table.PromoteHeaders(Source)\nin\n    Promoted"
        )
        cols = self._cols(("Amount", "int64"))
        result = _inject_column_types(m, cols)
        self.assertIn('"en-US"', result)

    def test_already_has_transform_unchanged(self):
        m = (
            'let\n    Source = Excel.Workbook(File.Contents("t.xlsx"), true, true),'
            '\n    ChangedType = Table.TransformColumnTypes(Source, {{"Col", type text}})'
            "\nin\n    ChangedType"
        )
        cols = self._cols(("Col", "string"))
        self.assertEqual(_inject_column_types(m, cols), m)

    def test_sql_query_gets_type_step(self):
        m = (
            'let\n    Source = Sql.Database("srv", "db"),'
            '\n    Data = Source{[Schema="dbo", Item="Orders"]}[Data]\nin\n    Data'
        )
        cols = self._cols(("Total", "double"))
        result = _inject_column_types(m, cols)
        self.assertIn("Table.TransformColumnTypes", result)

    def test_empty_columns_unchanged(self):
        m = 'let\n    Source = Excel.Workbook(File.Contents("t.xlsx"), true, true)\nin\n    Source'
        self.assertEqual(_inject_column_types(m, []), m)

    def test_no_let_in_block_unchanged(self):
        m = 'Excel.Workbook(File.Contents("t.xlsx"), true, true)'
        cols = self._cols(("Col", "string"))
        self.assertEqual(_inject_column_types(m, cols), m)

    def test_in_reference_updated_to_changed_type(self):
        m = (
            'let\n    Source = Excel.Workbook(File.Contents("t.xlsx"), true, true),'
            '\n    Data = Source{[Name="S1"]}[Data]\nin\n    Data'
        )
        cols = self._cols(("X", "string"))
        result = _inject_column_types(m, cols)
        found_in = False
        for line in result.split("\n"):
            if found_in and line.strip():
                self.assertEqual(line.strip(), "ChangedType")
                break
            if line.strip().startswith("in"):
                found_in = True

    def test_assembler_applies_column_types(self):
        decisions = _minimal_decisions(
            tables=[
                TableDecision(
                    name="Typed",
                    query_group="Fact",
                    columns=[
                        ColumnDecision(name="Name", source_column="Name", data_type="string"),
                        ColumnDecision(name="Count", source_column="Count", data_type="int64", summarize_by="sum"),
                        ColumnDecision(name="Date", source_column="Date", data_type="dateTime"),
                    ],
                    m_query=(
                        'let\n    Source = Excel.Workbook(File.Contents("data.xlsx"), true, true),'
                        '\n    Data = Source{[Name="Sheet1"]}[Data]\nin\n    Data'
                    ),
                ),
            ],
        )
        assembler = SemanticModelAssembler(decisions, "Book")
        files = assembler.assemble()
        table = files["Book.SemanticModel/definition/tables/Typed.tmdl"]
        self.assertIn("Table.TransformColumnTypes", table)
        self.assertIn('"Name", type text', table)
        self.assertIn('"Count", Int64.Type', table)
        self.assertIn('"Date", type datetime', table)

    def test_assembler_fixes_csv_quote_style(self):
        decisions = _minimal_decisions(
            tables=[
                TableDecision(
                    name="CsvTable",
                    query_group="Fact",
                    columns=[
                        ColumnDecision(name="Region", source_column="Region", data_type="string"),
                        ColumnDecision(name="Sales", source_column="Sales", data_type="int64", summarize_by="sum"),
                    ],
                    m_query=(
                        "let\n"
                        '    Source = Csv.Document(File.Contents("Data\\Sales.csv"), '
                        '[Delimiter=",", Encoding=65001, QuoteStyle=QuoteStyle.None]),\n'
                        "    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars=true])\n"
                        "in\n"
                        "    Promoted"
                    ),
                ),
            ],
        )
        assembler = SemanticModelAssembler(decisions, "Book")
        files = assembler.assemble()
        table = files["Book.SemanticModel/definition/tables/CsvTable.tmdl"]
        self.assertIn("QuoteStyle.Csv", table)
        self.assertNotIn("QuoteStyle.None", table)
