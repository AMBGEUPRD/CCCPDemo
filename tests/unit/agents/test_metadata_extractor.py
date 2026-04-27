import json
import unittest
from pathlib import Path
from zipfile import ZipFile

from Tableau2PowerBI.agents.metadata_extractor.metadata_extractor import (
    _parse_field_ref,
    _parse_shelf,
    extract_data_files_from_twbx,
    extract_workbook_metadata,
    read_twb_file,
    resolve_connection_paths,
)
from tests.support import managed_tempdir


class MetadataExtractorTests(unittest.TestCase):
    def test_extract_workbook_metadata_keeps_dashboard_sheet_order_deterministic(self):
        workbook_xml = """\
<workbook>
  <datasources />
  <worksheets />
  <dashboards>
    <dashboard name="Main">
      <zone name="Sheet B" type="worksheet" x="1" y="2" w="3" h="4" />
      <zone name="Sheet A" type="worksheet" x="5" y="6" w="7" h="8" />
      <zone name="Sheet B" type="worksheet" x="9" y="10" w="11" h="12" />
    </dashboard>
  </dashboards>
</workbook>
"""
        with managed_tempdir() as tmpdir:
            workbook_path = tmpdir / "sample.twb"
            workbook_path.write_text(workbook_xml, encoding="utf-8")

            metadata = extract_workbook_metadata(str(workbook_path))

        self.assertEqual(metadata["dashboards"][0]["sheets"], ["Sheet B", "Sheet A"])

    def test_read_twb_file_wraps_invalid_xml_in_value_error(self):
        with managed_tempdir() as tmpdir:
            workbook_path = tmpdir / "broken.twb"
            workbook_path.write_text("<workbook><broken>", encoding="utf-8")

            with self.assertRaises(ValueError):
                read_twb_file(str(workbook_path))

    def test_read_twb_file_preserves_top_level_schema(self):
        workbook_xml = """\
<workbook>
  <datasources>
    <datasource name="Data" caption="Data">
      <column name="[Sales]" datatype="real" role="measure" type="quantitative" />
    </datasource>
    <datasource name="Parameters">
      <column name="[Param]" datatype="string" role="dimension" type="nominal" param-domain-type="list">
        <calculation formula="'Default'" />
        <members>
          <member value="A" />
          <member value="B" />
        </members>
      </column>
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name="Sheet 1">
      <table>
        <view>
          <cols>[Sales]</cols>
          <rows />
          <mark class="bar" />
          <encoding type="color" field="[Sales]" />
          <filter class="categorical" column="[Sales]">
            <member value="A" ui-enumeration="inclusive" />
          </filter>
          <title><formatted-text><run>Title</run></formatted-text></title>
        </view>
      </table>
    </worksheet>
  </worksheets>
  <dashboards>
    <dashboard name="Dashboard 1">
      <size width="100" height="200" />
      <zone name="Sheet 1" type="worksheet" x="1" y="2" w="3" h="4" />
    </dashboard>
  </dashboards>
  <actions>
    <action name="Action 1" type="filter" source-sheet="Sheet 1" target-sheet="Sheet 1" fields="[Sales]" />
  </actions>
</workbook>
"""
        with managed_tempdir() as tmpdir:
            workbook_path = tmpdir / "sample.twb"
            workbook_path.write_text(workbook_xml, encoding="utf-8")

            payload = json.loads(read_twb_file(str(workbook_path)))

        self.assertEqual(
            list(payload.keys()),
            ["datasources", "worksheets", "dashboards", "actions", "parameters"],
        )
        self.assertEqual(payload["datasources"][0]["name"], "Data")
        self.assertEqual(payload["parameters"][0]["default_value"], "'Default'")
        self.assertEqual(payload["worksheets"][0]["mark_type"], "bar")
        self.assertEqual(payload["dashboards"][0]["sheets"], ["Sheet 1"])
        self.assertEqual(payload["actions"][0]["name"], "Action 1")

    def test_csv_datasource_has_first_row_header(self):
        """CSV sources with header='yes' should have first_row_header=True."""
        workbook_xml = """\
<workbook>
  <datasources>
    <datasource name="CSV Source" caption="CSV Source">
      <connection class='federated'>
        <named-connections>
          <named-connection caption='data.csv' name='textscan.abc123'>
            <connection class='textscan' directory='C:/data' filename='data.csv' />
          </named-connection>
        </named-connections>
        <relation connection='textscan.abc123' name='data.csv' table='[data#csv]' type='table'>
          <columns character-set='UTF-8' header='yes' locale='en_US' separator=','>
            <column datatype='string' name='Name' ordinal='0' />
            <column datatype='integer' name='Value' ordinal='1' />
          </columns>
        </relation>
      </connection>
    </datasource>
  </datasources>
  <worksheets />
  <dashboards />
</workbook>
"""
        with managed_tempdir() as tmpdir:
            workbook_path = tmpdir / "csv_test.twb"
            workbook_path.write_text(workbook_xml, encoding="utf-8")
            metadata = extract_workbook_metadata(str(workbook_path))

        conn = metadata["datasources"][0]["connection"]
        self.assertTrue(conn.get("first_row_header"), "CSV with header='yes' should set first_row_header")

    def test_excel_datasource_no_header_attribute(self):
        """Excel sources typically don't have the header attribute on <columns>."""
        workbook_xml = """\
<workbook>
  <datasources>
    <datasource name="Excel Source" caption="Excel Source">
      <connection class='federated'>
        <named-connections>
          <named-connection caption='test.xlsx' name='excel-direct.abc123'>
            <connection class='excel-direct' filename='test.xlsx' />
          </named-connection>
        </named-connections>
        <relation connection='excel-direct.abc123' name='Sheet1' table='[Sheet1$]' type='table'>
          <columns>
            <column datatype='string' name='Name' ordinal='0' />
          </columns>
        </relation>
      </connection>
    </datasource>
  </datasources>
  <worksheets />
  <dashboards />
</workbook>
"""
        with managed_tempdir() as tmpdir:
            workbook_path = tmpdir / "excel_test.twb"
            workbook_path.write_text(workbook_xml, encoding="utf-8")
            metadata = extract_workbook_metadata(str(workbook_path))

        conn = metadata["datasources"][0]["connection"]
        self.assertNotIn("first_row_header", conn, "Excel without header='yes' should not set first_row_header")


