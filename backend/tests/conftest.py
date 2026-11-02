import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.providers.chat import LangChainChatProvider, OpenAICompatibleChatProvider


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


async def _fake_stream_answer(
    self, question: str, context: list, history: list
):
    """Deterministic fake streaming for tests — never hits a real API."""
    if context:
        content = context[0].content.strip()
        answer = f"根据已发布的知识库：{content} [1]"
    else:
        answer = "抱歉，知识库中没有相关信息。"
    chunk_size = 14
    for i in range(0, len(answer), chunk_size):
        yield answer[i : i + chunk_size]


@pytest.fixture(autouse=True)
def configure_test_provider(monkeypatch) -> None:
    """Keep every test offline and deterministic.

    Chat still runs the full retrieval → provider → SSE → persistence chain, but
    embeddings use the hash fallback, MultiQuery and agent LLM planning are
    disabled, and graph checkpoints stay in memory.
    """
    monkeypatch.setattr(settings, "llm_provider", "auto")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
    monkeypatch.setattr(settings, "openrouter_model", "openrouter/free")
    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    monkeypatch.setattr(settings, "embedding_backend", "hash")
    monkeypatch.setattr(settings, "rag_multi_query_enabled", False)
    monkeypatch.setattr(settings, "agent_use_llm", False)
    monkeypatch.setattr(settings, "agent_checkpoint_backend", "memory")
    monkeypatch.setattr(LangChainChatProvider, "stream_answer", _fake_stream_answer)
    monkeypatch.setattr(
        OpenAICompatibleChatProvider, "stream_answer", _fake_stream_answer
    )
