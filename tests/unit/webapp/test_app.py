"""Tests for Tableau2PowerBI.webapp.app — SSE handler and doc routes.

Covers:
- _SSELogHandler sub-agent event detection
- GET /documentation/{workbook_name}/html and /md routes (404 + success)
- Prompt field removal: analyze_stream signature and index.html template
"""

import inspect
import logging
import asyncio
from io import BytesIO
import queue
import unittest
from types import SimpleNamespace

from fastapi import HTTPException
from starlette.datastructures import UploadFile

from Tableau2PowerBI.webapp.app import _SSELogHandler, _validate_upload_content_length
from Tableau2PowerBI.webapp.pipeline_stream_routes import build_analyze_stream_response


class SSELogHandlerTests(unittest.TestCase):
    """Verify the SSE log handler correctly routes sub-agent events."""

    def setUp(self):
        self.log_queue: queue.Queue = queue.Queue(maxsize=100)
        self.handler = _SSELogHandler(self.log_queue)
        self.logger = logging.getLogger("test.sse_handler")
        self.logger.addHandler(self.handler)
        self.logger.setLevel(logging.DEBUG)

    def tearDown(self):
        self.logger.removeHandler(self.handler)

    def test_regular_log_emits_log_type(self):
        """A normal log record is emitted with type='log'."""
        self.logger.info("Hello world")
        msg = self.log_queue.get_nowait()
        self.assertEqual(msg["type"], "log")
        self.assertEqual(msg["level"], "INFO")
        self.assertIn("Hello world", msg["message"])

    def test_sub_agent_event_emits_sub_agent_type(self):
        """A log record with extra.sub_agent is emitted with type='sub_agent'."""
        self.logger.info(
            "Processing page 'Overview'",
            extra={
                "sub_agent": {
                    "agent_id": "pbip_visuals_generator",
                    "page_name": "Overview",
                    "page_index": 0,
                    "page_total": 3,
                    "state": "running",
                },
            },
        )
        msg = self.log_queue.get_nowait()
        self.assertEqual(msg["type"], "sub_agent")
        self.assertEqual(msg["agent_id"], "pbip_visuals_generator")
        self.assertEqual(msg["page_name"], "Overview")
        self.assertEqual(msg["page_index"], 0)
        self.assertEqual(msg["page_total"], 3)
        self.assertEqual(msg["state"], "running")
        self.assertIn("Overview", msg["message"])

    def test_sub_agent_done_includes_visuals_count(self):
        """A 'done' sub-agent event includes the visuals_count field."""
        self.logger.info(
            "Page 1/2 (Overview) — 5 visuals",
            extra={
                "sub_agent": {
                    "agent_id": "pbip_visuals_generator",
                    "page_name": "Overview",
                    "page_index": 0,
                    "page_total": 2,
                    "visuals_count": 5,
                    "state": "done",
                },
            },
        )
        msg = self.log_queue.get_nowait()
        self.assertEqual(msg["type"], "sub_agent")
        self.assertEqual(msg["state"], "done")
        self.assertEqual(msg["visuals_count"], 5)

    def test_sub_agent_error_event(self):
        """A sub-agent error event is correctly emitted."""
        self.logger.error(
            "Page 'Detail' failed",
            extra={
                "sub_agent": {
                    "agent_id": "pbip_visuals_generator",
                    "page_name": "Detail",
                    "page_index": 1,
                    "page_total": 2,
                    "state": "error",
                },
            },
        )
        msg = self.log_queue.get_nowait()
        self.assertEqual(msg["type"], "sub_agent")
        self.assertEqual(msg["state"], "error")
        self.assertEqual(msg["page_name"], "Detail")

    def test_non_dict_sub_agent_treated_as_regular_log(self):
        """If sub_agent is not a dict, the record is treated as a regular log."""
        self.logger.info(
            "Weird extra",
            extra={"sub_agent": "not-a-dict"},
        )
        msg = self.log_queue.get_nowait()
        self.assertEqual(msg["type"], "log")

    def test_queue_full_does_not_raise(self):
        """When the queue is full, emit silently drops the record."""
        tiny_queue: queue.Queue = queue.Queue(maxsize=1)
        handler = _SSELogHandler(tiny_queue)
        logger = logging.getLogger("test.full_queue")
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        try:
            logger.info("First")
            logger.info("Second — should be dropped silently")
            self.assertEqual(tiny_queue.qsize(), 1)
        finally:
            logger.removeHandler(handler)


