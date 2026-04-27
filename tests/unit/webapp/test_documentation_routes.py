"""Tests for webapp.documentation_routes — documentation route helpers."""

from __future__ import annotations

import json
import logging
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.responses import FileResponse

from Tableau2PowerBI.webapp.documentation_routes import (
    build_tdd_stream_response,
    check_documentation_exists_response,
    get_documentation_html_response,
    get_documentation_md_response,
    get_tdd_html_response,
    get_tdd_md_response,
)
from tests.support import managed_tempdir


class GetDocumentationHtmlTests(unittest.TestCase):
    """Tests for get_documentation_html_response."""

    @patch("Tableau2PowerBI.webapp.documentation_routes.get_output_dir")
    def test_returns_file_response_when_exists(self, mock_get_output):
        with managed_tempdir() as tmpdir:
            html_path = tmpdir / "functional_documentation.html"
            html_path.write_text("<html></html>", encoding="utf-8")
            mock_get_output.return_value = tmpdir

            result = get_documentation_html_response("TestWb")
            self.assertIsInstance(result, FileResponse)

    @patch("Tableau2PowerBI.webapp.documentation_routes.get_output_dir")
    def test_raises_404_when_missing(self, mock_get_output):
        with managed_tempdir() as tmpdir:
            mock_get_output.return_value = tmpdir

            with self.assertRaises(HTTPException) as ctx:
                get_documentation_html_response("TestWb")
            self.assertEqual(ctx.exception.status_code, 404)


class GetDocumentationMdTests(unittest.TestCase):
    """Tests for get_documentation_md_response."""

    @patch("Tableau2PowerBI.webapp.documentation_routes.get_output_dir")
    def test_returns_file_response_when_exists(self, mock_get_output):
        with managed_tempdir() as tmpdir:
            md_path = tmpdir / "functional_documentation.md"
            md_path.write_text("# Doc", encoding="utf-8")
            mock_get_output.return_value = tmpdir

            result = get_documentation_md_response("TestWb")
            self.assertIsInstance(result, FileResponse)

    @patch("Tableau2PowerBI.webapp.documentation_routes.get_output_dir")
    def test_raises_404_when_missing(self, mock_get_output):
        with managed_tempdir() as tmpdir:
            mock_get_output.return_value = tmpdir

            with self.assertRaises(HTTPException) as ctx:
                get_documentation_md_response("TestWb")
            self.assertEqual(ctx.exception.status_code, 404)


class GetTddHtmlTests(unittest.TestCase):
    """Tests for get_tdd_html_response."""

    @patch("Tableau2PowerBI.webapp.documentation_routes.get_output_dir")
    def test_returns_file_response_when_exists(self, mock_get_output):
        with managed_tempdir() as tmpdir:
            html_path = tmpdir / "target_technical_documentation.html"
            html_path.write_text("<html></html>", encoding="utf-8")
            mock_get_output.return_value = tmpdir

            result = get_tdd_html_response("TestWb")
            self.assertIsInstance(result, FileResponse)

    @patch("Tableau2PowerBI.webapp.documentation_routes.get_output_dir")
    def test_raises_404_when_missing(self, mock_get_output):
        with managed_tempdir() as tmpdir:
            mock_get_output.return_value = tmpdir

            with self.assertRaises(HTTPException) as ctx:
                get_tdd_html_response("TestWb")
            self.assertEqual(ctx.exception.status_code, 404)


class GetTddMdTests(unittest.TestCase):
    """Tests for get_tdd_md_response."""

    @patch("Tableau2PowerBI.webapp.documentation_routes.get_output_dir")
    def test_returns_file_response_when_exists(self, mock_get_output):
        with managed_tempdir() as tmpdir:
            md_path = tmpdir / "target_technical_documentation.md"
            md_path.write_text("# TDD", encoding="utf-8")
            mock_get_output.return_value = tmpdir

            result = get_tdd_md_response("TestWb")
            self.assertIsInstance(result, FileResponse)

    @patch("Tableau2PowerBI.webapp.documentation_routes.get_output_dir")
    def test_raises_404_when_missing(self, mock_get_output):
        with managed_tempdir() as tmpdir:
            mock_get_output.return_value = tmpdir

            with self.assertRaises(HTTPException) as ctx:
                get_tdd_md_response("TestWb")
            self.assertEqual(ctx.exception.status_code, 404)


