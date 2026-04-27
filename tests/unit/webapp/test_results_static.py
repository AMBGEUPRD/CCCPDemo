from pathlib import Path

_WEBAPP = Path(__file__).resolve().parents[3] / "src" / "Tableau2PowerBI" / "webapp"
_STATIC = _WEBAPP / "static"
_TEMPLATES = _WEBAPP / "templates"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestResultsPbipStatic:
    def test_results_template_has_calculated_columns_section(self) -> None:
        html = _read(_TEMPLATES / "results.html")
        assert 'id="cardCalcColumns"' in html
        assert 'id="tableCalcColumns"' in html
        assert 'id="tablePageVisuals"' in html
        assert 'id="chartCard1Title"' in html
        assert 'id="chartCard2Title"' in html
        assert 'aria-expanded="false"' in html
        assert "<th>Status " not in html
        assert "Calculated Columns" in html

    def test_results_analysis_has_pbip_copy_and_page_visual_table(self) -> None:
        js = _read(_STATIC / "results-analysis.js")
        assert "Queries & Expressions" in js
        assert "Parameter Query" in js
        assert "renderCharts('pbip', pbip)" in js
        assert "renderPbipPageVisualTable" in js
        assert "tableCalcColumns" in js
        assert "tablePageVisuals" in js
        assert "Simple inventory of business and technical/support objects" in js
        assert "Auto Date Table" in js
        assert "Template Date Table" in js
        assert "calculated table" in js

    def test_results_analysis_has_tableau_consistency_copy(self) -> None:
        js = _read(_STATIC / "results-analysis.js")
        assert "_setSectionCopyTableau" in js
        assert "Queries & Connections" in js
        assert "Model Columns" in js
        assert "Calculations" in js
        assert "Pages & Visuals" in js
        assert "renderTableauPageVisualTable" in js
        assert "renderCharts('tableau', analysis)" in js

    def test_results_shared_assets_remove_height_cap_and_use_hidden_state(self) -> None:
        css = _read(_STATIC / "results-shared.css")
        shared_js = _read(_STATIC / "results-shared.js")
        assert "max-height: 2000px" not in css
        assert ".section-card-body[hidden]" in css
        assert ".field-raw-id--static" in css
        assert ".table-wrap" in css
        assert "#tablePageVisuals" in css
        assert "white-space:nowrap;" in css
        assert ".section-card:hover { transform:scale(1.02); }" not in css
        assert "aria-expanded" in shared_js
        assert "body.hidden =" in shared_js