class TestExtractDataFilesFromTwbx(unittest.TestCase):
    """Tests for extract_data_files_from_twbx."""

    def _make_twbx(self, tmpdir: Path, files: dict[str, bytes]) -> Path:
        """Create a .twbx (zip) with given internal files."""
        twbx_path = tmpdir / "test.twbx"
        with ZipFile(twbx_path, "w") as z:
            z.writestr("test.twb", "<workbook/>")
            for name, content in files.items():
                z.writestr(name, content)
        return twbx_path

    def test_extracts_data_files_and_skips_twb(self):
        with managed_tempdir() as tmpdir:
            twbx = self._make_twbx(
                tmpdir,
                {
                    "Data/Sales.xlsx": b"fake-excel-content",
                    "commission.csv": b"a,b,c\n1,2,3",
                },
            )
            output_dir = tmpdir / "extracted"
            mapping = extract_data_files_from_twbx(twbx, output_dir)

            self.assertEqual(len(mapping), 2)
            self.assertIn("Data/Sales.xlsx", mapping)
            self.assertIn("commission.csv", mapping)
            # TWB should NOT be extracted
            self.assertNotIn("test.twb", mapping)
            # Files should exist on disk
            self.assertTrue(mapping["Data/Sales.xlsx"].exists())
            self.assertTrue(mapping["commission.csv"].exists())
            # Content should match
            self.assertEqual(mapping["Data/Sales.xlsx"].read_bytes(), b"fake-excel-content")

    def test_returns_empty_for_twb(self):
        with managed_tempdir() as tmpdir:
            twb_path = tmpdir / "test.twb"
            twb_path.write_text("<workbook/>", encoding="utf-8")
            mapping = extract_data_files_from_twbx(twb_path, tmpdir / "out")
            self.assertEqual(mapping, {})

    def test_preserves_subdirectory_structure(self):
        with managed_tempdir() as tmpdir:
            twbx = self._make_twbx(
                tmpdir,
                {
                    "Data/Superstore/file.xls": b"xls-content",
                },
            )
            output_dir = tmpdir / "extracted"
            mapping = extract_data_files_from_twbx(twbx, output_dir)

            self.assertIn("Data/Superstore/file.xls", mapping)
            extracted_path = mapping["Data/Superstore/file.xls"]
            self.assertTrue(extracted_path.exists())
            self.assertEqual(extracted_path.read_bytes(), b"xls-content")

    def test_rejects_archive_path_traversal(self):
        with managed_tempdir() as tmpdir:
            twbx = self._make_twbx(
                tmpdir,
                {
                    "../escape.csv": b"bad",
                },
            )

            with self.assertRaises(ValueError):
                extract_data_files_from_twbx(twbx, tmpdir / "extracted")


