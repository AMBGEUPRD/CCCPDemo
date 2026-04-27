"""Tests for the ModelBackend implementations.

Tests cover MockBackend, ResponsesBackend (with faked SDK), and
ChatCompletionsBackend (with faked SDK), plus the create_backend factory.
"""

import asyncio
import logging
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from Tableau2PowerBI.core.backends import (
    LLMResponse,
    MockBackend,
    ResponsesBackend,
    create_backend,
    shared_client_cache,
)
from Tableau2PowerBI.core.config import AgentSettings

# ── Helpers ──────────────────────────────────────────────────────────────


def _settings(**overrides) -> AgentSettings:
    return AgentSettings(
        project_endpoint="https://example.test",
        **overrides,
    )


_LOGGER = logging.getLogger("test")


# ── MockBackend Tests ────────────────────────────────────────────────────


class MockBackendTests(unittest.TestCase):
    def test_single_response_returned_on_every_call(self):
        backend = MockBackend(responses="hello")
        backend.initialize(_settings(), "m", "skill", "agent", _LOGGER)

        r1 = backend.call("q1")
        r2 = backend.call("q2")

        self.assertEqual(r1.text, "hello")
        self.assertEqual(r2.text, "hello")

    def test_list_responses_pop_in_order(self):
        backend = MockBackend(responses=["first", "second"])
        backend.initialize(_settings(), "m", "skill", "agent", _LOGGER)

        self.assertEqual(backend.call("q1").text, "first")
        self.assertEqual(backend.call("q2").text, "second")

    def test_list_responses_exhausted_raises(self):
        backend = MockBackend(responses=["only"])
        backend.initialize(_settings(), "m", "skill", "agent", _LOGGER)

        backend.call("q1")
        with self.assertRaises(RuntimeError):
            backend.call("q2")

    def test_prompts_are_recorded(self):
        backend = MockBackend(responses="ok")
        backend.initialize(_settings(), "m", "skill", "agent", _LOGGER)

        backend.call("prompt-1")
        backend.call("prompt-2")

        self.assertEqual(backend.calls, ["prompt-1", "prompt-2"])

    def test_initialize_is_noop(self):
        backend = MockBackend()
        backend.initialize(_settings(), "m", "skill", "agent", _LOGGER)
        self.assertTrue(backend.initialized)
        self.assertEqual(backend.model, "m")
        self.assertEqual(backend.agent_name, "agent")

    def test_close_marks_closed(self):
        backend = MockBackend()
        backend.close()
        self.assertTrue(backend.closed)

    def test_llm_response_has_elapsed(self):
        backend = MockBackend(responses="ok")
        backend.initialize(_settings(), "m", "skill", "agent", _LOGGER)
        result = backend.call("q")
        self.assertEqual(result.elapsed_seconds, 0.01)


# ── LLMResponse Tests ───────────────────────────────────────────────────


class LLMResponseTests(unittest.TestCase):
    def test_defaults(self):
        r = LLMResponse(text="hello")
        self.assertEqual(r.text, "hello")
        self.assertEqual(r.tokens_in, 0)
        self.assertEqual(r.tokens_out, 0)
        self.assertEqual(r.elapsed_seconds, 0.0)

    def test_fields(self):
        r = LLMResponse(text="x", tokens_in=10, tokens_out=20, elapsed_seconds=1.5)
        self.assertEqual(r.tokens_in, 10)
        self.assertEqual(r.tokens_out, 20)
        self.assertEqual(r.elapsed_seconds, 1.5)


# ── ResponsesBackend Tests (with Faked SDK) ─────────────────────────────


class FakeAgents:
    def __init__(self):
        self.calls = []

    def create_version(self, *, agent_name, definition):
        self.calls.append({"agent_name": agent_name, "definition": definition})
        return SimpleNamespace(id="agent-id", name=agent_name, version="1")


class FakeProjectClient:
    def __init__(self, openai_client=None):
        self.agents = FakeAgents()
        self._openai_client = openai_client
        self.closed = False

    def get_openai_client(self, **kwargs):
        return self._openai_client

    def close(self):
        self.closed = True


