import json
import logging
import os
import unittest

from Tableau2PowerBI.core.config import AgentSettings, get_agent_settings
from Tableau2PowerBI.core.llm_output_parsing import (
    extract_json_from_markdown,
    normalise_warnings,
    recover_malformed_json,
    strip_markdown_fences,
)
from Tableau2PowerBI.core.logging_setup import setup_logging, shorten_abs_paths
from Tableau2PowerBI.core.output_dirs import (
    get_output_dir,
    reset_output_dir,
    resolve_safe_path,
    validate_name,
)
from tests.support import managed_tempdir


class ConfigAndUtilsTests(unittest.TestCase):
    def test_get_agent_settings_returns_default_runtime_settings(self):
        settings = get_agent_settings()

        self.assertTrue(settings.project_endpoint.startswith("https://"))
        self.assertEqual(settings.default_model, "gpt-4.1")

    def test_get_output_dir_uses_settings_boundary(self):
        with managed_tempdir() as tmpdir:
            settings = AgentSettings(
                project_endpoint="https://example.test",
                output_root=tmpdir,
            )

            output_dir = get_output_dir("agent-name", "run-name", settings)

            self.assertEqual(output_dir, tmpdir / "agent-name" / "run-name")


class ResetOutputDirTests(unittest.TestCase):
    def test_creates_dir_if_missing(self):
        with managed_tempdir() as tmpdir:
            target = tmpdir / "fresh"
            self.assertFalse(target.exists())
            reset_output_dir(target)
            self.assertTrue(target.is_dir())

    def test_removes_stale_files(self):
        with managed_tempdir() as tmpdir:
            target = tmpdir / "stale"
            target.mkdir()
            stale_file = target / "leftover.tmdl"
            stale_file.write_text("old data")
            self.assertTrue(stale_file.exists())

            reset_output_dir(target)

            self.assertTrue(target.is_dir())
            self.assertFalse(stale_file.exists())
            self.assertEqual(list(target.iterdir()), [])

    def test_removes_nested_stale_dirs(self):
        with managed_tempdir() as tmpdir:
            target = tmpdir / "deep"
            nested = target / "sub" / "dir"
            nested.mkdir(parents=True)
            (nested / "file.txt").write_text("old")

            reset_output_dir(target)

            self.assertTrue(target.is_dir())
            self.assertFalse((target / "sub").exists())


# ── strip_markdown_fences ─────────────────────────────────────────────────


class StripMarkdownFencesTests(unittest.TestCase):
    def test_json_fences_stripped(self):
        text = '```json\n{"key": "value"}\n```'
        self.assertEqual(strip_markdown_fences(text), '{"key": "value"}')

    def test_tmdl_fences_stripped(self):
        text = "```tmdl\ntable Orders\n```"
        self.assertEqual(strip_markdown_fences(text), "table Orders")

    def test_bare_fences_stripped(self):
        text = "```\nsome content\n```"
        self.assertEqual(strip_markdown_fences(text), "some content")

    def test_no_fences_unchanged(self):
        text = '{"key": "value"}'
        self.assertEqual(strip_markdown_fences(text), text)

    def test_empty_string(self):
        self.assertEqual(strip_markdown_fences(""), "")

    def test_whitespace_around_fences_stripped(self):
        text = "  ```json\n  content  \n```  "
        self.assertEqual(strip_markdown_fences(text), "content")


# ── normalise_warnings ────────────────────────────────────────────────────


class NormaliseWarningsTests(unittest.TestCase):
    def test_list_of_dicts(self):
        raw = [{"severity": "warn", "code": "W1", "message": "msg"}]
        result = normalise_warnings(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["severity"], "WARN")
        self.assertEqual(result[0]["code"], "W1")
        self.assertIn("timestamp", result[0])

    def test_single_dict(self):
        raw = {"severity": "error", "code": "E1", "message": "bad"}
        result = normalise_warnings(raw)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["severity"], "ERROR")

    def test_list_of_strings(self):
        raw = ["warning one", "warning two"]
        result = normalise_warnings(raw)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["code"], "UNSTRUCTURED_WARNING")
        self.assertEqual(result[0]["message"], "warning one")
        self.assertEqual(result[1]["message"], "warning two")

    def test_none_returns_empty(self):
        self.assertEqual(normalise_warnings(None), [])

    def test_empty_list_returns_empty(self):
        self.assertEqual(normalise_warnings([]), [])

    def test_dict_without_severity_defaults_to_warn(self):
        raw = [{"code": "C1", "message": "m"}]
        result = normalise_warnings(raw)
        self.assertEqual(result[0]["severity"], "WARN")


