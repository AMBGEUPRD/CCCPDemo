"""Tests for core/token_tracker.py — pipeline-wide token usage tracking."""

import threading
import unittest

from Tableau2PowerBI.core.token_tracker import TokenTracker


class TokenTrackerTests(unittest.TestCase):
    """Verify TokenTracker accumulates and reports correctly."""

    def setUp(self):
        self.tracker = TokenTracker()

    def test_empty_tracker(self):
        self.assertEqual(self.tracker.total_tokens_in(), 0)
        self.assertEqual(self.tracker.total_tokens_out(), 0)
        self.assertEqual(self.tracker.summary(), {})

    def test_single_record(self):
        self.tracker.record("agent_a", tokens_in=100, tokens_out=50)
        self.assertEqual(self.tracker.total_tokens_in(), 100)
        self.assertEqual(self.tracker.total_tokens_out(), 50)

    def test_multiple_records_same_agent(self):
        self.tracker.record("agent_a", tokens_in=100, tokens_out=50)
        self.tracker.record("agent_a", tokens_in=200, tokens_out=80)
        summary = self.tracker.summary()
        self.assertEqual(summary["agent_a"]["calls"], 2)
        self.assertEqual(summary["agent_a"]["tokens_in"], 300)
        self.assertEqual(summary["agent_a"]["tokens_out"], 130)

    def test_multiple_agents(self):
        self.tracker.record("agent_a", tokens_in=100, tokens_out=50)
        self.tracker.record("agent_b", tokens_in=200, tokens_out=80)
        self.assertEqual(self.tracker.total_tokens_in(), 300)
        self.assertEqual(self.tracker.total_tokens_out(), 130)
        self.assertIn("agent_a", self.tracker.summary())
        self.assertIn("agent_b", self.tracker.summary())

    def test_reset_clears_data(self):
        self.tracker.record("agent_a", tokens_in=100, tokens_out=50)
        self.tracker.reset()
        self.assertEqual(self.tracker.total_tokens_in(), 0)
        self.assertEqual(self.tracker.summary(), {})

    def test_thread_safety(self):
        """Multiple threads recording concurrently should not lose data."""
        barrier = threading.Barrier(4)

        def _worker(name: str, count: int):
            barrier.wait()
            for _ in range(count):
                self.tracker.record(name, tokens_in=1, tokens_out=1)

        threads = [threading.Thread(target=_worker, args=(f"agent_{i}", 100)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(self.tracker.total_tokens_in(), 400)
        self.assertEqual(self.tracker.total_tokens_out(), 400)

    def test_summary_sorted_by_name(self):
        self.tracker.record("z_agent", tokens_in=1, tokens_out=1)
        self.tracker.record("a_agent", tokens_in=1, tokens_out=1)
        keys = list(self.tracker.summary().keys())
        self.assertEqual(keys, ["a_agent", "z_agent"])

    def test_log_summary_no_error(self):
        """log_summary should not raise even when empty."""
        self.tracker.log_summary()
        self.tracker.record("agent_a", tokens_in=100, tokens_out=50)
        self.tracker.log_summary()
