"""Tests for core/prompt_utils.py — compact_json helper."""

import json
import unittest

from Tableau2PowerBI.core.prompt_utils import compact_json


class CompactJsonTests(unittest.TestCase):
    """Verify that compact_json produces valid, minimal JSON."""

    def test_simple_dict(self):
        result = compact_json({"a": 1, "b": "hello"})
        self.assertEqual(result, '{"a":1,"b":"hello"}')

    def test_nested_structure(self):
        obj = {"tables": [{"name": "T1", "cols": ["c1", "c2"]}]}
        result = compact_json(obj)
        # No spaces, no newlines
        self.assertNotIn("\n", result)
        self.assertNotIn(" ", result)
        # Round-trips correctly
        self.assertEqual(json.loads(result), obj)

    def test_non_ascii_preserved(self):
        """Non-ASCII characters (accented, CJK) are kept verbatim."""
        obj = {"name": "Café Résumé"}
        result = compact_json(obj)
        self.assertIn("Café", result)
        self.assertIn("Résumé", result)

    def test_ensure_ascii_flag(self):
        """When ensure_ascii=True, non-ASCII is escaped."""
        obj = {"name": "Café"}
        result = compact_json(obj, ensure_ascii=True)
        self.assertNotIn("Café", result)
        self.assertIn("\\u", result)

    def test_smaller_than_indent2(self):
        """compact_json should always be shorter than indent=2 for non-trivial input."""
        obj = {
            "datasources": [
                {
                    "name": f"DS{i}",
                    "tables": [
                        {
                            "name": f"Table{j}",
                            "columns": [{"name": f"col{k}", "type": "string"} for k in range(5)],
                        }
                        for j in range(3)
                    ],
                }
                for i in range(2)
            ]
        }
        compact = compact_json(obj)
        pretty = json.dumps(obj, indent=2, ensure_ascii=False)
        self.assertLess(len(compact), len(pretty))
        # Expect at least 20% savings on this structure
        ratio = len(compact) / len(pretty)
        self.assertLess(ratio, 0.80)

    def test_empty_dict(self):
        self.assertEqual(compact_json({}), "{}")

    def test_empty_list(self):
        self.assertEqual(compact_json([]), "[]")

    def test_string_value(self):
        self.assertEqual(compact_json("hello"), '"hello"')

    def test_null_value(self):
        self.assertEqual(compact_json(None), "null")