class FakeResponses:
    """Fake ``openai_client.responses`` — non-streaming create()."""

    def __init__(self, text: str = "", tokens_in: int = 5, tokens_out: int = 10):
        self._text = text
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            output_text=self._text,
            usage=SimpleNamespace(
                input_tokens=self._tokens_in,
                output_tokens=self._tokens_out,
            ),
        )


class FakeConversations:
    def __init__(self, conversation_id="conv-1"):
        self._id = conversation_id

    def create(self, **kwargs):
        return SimpleNamespace(id=self._id)


class FakeOpenAIClient:
    def __init__(
        self,
        text: str = "",
        tokens_in: int = 5,
        tokens_out: int = 10,
        conversation_id: str = "conv-1",
    ):
        self.responses = FakeResponses(text=text, tokens_in=tokens_in, tokens_out=tokens_out)
        self.conversations = FakeConversations(conversation_id)
        self.closed = False

    def close(self):
        self.closed = True


class ResponsesBackendTests(unittest.TestCase):
    def _make_backend(self, text="response text", tokens_in=5, tokens_out=10):
        """Create a ResponsesBackend with a faked SDK client."""
        openai_client = FakeOpenAIClient(
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
        project_client = FakeProjectClient(openai_client=openai_client)

        backend = ResponsesBackend(use_shared_clients=False)
        import Tableau2PowerBI.core.backends.responses_backend as responses_backend_mod

        original = responses_backend_mod._create_project_client
        responses_backend_mod._create_project_client = lambda settings: project_client

        # Provide a fake PromptAgentDefinition so tests run without azure SDK
        fake_models = SimpleNamespace(PromptAgentDefinition=lambda **kw: SimpleNamespace(**kw))
        with patch.dict(sys.modules, {"azure.ai.projects.models": fake_models}):
            backend.initialize(_settings(), "test-model", "test skill", "test-agent", _LOGGER)

        responses_backend_mod._create_project_client = original
        return backend, openai_client, project_client

    def test_initialize_registers_agent(self):
        backend, _, project_client = self._make_backend()
        self.assertEqual(len(project_client.agents.calls), 1)
        self.assertEqual(project_client.agents.calls[0]["agent_name"], "test-agent")

    def test_initialize_is_idempotent(self):
        backend, _, project_client = self._make_backend()
        # Second initialize should be no-op
        backend.initialize(_settings(), "test-model", "skill", "agent", _LOGGER)
        self.assertEqual(len(project_client.agents.calls), 1)

    def test_call_returns_llm_response(self):
        backend, openai_client, _ = self._make_backend()
        result = backend.call("hello")

        self.assertEqual(result.text, "response text")
        self.assertEqual(result.tokens_out, 10)
        self.assertEqual(result.tokens_in, 5)
        self.assertGreater(result.elapsed_seconds, 0)

    def test_call_sends_correct_request_shape(self):
        backend, openai_client, _ = self._make_backend()
        backend.call("test prompt")

        call = openai_client.responses.calls[0]
        self.assertEqual(call["model"], "test-model")
        self.assertEqual(call["input"], "test prompt")
        self.assertIn("conversation", call)
        self.assertIn("agent_reference", call["extra_body"])

    def test_call_raises_on_empty_response(self):
        backend, _, _ = self._make_backend(text="")
        with self.assertRaises(ValueError):
            backend.call("hello")

    def test_close_closes_clients(self):
        backend, openai_client, project_client = self._make_backend()
        backend.close()
        self.assertTrue(openai_client.closed)
        self.assertTrue(project_client.closed)


# ── ChatCompletionsBackend Tests (with Faked SDK) ────────────────────────


# Fake classes removed (Claude backend removed)# ChatCompletionsBackendTests removed (Claude backend removed)


# ── create_backend Factory Tests ─────────────────────────────────────────


class CreateBackendTests(unittest.TestCase):
    def test_responses_returns_responses_backend(self):
        backend = create_backend("responses")
        self.assertIsInstance(backend, ResponsesBackend)

    def test_mock_returns_mock_backend(self):
        backend = create_backend("mock")
        self.assertIsInstance(backend, MockBackend)

    def test_mock_with_kwargs(self):
        backend = create_backend("mock", responses="custom")
        self.assertIsInstance(backend, MockBackend)
        backend.initialize(_settings(), "m", "s", "a", _LOGGER)
        self.assertEqual(backend.call("q").text, "custom")

    def test_unknown_type_raises(self):
        with self.assertRaises(ValueError) as ctx:
            create_backend("nonexistent")
        self.assertIn("nonexistent", str(ctx.exception))


# ── Async Tests ──────────────────────────────────────────────────────────


class MockBackendAsyncTests(unittest.TestCase):
    """Test call_async on MockBackend (delegates to sync call)."""

    def test_call_async_returns_response(self):
        backend = MockBackend(responses="async result")
        backend.initialize(_settings(), "m", "skill", "agent", _LOGGER)
        result = asyncio.run(backend.call_async("hello"))
        self.assertEqual(result.text, "async result")

    def test_call_async_records_prompt(self):
        backend = MockBackend(responses="ok")
        backend.initialize(_settings(), "m", "skill", "agent", _LOGGER)
        asyncio.run(backend.call_async("my prompt"))
        self.assertEqual(backend.calls, ["my prompt"])


class FakeAsyncResponses:
    """Fake async ``openai_client.responses`` — non-streaming create()."""

    def __init__(self, text: str = "", tokens_in: int = 5, tokens_out: int = 10):
        self._text = text
        self._tokens_in = tokens_in
        self._tokens_out = tokens_out
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            output_text=self._text,
            usage=SimpleNamespace(
                input_tokens=self._tokens_in,
                output_tokens=self._tokens_out,
            ),
        )


