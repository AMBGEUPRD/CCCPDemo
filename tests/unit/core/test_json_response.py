"""Tests for shared LLM JSON response parsing helpers."""

import logging
import unittest

from Tableau2PowerBI.core.json_response import parse_llm_json_object


class JsonResponseTests(unittest.TestCase):
    def test_parses_valid_json_object(self):
        raw = '{"k": "v"}'
        parsed = parse_llm_json_object(raw)
        self.assertEqual(parsed, {"k": "v"})

    def test_rejects_non_object_json(self):
        with self.assertRaises(ValueError):
            parse_llm_json_object('["a"]')

    def test_recovery_enabled_parses_malformed_escape(self):
        logger = logging.getLogger("test.json_response")
        malformed = '{"a": "bad\\q"}'
        parsed = parse_llm_json_object(malformed, logger=logger, enable_recovery=True)
        self.assertEqual(parsed["a"], "bad\\q")

    def test_recovery_disabled_raises(self):
        with self.assertRaises(ValueError):
            parse_llm_json_object('{"a": "bad\\q"}', enable_recovery=False)