# ── validate_name ─────────────────────────────────────────────────────────


class ValidateNameTests(unittest.TestCase):
    def test_valid_name_returned_stripped(self):
        self.assertEqual(validate_name("Test", "  MyName  "), "MyName")

    def test_empty_name_raises(self):
        with self.assertRaises(ValueError):
            validate_name("Test", "")

    def test_whitespace_only_raises(self):
        with self.assertRaises(ValueError):
            validate_name("Test", "   ")

    def test_backslash_rejected(self):
        with self.assertRaises(ValueError):
            validate_name("Test", "path\\name")

    def test_forward_slash_rejected(self):
        with self.assertRaises(ValueError):
            validate_name("Test", "path/name")

    def test_colon_rejected(self):
        with self.assertRaises(ValueError):
            validate_name("Test", "C:")

    def test_traversal_dots_with_slash_rejected(self):
        with self.assertRaises(ValueError):
            validate_name("Test", "../escape")

    def test_name_with_spaces_and_dashes_accepted(self):
        self.assertEqual(
            validate_name("Test", "My Workbook - Sales"),
            "My Workbook - Sales",
        )


# ── resolve_safe_path ─────────────────────────────────────────────────────


class ResolveSafePathTests(unittest.TestCase):
    def test_valid_relative_path(self):
        with managed_tempdir() as tmpdir:
            result = resolve_safe_path(tmpdir, "sub/dir/file.txt")
            self.assertTrue(str(result).startswith(str(tmpdir.resolve())))

    def test_traversal_attack_rejected(self):
        with managed_tempdir() as tmpdir:
            with self.assertRaises(ValueError):
                resolve_safe_path(tmpdir, "../../etc/passwd")

    def test_base_path_itself_is_valid(self):
        with managed_tempdir() as tmpdir:
            result = resolve_safe_path(tmpdir, "")
            self.assertEqual(result, tmpdir.resolve())


# ── extract_json_from_markdown ────────────────────────────────────────────


class ExtractJsonFromMarkdownTests(unittest.TestCase):
    def test_plain_json(self):
        text = '{"key": "value"}'
        self.assertEqual(extract_json_from_markdown(text), {"key": "value"})

    def test_fenced_json(self):
        text = '```json\n{"key": "value"}\n```'
        self.assertEqual(extract_json_from_markdown(text), {"key": "value"})

    def test_fenced_json_with_surrounding_text(self):
        text = 'Here is the result:\n```json\n{"a": 1}\n```\nDone.'
        self.assertEqual(extract_json_from_markdown(text), {"a": 1})

    def test_invalid_json_raises(self):
        with self.assertRaises(json.JSONDecodeError):
            extract_json_from_markdown("not json at all")

    def test_nested_json_object(self):
        text = '{"outer": {"inner": [1, 2, 3]}}'
        result = extract_json_from_markdown(text)
        self.assertEqual(result["outer"]["inner"], [1, 2, 3])


# ── Per-Agent Model Config ───────────────────────────────────────────────


