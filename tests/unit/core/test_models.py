"""Tests for core.models — shared Pydantic models."""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from Tableau2PowerBI.core.models import MigrationWarning


class MigrationWarningTests(unittest.TestCase):
    """Tests for the MigrationWarning model."""

    def test_valid_construction(self):
        w = MigrationWarning(
            severity="WARN",
            code="W001",
            message="Test warning",
            timestamp="2026-01-01T00:00:00Z",
        )
        self.assertEqual(w.severity, "WARN")
        self.assertEqual(w.code, "W001")
        self.assertEqual(w.message, "Test warning")
        self.assertEqual(w.timestamp, "2026-01-01T00:00:00Z")

    def test_model_dump_round_trip(self):
        w = MigrationWarning(
            severity="ERROR",
            code="E001",
            message="Critical issue",
            timestamp="2026-04-13T12:00:00Z",
        )
        data = w.model_dump()
        restored = MigrationWarning.model_validate(data)
        self.assertEqual(restored, w)

    def test_missing_required_field_raises(self):
        with self.assertRaises(ValidationError):
            MigrationWarning(severity="WARN", code="W1", message="m")  # noqa: missing timestamp

    def test_extra_fields_ignored_by_default(self):
        # Pydantic v2 default: extra fields are ignored (not forbidden)
        w = MigrationWarning(
            severity="INFO",
            code="I001",
            message="note",
            timestamp="2026-01-01T00:00:00Z",
            extra_field="should be ignored",
        )
        self.assertFalse(hasattr(w, "extra_field"))

    def test_json_serialisation(self):
        w = MigrationWarning(
            severity="WARN",
            code="W002",
            message="minor issue",
            timestamp="2026-06-01T00:00:00Z",
        )
        json_str = w.model_dump_json()
        self.assertIn('"severity"', json_str)
        self.assertIn('"W002"', json_str)
