"""Tests for webapp.runtime — in-memory result store, SSE helpers, log handler."""

from __future__ import annotations

import json
import logging
import queue
import time
import unittest

from Tableau2PowerBI.webapp.runtime import (
    RESULT_TTL_SECONDS,
    _format_pipeline_result_for_display,
    _drain_log_queue,
    _evict_expired,
    _iso_now,
    _result_store,
    _sse_event,
    _SSELogHandler,
    store_result,
)


class SSEEventTests(unittest.TestCase):
    """Tests for _sse_event formatting."""

    def test_basic_data_only(self):
        result = _sse_event({"step": 1})
        self.assertTrue(result.startswith("data: "))
        self.assertTrue(result.endswith("\n\n"))
        payload = json.loads(result.split("data: ")[1].strip())
        self.assertEqual(payload["step"], 1)

    def test_with_event_name(self):
        result = _sse_event({"msg": "hi"}, event="update")
        self.assertIn("event: update\n", result)
        self.assertIn("data: ", result)

    def test_non_ascii_preserved(self):
        result = _sse_event({"name": "Supermercato"})
        self.assertIn("Supermercato", result)


class StoreResultTests(unittest.TestCase):
    """Tests for store_result and _evict_expired."""

    def setUp(self):
        _result_store.clear()

    def tearDown(self):
        _result_store.clear()

    def test_store_and_retrieve(self):
        store_result("id1", '{"ok": true}')
        self.assertIn("id1", _result_store)
        _, payload = _result_store["id1"]
        self.assertEqual(payload, '{"ok": true}')

    def test_evict_removes_expired_entries(self):
        # Insert an entry with a timestamp in the past
        _result_store["old"] = (time.time() - RESULT_TTL_SECONDS - 10, "expired")
        _result_store["new"] = (time.time(), "fresh")
        _evict_expired()
        self.assertNotIn("old", _result_store)
        self.assertIn("new", _result_store)

    def test_store_evicts_oldest_when_at_capacity(self):
        # Fill to capacity with entries at different timestamps
        for i in range(200):
            _result_store[f"item-{i}"] = (time.time() + i * 0.001, f"payload-{i}")
        self.assertEqual(len(_result_store), 200)

        # Adding one more should evict the oldest
        store_result("overflow", "new")
        self.assertIn("overflow", _result_store)
        self.assertEqual(len(_result_store), 200)


class SSELogHandlerTests(unittest.TestCase):
    """Tests for _SSELogHandler."""

    def test_regular_log_emits_log_type(self):
        q: queue.Queue = queue.Queue(maxsize=100)
        handler = _SSELogHandler(q)
        record = logging.LogRecord(
            "test.logger",
            logging.INFO,
            "",
            0,
            "hello",
            (),
            None,
        )
        handler.emit(record)
        item = q.get_nowait()
        self.assertEqual(item["type"], "log")
        self.assertEqual(item["level"], "INFO")
        self.assertIn("hello", item["message"])

    def test_sub_agent_emits_sub_agent_type(self):
        q: queue.Queue = queue.Queue(maxsize=100)
        handler = _SSELogHandler(q)
        record = logging.LogRecord(
            "test.logger",
            logging.INFO,
            "",
            0,
            "visual done",
            (),
            None,
        )
        record.sub_agent = {"page_id": "abc123", "status": "done"}
        handler.emit(record)
        item = q.get_nowait()
        self.assertEqual(item["type"], "sub_agent")
        self.assertEqual(item["page_id"], "abc123")

    def test_full_queue_does_not_raise(self):
        q: queue.Queue = queue.Queue(maxsize=1)
        handler = _SSELogHandler(q)
        record = logging.LogRecord(
            "test.logger",
            logging.INFO,
            "",
            0,
            "msg1",
            (),
            None,
        )
        handler.emit(record)
        # Queue is now full — second emit should not raise
        record2 = logging.LogRecord(
            "test.logger",
            logging.INFO,
            "",
            0,
            "msg2",
            (),
            None,
        )
        handler.emit(record2)  # silently dropped
        self.assertEqual(q.qsize(), 1)


class DrainLogQueueTests(unittest.TestCase):
    """Tests for _drain_log_queue."""

    def test_returns_sse_events_and_empties_queue(self):
        q: queue.Queue = queue.Queue()
        q.put({"type": "log", "level": "INFO", "message": "hi"})
        q.put({"type": "log", "level": "WARNING", "message": "warn"})
        events = _drain_log_queue(q)
        self.assertEqual(len(events), 2)
        self.assertTrue(q.empty())
        for event in events:
            self.assertIn("data: ", event)

    def test_empty_queue_returns_empty_list(self):
        q: queue.Queue = queue.Queue()
        events = _drain_log_queue(q)
        self.assertEqual(events, [])


class CoerceTests(unittest.TestCase):
    """Tests for _format_pipeline_result_for_display — result normalisation."""

    def test_none_returns_default_message(self):
        self.assertEqual(_format_pipeline_result_for_display(None), "Analysis completed.")

    def test_string_passthrough(self):
        self.assertEqual(_format_pipeline_result_for_display("done"), "done")

    def test_dict_serialised_to_json(self):
        result = _format_pipeline_result_for_display({"k": "v"})
        self.assertEqual(json.loads(result), {"k": "v"})

    def test_other_types_converted_to_string(self):
        self.assertEqual(_format_pipeline_result_for_display(42), "42")


class IsoNowTests(unittest.TestCase):
    """Tests for _iso_now — UTC timestamp helper."""

    def test_returns_iso_string(self):
        result = _iso_now()
        self.assertIn("T", result)
        self.assertTrue(result.endswith("+00:00"))