class TestResolveConnectionPaths(unittest.TestCase):
    """Tests for resolve_connection_paths."""

    def test_adds_resolved_filename_and_relative_path(self):
        metadata = {
            "datasources": [
                {
                    "name": "Sales",
                    "connection": {
                        "type": "excel-direct",
                        "filename": "Data/Sales.xlsx",
                    },
                }
            ]
        }
        file_mapping = {"Data/Sales.xlsx": Path("C:/output/extracted/Data/Sales.xlsx")}
        result = resolve_connection_paths(metadata, file_mapping)

        conn = result["datasources"][0]["connection"]
        self.assertEqual(conn["resolved_filename"], "C:\\output\\extracted\\Data\\Sales.xlsx")
        self.assertEqual(conn["relative_path"], "Data/Sales.xlsx")

    def test_normalised_match_with_mixed_slashes(self):
        metadata = {
            "datasources": [
                {
                    "name": "Sales",
                    "connection": {
                        "type": "excel-direct",
                        "filename": "Data\\Sales.xlsx",
                    },
                }
            ]
        }
        file_mapping = {"Data/Sales.xlsx": Path("C:/output/Data/Sales.xlsx")}
        result = resolve_connection_paths(metadata, file_mapping)

        conn = result["datasources"][0]["connection"]
        self.assertIn("resolved_filename", conn)
        # relative_path uses the archive key (forward slashes)
        self.assertEqual(conn["relative_path"], "Data/Sales.xlsx")

    def test_basename_fallback_matches_when_path_prefix_differs(self):
        """Tableau may store just 'file.csv' but the archive has 'Data/Subdir/file.csv'."""
        metadata = {
            "datasources": [
                {
                    "name": "Commission",
                    "connection": {
                        "type": "textscan",
                        "filename": "Sales Commission.csv",
                    },
                }
            ]
        }
        file_mapping = {
            "Data/Superstore/Sales Commission.csv": Path("C:/out/Data/Superstore/Sales Commission.csv"),
        }
        result = resolve_connection_paths(metadata, file_mapping)

        conn = result["datasources"][0]["connection"]
        self.assertIn("resolved_filename", conn)
        # relative_path should be the archive path, not the Tableau filename
        self.assertEqual(conn["relative_path"], "Data/Superstore/Sales Commission.csv")

    def test_no_match_leaves_connection_unchanged(self):
        metadata = {
            "datasources": [
                {
                    "name": "Sales",
                    "connection": {
                        "type": "sqlserver",
                        "server": "myserver",
                    },
                }
            ]
        }
        result = resolve_connection_paths(metadata, {})
        conn = result["datasources"][0]["connection"]
        self.assertNotIn("resolved_filename", conn)
        self.assertNotIn("relative_path", conn)

    def test_empty_file_mapping_returns_metadata_unchanged(self):
        metadata = {
            "datasources": [
                {
                    "name": "Sales",
                    "connection": {"type": "excel-direct", "filename": "test.xlsx"},
                }
            ]
        }
        result = resolve_connection_paths(metadata, {})
        self.assertNotIn("resolved_filename", result["datasources"][0]["connection"])
        self.assertNotIn("relative_path", result["datasources"][0]["connection"])

    def test_multiple_datasources_resolved_independently(self):
        metadata = {
            "datasources": [
                {
                    "name": "Excel DS",
                    "connection": {"type": "excel-direct", "filename": "Data/file.xlsx"},
                },
                {
                    "name": "CSV DS",
                    "connection": {"type": "textscan", "filename": "data.csv"},
                },
                {
                    "name": "SQL DS",
                    "connection": {"type": "sqlserver", "server": "myserver"},
                },
            ]
        }
        file_mapping = {
            "Data/file.xlsx": Path("C:/out/Data/file.xlsx"),
            "data.csv": Path("C:/out/data.csv"),
        }
        result = resolve_connection_paths(metadata, file_mapping)

        self.assertIn("relative_path", result["datasources"][0]["connection"])
        self.assertIn("relative_path", result["datasources"][1]["connection"])
        self.assertNotIn("relative_path", result["datasources"][2]["connection"])

    def test_ambiguous_basename_fallback_raises(self):
        metadata = {
            "datasources": [
                {
                    "name": "Sales",
                    "connection": {
                        "type": "textscan",
                        "filename": "sales.csv",
                    },
                }
            ]
        }
        file_mapping = {
            "Data/A/sales.csv": Path("C:/out/Data/A/sales.csv"),
            "Data/B/sales.csv": Path("C:/out/Data/B/sales.csv"),
        }

        with self.assertRaises(ValueError):
            resolve_connection_paths(metadata, file_mapping)