class FakeAsyncConversations:
    def __init__(self, conversation_id="conv-async-1"):
        self._id = conversation_id

    def create(self, **kwargs):
        return SimpleNamespace(id=self._id)


class FakeAsyncOpenAIClient:
    def __init__(
        self,
        text: str = "",
        tokens_in: int = 5,
        tokens_out: int = 10,
    ):
        self.responses = FakeAsyncResponses(
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
        self.conversations = FakeAsyncConversations()
        self.closed = False

    def close(self):
        self.closed = True


class FakeAsyncProjectClient:
    def __init__(self, openai_client=None):
        self._openai_client = openai_client
        self.closed = False

    def get_openai_client(self, **kwargs):
        return self._openai_client

    def close(self):
        self.closed = True


class ResponsesBackendAsyncTests(unittest.TestCase):
    """Test call_async on ResponsesBackend with faked async SDK."""

    def _make_backend(self, text="async response", tokens_in=5, tokens_out=10):
        """Create a ResponsesBackend with sync init + async client cache."""
        # Sync init for agent registration
        sync_openai = FakeOpenAIClient(text=text, tokens_in=tokens_in, tokens_out=tokens_out)
        sync_project = FakeProjectClient(openai_client=sync_openai)

        backend = ResponsesBackend(use_shared_clients=False)
        import Tableau2PowerBI.core.backends.responses_backend as responses_backend_mod

        original = responses_backend_mod._create_project_client
        responses_backend_mod._create_project_client = lambda s: sync_project

        # Provide a fake PromptAgentDefinition so tests run without azure SDK
        fake_models = SimpleNamespace(PromptAgentDefinition=lambda **kw: SimpleNamespace(**kw))
        with patch.dict(sys.modules, {"azure.ai.projects.models": fake_models}):
            backend.initialize(_settings(), "test-model", "test skill", "test-agent", _LOGGER)
        responses_backend_mod._create_project_client = original

        # Prepare async fakes in the shared cache
        import Tableau2PowerBI.core.backends.shared_clients as shared_clients_mod

        async_openai = FakeAsyncOpenAIClient(
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
        )
        async_project = FakeAsyncProjectClient(openai_client=async_openai)

        original_async = shared_clients_mod.create_async_project_client
        shared_clients_mod.create_async_project_client = lambda s: async_project

        return backend, async_openai, shared_clients_mod, original_async

    def _cleanup(self, shared_clients_mod, original_async):
        shared_clients_mod.create_async_project_client = original_async
        # Clear async entries from the shared cache
        with shared_client_cache._lock:
            async_keys = [k for k in shared_client_cache._entries if k.startswith("async:")]
            for k in async_keys:
                del shared_client_cache._entries[k]

    def test_call_async_returns_llm_response(self):
        backend, async_openai, mod, orig = self._make_backend()
        try:
            result = asyncio.run(backend.call_async("hello"))
            self.assertEqual(result.text, "async response")
            self.assertEqual(result.tokens_in, 5)
            self.assertEqual(result.tokens_out, 10)
            self.assertGreater(result.elapsed_seconds, 0)
        finally:
            self._cleanup(mod, orig)

    def test_call_async_raises_on_empty_response(self):
        backend, _, mod, orig = self._make_backend(text="")
        try:
            with self.assertRaises(ValueError):
                asyncio.run(backend.call_async("hello"))
        finally:
            self._cleanup(mod, orig)


class FakeAsyncChatChunkIterator:
    """Deprecated: Removed with ChatCompletionsBackend."""


class ChatCompletionsBackendAsyncTests(unittest.TestCase):
    """Removed: ChatCompletionsBackend for Claude models."""


# ── ClientCache Tests ────────────────────────────────────────────────────


class ClientCacheTests(unittest.TestCase):
    """Tests for the shared ClientCache in shared_clients.py."""

    def test_get_or_create_returns_same_pair(self):
        import Tableau2PowerBI.core.backends.shared_clients as sc_mod
        from Tableau2PowerBI.core.backends.shared_clients import ClientCache

        cache = ClientCache()
        fake_project = SimpleNamespace(
            close=lambda: None,
            get_openai_client=lambda **kw: SimpleNamespace(close=lambda: None),
        )
        orig = sc_mod.create_project_client
        sc_mod.create_project_client = lambda s: fake_project
        try:
            settings = _settings()
            pair1 = cache.get_or_create(settings)
            pair2 = cache.get_or_create(settings)
            self.assertIs(pair1[0], pair2[0])
        finally:
            sc_mod.create_project_client = orig

    def test_get_or_create_async_returns_same_pair(self):
        import Tableau2PowerBI.core.backends.shared_clients as sc_mod
        from Tableau2PowerBI.core.backends.shared_clients import ClientCache

        cache = ClientCache()
        fake_project = SimpleNamespace(
            close=lambda: None,
            get_openai_client=lambda **kw: SimpleNamespace(close=lambda: None),
        )
        orig = sc_mod.create_async_project_client
        sc_mod.create_async_project_client = lambda s: fake_project
        try:
            settings = _settings()

            async def _get():
                return await cache.get_or_create_async(settings)

            pair1 = asyncio.run(_get())
            pair2 = asyncio.run(_get())
            self.assertIs(pair1[0], pair2[0])
        finally:
            sc_mod.create_async_project_client = orig

    def test_close_all_clears_entries(self):
        from Tableau2PowerBI.core.backends.shared_clients import ClientCache

        cache = ClientCache()
        closed = []
        fake_client = SimpleNamespace(close=lambda: closed.append(True))
        cache._entries["key1"] = (fake_client, fake_client)
        cache.close_all()
        self.assertEqual(len(cache._entries), 0)
        self.assertGreater(len(closed), 0)

    def test_close_all_async_clears_async_entries(self):
        from Tableau2PowerBI.core.backends.shared_clients import ClientCache

        cache = ClientCache()
        closed = []
        fake_client = SimpleNamespace(close=lambda: closed.append(True))
        cache._entries["async:key1"] = (fake_client, fake_client)
        cache._entries["sync_key"] = (fake_client, fake_client)
        asyncio.run(cache.close_all_async())
        # Only async keys are removed
        self.assertNotIn("async:key1", cache._entries)
        self.assertIn("sync_key", cache._entries)
