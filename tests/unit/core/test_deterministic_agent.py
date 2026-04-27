"""Tests for the deterministic (non-LLM) agent base class."""

import unittest

from Tableau2PowerBI.core.agent import DeterministicAgent
from Tableau2PowerBI.core.config import AgentSettings


class _StubDeterministicAgent(DeterministicAgent):
    def __init__(self, settings: AgentSettings):
        super().__init__(
            skill_name="tableau_metadata_extractor_agent",
            settings=settings,
        )


class DeterministicAgentTests(unittest.TestCase):
    def test_constructor_loads_skill_text(self):
        settings = AgentSettings(project_endpoint="https://example.test")
        agent = _StubDeterministicAgent(settings=settings)
        self.assertIn("Tableau Source Understanding", agent.skill_text)

    def test_run_raises_runtime_error(self):
        settings = AgentSettings(project_endpoint="https://example.test")
        agent = _StubDeterministicAgent(settings=settings)
        with self.assertRaises(RuntimeError):
            agent.run("hello")

    def test_run_async_raises_runtime_error(self):
        settings = AgentSettings(project_endpoint="https://example.test")
        agent = _StubDeterministicAgent(settings=settings)

        async def _call():
            await agent.run_async("hello")

        with self.assertRaises(RuntimeError):
            import asyncio

            asyncio.run(_call())

    def test_create_returns_self(self):
        settings = AgentSettings(project_endpoint="https://example.test")
        agent = _StubDeterministicAgent(settings=settings)
        result = agent.create()
        self.assertIs(result, agent)

    def test_close_is_noop(self):
        settings = AgentSettings(project_endpoint="https://example.test")
        agent = _StubDeterministicAgent(settings=settings)
        agent.close()  # should not raise

    def test_context_manager(self):
        settings = AgentSettings(project_endpoint="https://example.test")
        with _StubDeterministicAgent(settings=settings) as agent:
            self.assertIsInstance(agent, DeterministicAgent)