class CheckDocumentationExistsTests(unittest.TestCase):
    """Tests for check_documentation_exists_response."""

    @patch("Tableau2PowerBI.webapp.documentation_routes.get_output_dir")
    def test_returns_true_when_html_exists(self, mock_get_output):
        with managed_tempdir() as tmpdir:
            (tmpdir / "functional_documentation.html").write_text("<html/>")
            mock_get_output.return_value = tmpdir

            result = check_documentation_exists_response("TestWb")
            self.assertTrue(result["exists"])

    @patch("Tableau2PowerBI.webapp.documentation_routes.get_output_dir")
    def test_returns_true_when_md_exists(self, mock_get_output):
        with managed_tempdir() as tmpdir:
            (tmpdir / "functional_documentation.md").write_text("# Doc")
            mock_get_output.return_value = tmpdir

            result = check_documentation_exists_response("TestWb")
            self.assertTrue(result["exists"])

    @patch("Tableau2PowerBI.webapp.documentation_routes.get_output_dir")
    def test_returns_false_when_neither_exists(self, mock_get_output):
        with managed_tempdir() as tmpdir:
            mock_get_output.return_value = tmpdir

            result = check_documentation_exists_response("TestWb")
            self.assertFalse(result["exists"])


class _FakeRequest:
    """Minimal async request stub for JSON bodies."""

    def __init__(self, body: dict) -> None:
        self._body = body

    async def json(self) -> dict:
        return self._body


class _FakeTddAgent:
    """Minimal agent that emits the two expected TDD phase logs."""

    def __init__(self) -> None:
        self.logger = logging.getLogger("Tableau2PowerBI.tests.tdd")
        self.logger.setLevel(logging.INFO)

    def create(self) -> None:
        return None

    def close(self) -> None:
        return None

    def generate_tdd(self, workbook_name: str):
        self.logger.info("[TDD:PHASE] 1/2 Data Model Design - Creating semantic model and DAX measures")
        self.logger.info("[TDD:PHASE] 2/2 Report Design - Creating report layout and visuals")
        return SimpleNamespace(
            semantic_model=SimpleNamespace(tables=[{"name": "Sales"}]),
            dax_measures=SimpleNamespace(measures=[{"name": "Revenue"}]),
            report=SimpleNamespace(pages=[{"name": "Overview"}]),
        )


class BuildTddStreamResponseTests(unittest.IsolatedAsyncioTestCase):
    """Tests for the TDD SSE stream response."""

    @patch("Tableau2PowerBI.webapp.documentation_routes.get_output_dir")
    async def test_emits_running_phase_updates_for_both_tdd_phases(self, mock_get_output):
        with managed_tempdir() as tmpdir:
            mock_get_output.return_value = tmpdir
            request = _FakeRequest({"workbook_name": "TestWb"})
            response = await build_tdd_stream_response(
                request,
                target_technical_doc_cls=_FakeTddAgent,
                get_history_fn=lambda: None,
                logger=logging.getLogger("tests.webapp.documentation_routes"),
            )

            payloads = []
            async for chunk in response.body_iterator:
                for raw_event in chunk.split("\n\n"):
                    if not raw_event.strip():
                        continue
                    for line in raw_event.splitlines():
                        if line.startswith("data: "):
                            payloads.append(json.loads(line[6:]))

        running_phase_events = [
            payload for payload in payloads if payload.get("state") == "running" and payload.get("phase")
        ]
        self.assertEqual(len(running_phase_events), 2)
        self.assertEqual(running_phase_events[0]["phase_step"], 1)
        self.assertIn("1/2 Data Model Design", running_phase_events[0]["phase"])
        self.assertEqual(running_phase_events[1]["phase_step"], 2)
        self.assertIn("2/2 Report Design", running_phase_events[1]["phase"])

        complete_events = [payload for payload in payloads if payload.get("state") == "complete"]
        self.assertEqual(len(complete_events), 1)
        self.assertEqual(complete_events[0]["tdd"]["tables"], 1)