class GetModelForAgentTests(unittest.TestCase):
    """Tests for AgentSettings.get_model_for_agent()."""

    def _settings(self, **overrides):
        return AgentSettings(
            project_endpoint="https://example.test",
            **overrides,
        )

    def test_returns_per_agent_model(self):
        s = self._settings(model_dax_measures="gpt-5.4")
        result = s.get_model_for_agent("tmdl_measures_generator_agent")
        self.assertEqual(result, "gpt-5.4")

    def test_returns_default_for_unknown_agent(self):
        s = self._settings(default_model="gpt-4.1")
        result = s.get_model_for_agent("unknown_agent")
        self.assertEqual(result, "gpt-4.1")

    def test_returns_per_agent_field_over_default(self):
        """Per-agent field takes precedence over default_model."""
        s = self._settings(
            default_model="gpt-4.1",
            model_functional_doc="gpt-4.1-mini",
        )
        result = s.get_model_for_agent("tableau_functional_doc_agent")
        self.assertEqual(result, "gpt-4.1-mini")

    def test_env_var_overrides_per_agent_field(self):
        """Environment variable takes highest precedence."""
        s = self._settings(model_dax_measures="gpt-4.1")
        env_key = "MODEL_DAX_MEASURES"
        original = os.environ.get(env_key)
        try:
            os.environ[env_key] = "o3-from-env"
            result = s.get_model_for_agent("tmdl_measures_generator_agent")
            self.assertEqual(result, "o3-from-env")
        finally:
            if original is None:
                os.environ.pop(env_key, None)
            else:
                os.environ[env_key] = original

    def test_all_tier_a_agents_resolve(self):
        s = self._settings()
        tier_a = [
            ("pbip_semantic_model_generator_agent", "model_semantic_model"),
            ("tmdl_measures_generator_agent", "model_dax_measures"),
            ("pbir_report_generator_agent", "model_report_visuals"),
            ("target_technical_doc_agent", "model_target_technical_doc"),
        ]
        for skill_name, field in tier_a:
            result = s.get_model_for_agent(skill_name)
            expected = getattr(s, field)
            self.assertEqual(
                result,
                expected,
                f"{skill_name} → {result}, expected {expected}",
            )

    def test_all_tier_bc_agents_resolve(self):
        s = self._settings()
        tier_bc = [
            ("report_skeleton_agent", "model_report_skeleton"),
            ("report_page_visuals_agent", "model_report_page_visuals"),
            ("tableau_functional_doc_agent", "model_functional_doc"),
            ("warnings_reviewer_agent", "model_warnings_reviewer"),
        ]
        for skill_name, field in tier_bc:
            result = s.get_model_for_agent(skill_name)
            expected = getattr(s, field)
            self.assertEqual(
                result,
                expected,
                f"{skill_name} → {result}, expected {expected}",
            )

    def test_ideal_model_defaults(self):
        """Verify the ideal model map defaults shipped in config."""
        s = self._settings()
        # Tier A — frontier models
        self.assertEqual(s.model_semantic_model, "gpt-5.4")
        self.assertEqual(s.model_dax_measures, "gpt-5.4")
        self.assertEqual(s.model_report_visuals, "gpt-5.4")
        self.assertEqual(s.model_target_technical_doc, "gpt-5.4")
        # Tier B/C — fast models
        self.assertEqual(s.model_report_skeleton, "gpt-4.1-mini")
        self.assertEqual(s.model_report_page_visuals, "gpt-4.1-mini")
        self.assertEqual(s.model_functional_doc, "gpt-4.1-mini")
        self.assertEqual(s.model_warnings_reviewer, "gpt-4.1-mini")


class GetBackendForModelTests(unittest.TestCase):
    """Tests for AgentSettings.get_backend_for_model()."""

    def _settings(self, **overrides):
        return AgentSettings(
            project_endpoint="https://example.test",
            **overrides,
        )

    def test_openai_model_returns_responses(self):
        s = self._settings()
        self.assertEqual(s.get_backend_for_model("gpt-4.1"), "responses")

    def test_unknown_model_maps_to_responses_backend(self):
        """Unknown models default to OpenAI responses backend."""
        s = self._settings()
        self.assertEqual(
            s.get_backend_for_model("some-unknown-model"),
            "responses",
        )

    def test_unknown_model_defaults_to_responses(self):
        s = self._settings()
        self.assertEqual(
            s.get_backend_for_model("some-custom-deploy"),
            "responses",
        )

    def test_custom_mapping_overrides_default(self):
        s = self._settings(
            model_backends={"my-deploy": "responses"},
        )
        self.assertEqual(
            s.get_backend_for_model("my-deploy"),
            "responses",
        )


class GetAgentSettingsEnvVarTests(unittest.TestCase):
    """Tests for environment-variable overrides in get_agent_settings()."""

    def _set_env(self, key, value):
        """Helper to set an env var and return the original for restore."""
        original = os.environ.get(key)
        if value is not None:
            os.environ[key] = value
        elif original is not None:
            del os.environ[key]
        return original

    def _restore_env(self, key, original):
        if original is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = original

    def test_page_generation_workers_env(self):
        orig = self._set_env("PAGE_GENERATION_WORKERS", "8")
        try:
            s = get_agent_settings()
            self.assertEqual(s.page_generation_workers, 8)
        finally:
            self._restore_env("PAGE_GENERATION_WORKERS", orig)

    def test_page_launch_stagger_env(self):
        orig = self._set_env("PAGE_LAUNCH_STAGGER_SECONDS", "2.5")
        try:
            s = get_agent_settings()
            self.assertEqual(s.page_launch_stagger_seconds, 2.5)
        finally:
            self._restore_env("PAGE_LAUNCH_STAGGER_SECONDS", orig)

    def test_max_concurrent_llm_calls_env(self):
        orig = self._set_env("MAX_CONCURRENT_LLM_CALLS", "20")
        try:
            s = get_agent_settings()
            self.assertEqual(s.max_concurrent_llm_calls, 20)
        finally:
            self._restore_env("MAX_CONCURRENT_LLM_CALLS", orig)

    def test_functional_doc_input_threshold_kb_env(self):
        orig = self._set_env("FUNCTIONAL_DOC_INPUT_THRESHOLD_KB", "250")
        try:
            s = get_agent_settings()
            self.assertEqual(s.functional_doc_input_threshold_kb, 250)
        finally:
            self._restore_env("FUNCTIONAL_DOC_INPUT_THRESHOLD_KB", orig)