class ParseShelfTests(unittest.TestCase):
    """Tests for _parse_shelf — the cols/rows shelf expression parser."""

    def _fields(self, shelf_text: str) -> list[str | None]:
        """Return the 'field' values from a parsed shelf."""
        return [entry.get("field") for entry in _parse_shelf(shelf_text)]

    def test_single_field(self):
        result = _parse_shelf("[ds].[none:Vendite:qk]")
        self.assertEqual(result[0]["field"], "Vendite")

    def test_two_fields_star_separator(self):
        # Tableau wraps multi-field shelves in parens: "([f1] * [f2])"
        shelf = "([ds].[none:Segmento:nk] * [ds].[sum:Vendite:qk])"
        fields = self._fields(shelf)
        self.assertEqual(fields, ["Segmento", "Vendite"])

    def test_two_fields_slash_separator(self):
        shelf = "([ds].[none:Categoria:nk] / [ds].[none:Sottocategoria:nk])"
        fields = self._fields(shelf)
        self.assertEqual(fields, ["Categoria", "Sottocategoria"])

    def test_no_trailing_none_from_parens(self):
        # Regression: stray ')' must not produce an entry with field=None,
        # which caused a trailing comma in the UI ("Segmento,").
        shelf = "([ds].[none:Segmento:nk] * [ds].[sum:Vendite:qk])"
        fields = self._fields(shelf)
        self.assertNotIn(None, fields)
        self.assertEqual(len(fields), 2)

    def test_empty_string_returns_empty_list(self):
        self.assertEqual(_parse_shelf(""), [])


class ParseFieldRefTests(unittest.TestCase):
    """Tests for _parse_field_ref — covers virtual fields, fval expressions, and plain refs."""

    def test_standard_field_with_agg_and_type(self):
        result = _parse_field_ref("[ds].[none:Vendite:qk]")
        self.assertEqual(result["field"], "Vendite")
        self.assertEqual(result["aggregation"], "none")
        self.assertEqual(result["type_code"], "qk")

    def test_virtual_field_colon_stripped(self):
        # ':Measure Names' is a Tableau built-in virtual pill — leading ':' must be removed.
        result = _parse_field_ref("[ds].[:Measure Names]")
        self.assertEqual(result["field"], "Measure Names")

    def test_virtual_measure_values_colon_stripped(self):
        result = _parse_field_ref("[ds].[:Measure Values]")
        self.assertEqual(result["field"], "Measure Values")

    def test_fval_expression_field_extracted(self):
        # Real fval shelf refs use 'fVal:inner_agg:FieldName:typecode' format,
        # e.g. [ds].[fVal:sum:Vendite:qk].  The inner field name must be extracted.
        result = _parse_field_ref("[ds].[fVal:sum:Vendite:qk]")
        self.assertEqual(result["aggregation"], "fVal")
        self.assertEqual(result["field"], "Vendite")

    def test_simple_field_no_datasource(self):
        result = _parse_field_ref("[Customer Name]")
        self.assertEqual(result["field"], "Customer Name")

    def test_empty_ref_returns_raw_only(self):
        result = _parse_field_ref("")
        self.assertNotIn("field", result)


class CalcIndexResolutionTests(unittest.TestCase):
    """End-to-end: Calculation_XXXXXXXXX names in shelf refs resolve to captions."""

    def _make_workbook_xml(self, calc_name: str, caption: str) -> str:
        return f"""\
<workbook>
  <datasources>
    <datasource name="ds1" caption="My DS">
      <column name="[{calc_name}]" caption="{caption}" datatype="integer" role="measure" type="quantitative">
        <calculation class="tableau" formula="1+1" />
      </column>
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name="Sheet 1">
      <table>
        <view>
          <cols>[ds1].[sum:{calc_name}:qk]</cols>
          <rows>[ds1].[none:Region:nk]</rows>
        </view>
      </table>
    </worksheet>
  </worksheets>
  <dashboards />
</workbook>"""

    def test_calculation_name_resolved_to_caption_in_shelf(self):
        xml = self._make_workbook_xml("Calculation_9921103144103743", "Profit Ratio")
        with managed_tempdir() as tmpdir:
            path = tmpdir / "sample.twb"
            path.write_text(xml, encoding="utf-8")
            result = extract_workbook_metadata(str(path))
        ws = result["worksheets"][0]
        shelf_fields = [ref.get("field") for ref in ws["cols_shelf"]]
        self.assertIn("Profit Ratio", shelf_fields)
        self.assertNotIn("Calculation_9921103144103743", shelf_fields)

    def test_calc_without_caption_left_as_raw_name(self):
        # If a calculated field has no caption, the raw name stays rather than
        # replacing with an empty string.
        xml = """\
<workbook>
  <datasources>
    <datasource name="ds1">
      <column name="[Calculation_111]" datatype="integer" role="measure" type="quantitative">
        <calculation class="tableau" formula="1" />
      </column>
    </datasource>
  </datasources>
  <worksheets>
    <worksheet name="Sheet 1">
      <table><view>
        <cols>[ds1].[sum:Calculation_111:qk]</cols>
        <rows></rows>
      </view></table>
    </worksheet>
  </worksheets>
  <dashboards />
</workbook>"""
        with managed_tempdir() as tmpdir:
            path = tmpdir / "sample.twb"
            path.write_text(xml, encoding="utf-8")
            result = extract_workbook_metadata(str(path))
        ws = result["worksheets"][0]
        shelf_fields = [ref.get("field") for ref in ws["cols_shelf"]]
        self.assertIn("Calculation_111", shelf_fields)


