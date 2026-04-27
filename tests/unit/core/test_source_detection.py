from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

from Tableau2PowerBI.core.source_detection import detect_source_file
from tests.support import managed_tempdir


_MINIMAL_TWB = (
    '<?xml version="1.0"?>'
    '<workbook xmlns:user="http://www.tableausoftware.com/xml/user"'
    ' source-build="2024.1.0" source-platform="win" version="18.1">'
    "<datasources/><worksheets/><dashboards/>"
    "</workbook>"
)


def _write_minimal_pbip_zip(path: Path, *, project_name: str = "SalesModel", pbip_count: int = 1) -> None:
    with ZipFile(path, "w") as zf:
        for idx in range(pbip_count):
            suffix = "" if idx == 0 else str(idx + 1)
            zf.writestr(
                f"{project_name}{suffix}.pbip",
                """{
  "version": "1.0",
  "artifacts": [{"report": {"path": "SalesModel.Report"}}]
}""",
            )
        zf.writestr(
            "SalesModel.Report/definition.pbir",
            """{
  "version": "4.0",
  "datasetReference": {"byPath": {"path": "../SalesModel.SemanticModel"}}
}""",
        )


class TestDetectSourceFile:
    def test_detects_twb(self) -> None:
        with managed_tempdir() as tmpdir:
            path = tmpdir / "Workbook.twb"
            path.write_text(_MINIMAL_TWB, encoding="utf-8")

            detected = detect_source_file(path)

        assert detected.source_format == "tableau"
        assert detected.workbook_name == "Workbook"
        assert detected.metadata_agent_name == "tableau_metadata_extractor_agent"

    def test_detects_twbx(self) -> None:
        with managed_tempdir() as tmpdir:
            path = tmpdir / "Workbook.twbx"
            with ZipFile(path, "w") as zf:
                zf.writestr("Workbook.twb", _MINIMAL_TWB)

            detected = detect_source_file(path)

        assert detected.source_format == "tableau"
        assert detected.workbook_name == "Workbook"

    def test_detects_pbip_zip(self) -> None:
        with managed_tempdir() as tmpdir:
            path = tmpdir / "upload.zip"
            _write_minimal_pbip_zip(path)

            detected = detect_source_file(path)

        assert detected.source_format == "pbip"
        assert detected.workbook_name == "SalesModel"
        assert detected.metadata_agent_name == "powerbi_metadata_extractor_agent"
        assert detected.pbip_entry == "SalesModel.pbip"

    def test_rejects_zip_without_pbip(self) -> None:
        with managed_tempdir() as tmpdir:
            path = tmpdir / "invalid.zip"
            with ZipFile(path, "w") as zf:
                zf.writestr("notes.txt", "not a pbip")

            with pytest.raises(ValueError, match="exactly one \\.pbip"):
                detect_source_file(path)

    def test_rejects_zip_with_multiple_pbips(self) -> None:
        with managed_tempdir() as tmpdir:
            path = tmpdir / "multiple.zip"
            _write_minimal_pbip_zip(path, pbip_count=2)

            with pytest.raises(ValueError, match="multiple \\.pbip"):
                detect_source_file(path)