class PageRoutesTests(unittest.TestCase):
    """Test that each HTML page route returns 200 and the correct content."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient

        from Tableau2PowerBI.webapp.app import app

        cls.client = TestClient(app)

    def test_index_returns_200(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers["content-type"])

    def test_index_uses_configured_upload_limit_not_stale_50_mb_literal(self):
        resp = self.client.get("/")
        self.assertIn("max 10240 MB", resp.text)
        self.assertIn('data-upload-limit-bytes="10737418240"', resp.text)
        self.assertNotIn("max 50 MB", resp.text)
        self.assertNotIn("52428800", resp.text)

    def test_results_returns_200(self):
        resp = self.client.get("/results")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("results-shared.css", resp.text)
        self.assertIn("results-analysis.js", resp.text)

    def test_generate_returns_200(self):
        resp = self.client.get("/generate")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("results-generate.js", resp.text)

    def test_warnings_returns_200(self):
        resp = self.client.get("/warnings")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("results-warnings.js", resp.text)

    def test_results_no_inline_style_block(self):
        """results.html should not contain inline <style> blocks (CSS is external)."""
        resp = self.client.get("/results")
        # The file should reference external CSS, not have a big inline block
        self.assertNotIn("<style>", resp.text)

    def test_results_no_inline_script_block(self):
        """results.html should not contain large inline <script> blocks (JS is external)."""
        resp = self.client.get("/results")
        # Small inline script for wiring links is OK, but no function definitions
        self.assertNotIn("function enableTableSort", resp.text)
        self.assertNotIn("function renderCharts", resp.text)

    def test_generate_has_pipeline_overlay(self):
        """generate.html should have the pipeline progress overlay."""
        resp = self.client.get("/generate")
        self.assertIn("pipelineOverlay", resp.text)
        self.assertIn("generateBtn", resp.text)

    def test_warnings_has_review_overlay(self):
        """warnings.html should have the warnings review overlay."""
        resp = self.client.get("/warnings")
        self.assertIn("reviewOverlay", resp.text)
        self.assertIn("btnReviewWarnings", resp.text)

    def test_static_css_files_served(self):
        """Shared CSS file should be served from /static/."""
        resp = self.client.get("/static/results-shared.css")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/css", resp.headers["content-type"])

    def test_static_js_files_served(self):
        """Shared JS files should be served from /static/."""
        for name in ["results-shared.js", "results-analysis.js", "results-generate.js", "results-warnings.js"]:
            resp = self.client.get(f"/static/{name}")
            self.assertEqual(resp.status_code, 200, f"{name} not served")


class UploadPreflightValidationTests(unittest.TestCase):
    """Validate request-size preflight checks for upload endpoints."""

    def test_missing_content_length_is_accepted(self):
        request = SimpleNamespace(headers={})
        _validate_upload_content_length(request, 100, 1)

    def test_invalid_content_length_raises_400(self):
        request = SimpleNamespace(headers={"content-length": "not-a-number"})
        with self.assertRaises(HTTPException) as exc_info:
            _validate_upload_content_length(request, 100, 1)
        self.assertEqual(exc_info.exception.status_code, 400)

    def test_oversized_content_length_raises_413(self):
        request = SimpleNamespace(headers={"content-length": "101"})
        with self.assertRaises(HTTPException) as exc_info:
            _validate_upload_content_length(request, 100, 1)
        self.assertEqual(exc_info.exception.status_code, 413)
        self.assertEqual(exc_info.exception.detail, "File exceeds the 1 MB limit")

    def test_oversized_upload_body_raises_configured_413_message(self):
        async def run_test():
            upload = UploadFile(filename="oversized.twb", file=BytesIO(b"abc"))
            with self.assertRaises(HTTPException) as exc_info:
                await build_analyze_stream_response(
                    upload,
                    upload_to_adls_fn=lambda *args, **kwargs: None,
                    metadata_extractor_cls=object,
                    get_history_fn=lambda: None,
                    get_settings_fn=lambda: None,
                    logger=logging.getLogger("test.upload_limit"),
                    allowed_extensions={".twb", ".twbx"},
                    max_file_size=2,
                    max_file_size_mb=1,
                )
            self.assertEqual(exc_info.exception.status_code, 413)
            self.assertEqual(exc_info.exception.detail, "File exceeds the 1 MB limit")

        asyncio.run(run_test())


class DocumentationRoutesTests(unittest.TestCase):
    """Test the GET /documentation/{workbook_name}/html and /md routes."""

    @classmethod
    def setUpClass(cls):
        """Create a test client once (avoids repeated import overhead)."""
        from fastapi.testclient import TestClient

        from Tableau2PowerBI.webapp.app import app

        cls.client = TestClient(app)

    def test_html_returns_404_when_file_missing(self):
        """GET /documentation/NonExistent/html returns 404."""
        resp = self.client.get("/documentation/NonExistent_WB_XYZ/html")
        self.assertEqual(resp.status_code, 404)

    def test_md_returns_404_when_file_missing(self):
        """GET /documentation/NonExistent/md returns 404."""
        resp = self.client.get("/documentation/NonExistent_WB_XYZ/md")
        self.assertEqual(resp.status_code, 404)

    def test_html_returns_file_when_present(self):
        """GET /documentation/Test/html returns 200 and the file content."""
        from Tableau2PowerBI.core.output_dirs import get_output_dir

        doc_dir = get_output_dir("tableau_functional_doc_agent", "TestWB123")
        doc_dir.mkdir(parents=True, exist_ok=True)
        html_file = doc_dir / "functional_documentation.html"
        html_file.write_text(
            "<html><body>Test Doc</body></html>",
            encoding="utf-8",
        )
        try:
            resp = self.client.get("/documentation/TestWB123/html")
            self.assertEqual(resp.status_code, 200)
            self.assertIn("text/html", resp.headers["content-type"])
            self.assertIn("Test Doc", resp.text)
            # Must render inline, not trigger a download.
            disposition = resp.headers.get("content-disposition", "")
            self.assertNotIn(
                "attachment",
                disposition,
                "HTML doc should be served inline, not as attachment",
            )
        finally:
            html_file.unlink(missing_ok=True)
            # Clean up the directory tree.
            import shutil

            shutil.rmtree(doc_dir, ignore_errors=True)

    def test_md_returns_file_when_present(self):
        """GET /documentation/Test/md returns 200 and the file content."""
        from Tableau2PowerBI.core.output_dirs import get_output_dir

        doc_dir = get_output_dir("tableau_functional_doc_agent", "TestWB456")
        doc_dir.mkdir(parents=True, exist_ok=True)
        md_file = doc_dir / "functional_documentation.md"
        md_file.write_text("# Test\n\nMarkdown doc.", encoding="utf-8")
        try:
            resp = self.client.get("/documentation/TestWB456/md")
            self.assertEqual(resp.status_code, 200)
            self.assertIn("# Test", resp.text)
            # Markdown should be served as a download.
            disposition = resp.headers.get("content-disposition", "")
            self.assertIn(
                "attachment",
                disposition,
                "Markdown doc should be served as an attachment download",
            )
        finally:
            md_file.unlink(missing_ok=True)
            import shutil

            shutil.rmtree(doc_dir, ignore_errors=True)


class ResultStoreAPITests(unittest.TestCase):
    """Tests for GET/POST /api/results/{result_id} endpoints."""

    def setUp(self):
        from Tableau2PowerBI.webapp.app import _result_store

        self._store = _result_store
        self._store.clear()
        from fastapi.testclient import TestClient

        from Tableau2PowerBI.webapp.app import app

        self.client = TestClient(app)

    def tearDown(self):
        self._store.clear()

    def test_get_unknown_id_returns_404(self):
        resp = self.client.get("/api/results/result_1234567890123")
        self.assertEqual(resp.status_code, 404)

    def test_invalid_id_format_returns_error(self):
        resp = self.client.get("/api/results/not_a_valid_id")
        self.assertIn(resp.status_code, (400, 404, 422))

    def test_post_and_get_round_trip(self):
        payload = {"id": "result_1000", "filename": "test.twb", "result": "{}"}
        resp = self.client.post(
            "/api/results/result_1000",
            json=payload,
        )
        self.assertEqual(resp.status_code, 200)

        resp = self.client.get("/api/results/result_1000")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["filename"], "test.twb")

    def test_server_side_store_result(self):
        """store_result() makes data retrievable via GET."""
        import json

        from Tableau2PowerBI.webapp.app import store_result

        store_result("result_9999", json.dumps({"filename": "hello.twbx"}))
        resp = self.client.get("/api/results/result_9999")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["filename"], "hello.twbx")


class GenerateStreamTDDReuseTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient

        from Tableau2PowerBI.webapp.app import app

        self.client = TestClient(app)

    def test_partial_tdd_regenerates_when_dax_design_missing(self):
        import json
        import shutil
        from unittest.mock import patch

        from Tableau2PowerBI.core.output_dirs import get_output_dir

        workbook = "PartialTddWB"
        tdd_dir = get_output_dir("target_technical_doc_agent", workbook)
        tdd_dir.mkdir(parents=True, exist_ok=True)
        (tdd_dir / "semantic_model_design.json").write_text("{}", encoding="utf-8")
        (tdd_dir / "report_design.json").write_text("{}", encoding="utf-8")

        tdd_result = SimpleNamespace(
            semantic_model=SimpleNamespace(tables=[]),
            dax_measures=SimpleNamespace(measures=[]),
            report=SimpleNamespace(pages=[]),
        )

        try:
            with (
                patch(
                    "Tableau2PowerBI.webapp.app.TargetTechnicalDocAgent.generate_tdd",
                    return_value=tdd_result,
                ) as gen_tdd,
                patch(
                    "Tableau2PowerBI.webapp.app.PBIPProjectSkeletonAgent.generate_pbip_project_skeleton",
                    return_value="ok",
                ),
                patch(
                    "Tableau2PowerBI.webapp.app.PBIPSemanticModelGeneratorAgent.generate_pbip_semantic_model",
                    return_value=None,
                ),
                patch(
                    "Tableau2PowerBI.webapp.app.TmdlMeasuresGeneratorAgent.generate_tmdl_measures",
                    return_value=None,
                ),
                patch(
                    "Tableau2PowerBI.webapp.app.PbirReportGeneratorAgent.generate_pbir_report",
                    return_value=None,
                ),
                patch(
                    "Tableau2PowerBI.webapp.app.PBIPProjectAssemblerAgent.assemble_pbip_project",
                    return_value="ok",
                ),
            ):
                with self.client.stream(
                    "POST",
                    "/generate-stream",
                    json={
                        "metadata_json": json.dumps({}),
                        "twb_path": f"{workbook}.twb",
                    },
                ) as resp:
                    self.assertEqual(resp.status_code, 200)
                    list(resp.iter_text())

            self.assertTrue(gen_tdd.called)
        finally:
            shutil.rmtree(tdd_dir, ignore_errors=True)

    def test_generate_stream_rejects_invalid_force_stages(self):
        """POST /generate-stream with invalid force_stages returns 422."""
        import json

        resp = self.client.post(
            "/generate-stream",
            json={
                "metadata_json": json.dumps({}),
                "twb_path": "test.twb",
                "force_stages": ["bogus_stage", "also_fake"],
            },
        )
        self.assertEqual(resp.status_code, 422)
        self.assertIn("bogus_stage", resp.text)

    def test_generate_stream_accepts_valid_force_stages(self):
        """POST /generate-stream with valid force_stages does not 422."""
        resp = self.client.post(
            "/generate-stream",
            json={
                "metadata_json": "{}",
                "twb_path": "test.twb",
                "force_stages": ["semantic_model", "dax_measures"],
            },
        )
        # Should not be 422 (may fail later in pipeline, but validation passes)
        self.assertNotEqual(resp.status_code, 422)


class PromptParamRemovalTests(unittest.TestCase):
    """Tests that verify the 'prompt' parameter has been removed from the webapp."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from Tableau2PowerBI.webapp.app import app
        cls.client = TestClient(app)

    def test_analyze_stream_accepts_request_without_prompt(self):
        """Given a valid file upload with only lang, when POST /analyze-stream,
        then the endpoint returns 200 and begins streaming.
        """
        twb_content = b"<workbook></workbook>"
        response = self.client.post(
            "/analyze-stream",
            data={"lang": "en"},
            files={"file": ("test.twb", twb_content, "application/octet-stream")},
        )
        # 200 means the endpoint accepted the request without a prompt field
        self.assertEqual(response.status_code, 200)

    def test_analyze_stream_ignores_extra_prompt_field(self):
        """Given a valid file upload that includes an extra prompt field,
        when POST /analyze-stream, then the endpoint returns 200 (no 422 rejection).
        """
        twb_content = b"<workbook></workbook>"
        response = self.client.post(
            "/analyze-stream",
            data={"lang": "en", "prompt": "some extra text"},
            files={"file": ("test.twb", twb_content, "application/octet-stream")},
        )
        # Must not 422: the endpoint should ignore the extra prompt field
        self.assertNotEqual(response.status_code, 422)

    def test_prompt_param_constant_removed(self):
        """Given the app module, when checking for the attribute _PROMPT_PARAM,
        then hasattr(app_module, '_PROMPT_PARAM') is False.
        """
        import Tableau2PowerBI.webapp.app as app_module
        self.assertFalse(
            hasattr(app_module, "_PROMPT_PARAM"),
            "_PROMPT_PARAM should have been removed from app.py",
        )

    def test_analyze_stream_signature_has_no_prompt_param(self):
        """Given the analyze_stream function, when inspecting its signature via
        inspect.signature, then 'prompt' is not in the parameter names.
        """
        from Tableau2PowerBI.webapp.app import analyze_stream
        sig = inspect.signature(analyze_stream)
        self.assertNotIn(
            "prompt",
            sig.parameters,
            "analyze_stream should not have a 'prompt' parameter",
        )

    def test_index_html_has_no_prompt_textarea(self):
        """Given the rendered index.html template, when searching for id="prompt",
        then no match is found.
        """
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(
            'id="prompt"',
            response.text,
            'index.html should not contain a textarea with id="prompt"',
        )

    def test_index_html_has_no_prompt_formdata_append(self):
        """Given the rendered index.html template, when searching for fd.append('prompt',
        then no match is found.
        """
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(
            "fd.append('prompt',",
            response.text,
            "index.html should not append a 'prompt' field to FormData",
        )


if __name__ == "__main__":
    unittest.main()