class MeasureValuesFilterTests(unittest.TestCase):
    """Measure Names / Measure Values virtual fields are filtered from shelves."""

    def _make_workbook_xml(self, cols: str, rows: str) -> str:
        return f"""\
<workbook>
  <datasources>
    <datasource name="ds1" caption="Orders" />
  </datasources>
  <worksheets>
    <worksheet name="Sheet 1">
      <table><view>
        <cols>{cols}</cols>
        <rows>{rows}</rows>
      </view></table>
    </worksheet>
  </worksheets>
  <dashboards />
</workbook>"""

    def test_measure_names_filtered_from_cols_shelf(self):
        xml = self._make_workbook_xml(
            cols="([ds1].[:Measure Names] * [ds1].[none:Categoria:nk])",
            rows="[ds1].[none:Segmento:nk]",
        )
        with managed_tempdir() as tmpdir:
            path = tmpdir / "sample.twb"
            path.write_text(xml, encoding="utf-8")
            result = extract_workbook_metadata(str(path))

        ws = result["worksheets"][0]
        shelf_fields = [ref.get("field") for ref in ws["cols_shelf"]]
        self.assertNotIn("Measure Names", shelf_fields)
        self.assertIn("Categoria", shelf_fields)

    def test_uses_measure_values_flag_set_when_virtual_field_present(self):
        xml = self._make_workbook_xml(
            cols="[ds1].[:Measure Names]",
            rows="[ds1].[none:Segmento:nk]",
        )
        with managed_tempdir() as tmpdir:
            path = tmpdir / "sample.twb"
            path.write_text(xml, encoding="utf-8")
            result = extract_workbook_metadata(str(path))

        ws = result["worksheets"][0]
        self.assertTrue(ws["uses_measure_values"])

    def test_uses_measure_values_false_when_no_virtual_fields(self):
        xml = self._make_workbook_xml(
            cols="[ds1].[none:Categoria:nk]",
            rows="[ds1].[none:Segmento:nk]",
        )
        with managed_tempdir() as tmpdir:
            path = tmpdir / "sample.twb"
            path.write_text(xml, encoding="utf-8")
            result = extract_workbook_metadata(str(path))

        ws = result["worksheets"][0]
        self.assertFalse(ws["uses_measure_values"])

    def test_datasource_hash_name_resolved_to_caption_in_shelf(self):
        """Hash datasource names appearing as shelf field refs resolve to caption."""
        xml = """\
<workbook>
  <datasources>
    <datasource name="Ordini_6D2EF74F348B46BDA976A7AEEA6FB5C9" caption="Ordini" />
  </datasources>
  <worksheets>
    <worksheet name="Sheet 1">
      <table><view>
        <cols>[Ordini_6D2EF74F348B46BDA976A7AEEA6FB5C9]</cols>
        <rows>[ds1].[none:Segmento:nk]</rows>
      </view></table>
    </worksheet>
  </worksheets>
  <dashboards />
</workbook>"""
        with managed_tempdir() as tmpdir:
            path = tmpdir / "sample.twb"
            path.write_text(xml, encoding="utf-8")
            result = extract_workbook_metadata(str(path))

        ws = result["worksheets"][0]
        shelf_fields = [ref.get("field") for ref in ws["cols_shelf"]]
        self.assertIn("Ordini", shelf_fields)
        self.assertNotIn("Ordini_6D2EF74F348B46BDA976A7AEEA6FB5C9", shelf_fields)
