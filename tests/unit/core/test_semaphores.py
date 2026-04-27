"""Tests for the shared semaphore primitives in core.agent.semaphores."""

from __future__ import annotations

import asyncio
import threading
import unittest

import Tableau2PowerBI.core.agent.semaphores as sem_module


class SyncSemaphoreTests(unittest.TestCase):
    """Tests for get_llm_semaphore."""

    def setUp(self):
        # Reset global state before each test.
        sem_module._llm_semaphore = None

    def tearDown(self):
        sem_module._llm_semaphore = None

    def test_returns_threading_semaphore(self):
        s = sem_module.get_llm_semaphore()
        self.assertIsInstance(s, threading.Semaphore)

    def test_returns_same_instance_on_repeated_calls(self):
        s1 = sem_module.get_llm_semaphore()
        s2 = sem_module.get_llm_semaphore()
        self.assertIs(s1, s2)

    def test_respects_max_calls(self):
        s = sem_module.get_llm_semaphore(max_calls=2)
        # Should be able to acquire twice without blocking
        self.assertTrue(s.acquire(blocking=False))
        self.assertTrue(s.acquire(blocking=False))
        # Third acquire should fail (non-blocking)
        self.assertFalse(s.acquire(blocking=False))
        s.release()
        s.release()


class AsyncSemaphoreTests(unittest.TestCase):
    """Tests for get_async_llm_semaphore."""

    def setUp(self):
        sem_module._async_semaphores.clear()

    def tearDown(self):
        sem_module._async_semaphores.clear()

    def test_returns_asyncio_semaphore(self):
        async def _check():
            s = sem_module.get_async_llm_semaphore()
            self.assertIsInstance(s, asyncio.Semaphore)

        asyncio.run(_check())

    def test_returns_same_instance_on_repeated_calls(self):
        async def _check():
            s1 = sem_module.get_async_llm_semaphore()
            s2 = sem_module.get_async_llm_semaphore()
            self.assertIs(s1, s2)

        asyncio.run(_check())

    def test_different_loops_get_different_semaphores(self):
        """Separate event loops each receive their own semaphore."""
        holder: list[asyncio.Semaphore] = []

        async def _capture():
            s = sem_module.get_async_llm_semaphore()
            holder.append(s)

        asyncio.run(_capture())
        asyncio.run(_capture())
        self.assertEqual(len(holder), 2)
        self.assertIsNot(holder[0], holder[1])

    def test_respects_max_calls(self):
        async def _check():
            s = sem_module.get_async_llm_semaphore(max_calls=2)
            await s.acquire()
            await s.acquire()
            # Third acquire should not be immediately available
            acquired = asyncio.create_task(s.acquire())
            await asyncio.sleep(0)  # yield to event loop
            self.assertFalse(acquired.done())
            s.release()
            await acquired  # now it should complete

        asyncio.run(_check())