# ── setup_logging ─────────────────────────────────────────────────────────


class SetupLoggingTests(unittest.TestCase):
    """Tests for setup_logging() — log format and idempotent handler setup."""

    def setUp(self):
        # Clear any handlers from previous tests
        pkg_logger = logging.getLogger("Tableau2PowerBI")
        pkg_logger.handlers.clear()

    def test_setup_logging_adds_handler(self):
        setup_logging()
        pkg_logger = logging.getLogger("Tableau2PowerBI")
        self.assertEqual(len(pkg_logger.handlers), 1)

    def test_setup_logging_idempotent(self):
        setup_logging()
        setup_logging()  # second call should not add another handler
        pkg_logger = logging.getLogger("Tableau2PowerBI")
        self.assertEqual(len(pkg_logger.handlers), 1)

    def test_setup_logging_silences_noisy_loggers(self):
        setup_logging()
        noisy = logging.getLogger("azure.core.pipeline.policies.http_logging_policy")
        self.assertEqual(noisy.level, logging.WARNING)

    def tearDown(self):
        pkg_logger = logging.getLogger("Tableau2PowerBI")
        pkg_logger.handlers.clear()


# ── shorten_abs_paths ─────────────────────────────────────────────────────


class ShortenAbsPathsTests(unittest.TestCase):
    def test_windows_path_shortened(self):
        text = r"Saved: C:\Users\me\project\data\out\file.tmdl"
        result = shorten_abs_paths(text)
        self.assertIn("data/out/file.tmdl", result)
        self.assertNotIn("C:\\", result)

    def test_short_path_unchanged(self):
        text = "Nothing to shorten here"
        self.assertEqual(shorten_abs_paths(text), text)


# ── recover_malformed_json ────────────────────────────────────────────────


class RecoverMalformedJsonTests(unittest.TestCase):
    def test_valid_json_returned(self):
        result = recover_malformed_json('{"key": "value"}')
        self.assertEqual(result, {"key": "value"})

    def test_invalid_escape_doubled(self):
        # \S is not a valid JSON escape — should be doubled
        raw = '{"path": "C:\\\\Some\\\\Path"}'
        result = recover_malformed_json(raw)
        self.assertIsNotNone(result)
        self.assertIn("path", result)

    def test_literal_newline_in_string_escaped(self):
        raw = '{"msg": "line1\nline2"}'
        result = recover_malformed_json(raw)
        self.assertIsNotNone(result)
        self.assertEqual(result["msg"], "line1\nline2")

    def test_literal_tab_in_string_escaped(self):
        raw = '{"msg": "col1\tcol2"}'
        result = recover_malformed_json(raw)
        self.assertIsNotNone(result)
        self.assertIn("col1\tcol2", result["msg"])

    def test_unicode_escape_passes_through(self):
        raw = '{"sym": "\\u0041"}'
        result = recover_malformed_json(raw)
        self.assertIsNotNone(result)
        self.assertEqual(result["sym"], "A")

    def test_trailing_backslash_is_unrecoverable(self):
        raw = '{"val": "end\\'
        # Trailing lone backslash breaks string delimiter — unrecoverable
        result = recover_malformed_json(raw + '"}')
        self.assertIsNone(result)

    def test_non_dict_returns_none(self):
        result = recover_malformed_json("[1, 2, 3]")
        self.assertIsNone(result)

    def test_unrecoverable_returns_none(self):
        result = recover_malformed_json("totally not json {{{}}}}")
        self.assertIsNone(result)
