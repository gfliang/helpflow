import json
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.config import settings
from app.db.session import SessionLocal
from app.main import app
from app.models import (
    Conversation,
    KnowledgeChunk,
    KnowledgeDocument,
    Membership,
    Message,
    User,
    Workspace,
)
from app.providers.chat import (
    LangChainChatProvider,
    ProviderError,
    build_chat_provider,
)
from app.services.moderation import contains_sensitive_word, is_handoff_request
from app.services.passwords import hash_password
from app.services.tokens import create_access_token


@dataclass(frozen=True)
class PublicWorkspace:
    workspace_id: uuid.UUID
    slug: str
    headers: dict[str, str]


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def workspace_factory() -> Iterator[Callable[[], PublicWorkspace]]:
    created: list[tuple[uuid.UUID, uuid.UUID]] = []

    def make() -> PublicWorkspace:
        suffix = uuid.uuid4().hex[:10]
        with SessionLocal() as db:
            user = User(
                email=f"chat-{suffix}@helpflow.test",
                name="Chat Test User",
                password_hash=hash_password("test-password"),
            )
            workspace = Workspace(name="Chat Test", slug=f"chat-{suffix}")
            db.add_all([user, workspace])
            db.flush()
            db.add(Membership(user_id=user.id, workspace_id=workspace.id, role="admin"))
            db.commit()
            token, _ = create_access_token(user_id=user.id, workspace_id=workspace.id, role="admin")
            created.append((workspace.id, user.id))
            return PublicWorkspace(
                workspace_id=workspace.id,
                slug=workspace.slug,
                headers={"Authorization": f"Bearer {token}"},
            )

    yield make

    with SessionLocal() as db:
        for workspace_id, user_id in created:
            conversation_ids = db.scalars(
                select(Conversation.id).where(Conversation.workspace_id == workspace_id)
            ).all()
            if conversation_ids:
                db.execute(delete(Message).where(Message.conversation_id.in_(conversation_ids)))
                db.execute(delete(Conversation).where(Conversation.id.in_(conversation_ids)))
            db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.workspace_id == workspace_id))
            db.execute(
                delete(KnowledgeDocument).where(KnowledgeDocument.workspace_id == workspace_id)
            )
            db.execute(delete(Membership).where(Membership.workspace_id == workspace_id))
            db.execute(delete(Workspace).where(Workspace.id == workspace_id))
            db.execute(delete(User).where(User.id == user_id))
        db.commit()


def parse_sse(payload: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    for block in payload.strip().split("\n\n"):
        event = ""
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if event and data_lines:
            events.append((event, json.loads("\n".join(data_lines))))
    return events


def event_payload(events: list[tuple[str, dict]], name: str) -> dict:
    return next(payload for event, payload in events if event == name)


def publish_document(client: TestClient, workspace: PublicWorkspace, title: str, content: str) -> str:
    created = client.post(
        "/api/v1/knowledge/documents",
        headers=workspace.headers,
        json={"title": title, "content": content},
    )
    assert created.status_code == 201
    document_id = created.json()["data"]["id"]
    published = client.post(
        f"/api/v1/knowledge/documents/{document_id}/publish", headers=workspace.headers
    )
    assert published.status_code == 200
    return document_id


def test_public_workspace_config(client, workspace_factory) -> None:
    workspace = workspace_factory()
    response = client.get(f"/api/v1/public/workspaces/{workspace.slug}")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["slug"] == workspace.slug
    assert data["greeting"]
    assert len(data["preset_questions"]) == 4

    assert client.get("/api/v1/public/workspaces/does-not-exist").status_code == 404


def test_anonymous_chat_streams_answer_with_citations(
    client, workspace_factory, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "chat_confidence_threshold", 0.0)
    workspace = workspace_factory()
    document_id = publish_document(
        client,
        workspace,
        "专业版价格",
        "专业版每月 899 元，包含 3 个工作空间、10 个客服席位和每月 10,000 次 AI 回答。",
    )

    response = client.post(
        f"/api/v1/public/workspaces/{workspace.slug}/chat",
        json={"message": "专业版多少钱？", "visitor_id": "visitor-answer-1"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")

    events = parse_sse(response.text)
    meta = event_payload(events, "meta")
    assert meta["provider"] == "openrouter"
    assert meta["mode"] == "answer"
    assert meta["conversation_id"]

    answer = "".join(payload["text"] for event, payload in events if event == "delta")
    assert "899" in answer
    assert "[1]" in answer

    citations = event_payload(events, "citations")["citations"]
    assert citations[0]["document_id"] == document_id
    assert citations[0]["document_title"] == "专业版价格"

    done = event_payload(events, "done")
    assert done["refused"] is False
    assert done["handoff"] is False
    assert done["message_id"]

    with SessionLocal() as db:
        messages = db.scalars(
            select(Message).where(Message.conversation_id == uuid.UUID(meta["conversation_id"]))
        ).all()
    assert {message.role for message in messages} == {"visitor", "assistant"}


def test_low_confidence_question_is_refused_without_citations(
    client, workspace_factory, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "chat_confidence_threshold", 0.99)
    workspace = workspace_factory()
    publish_document(
        client, workspace, "退款政策", "年度订阅在首次购买后 7 天内可以申请全额退款。"
    )

    response = client.post(
        f"/api/v1/public/workspaces/{workspace.slug}/chat",
        json={"message": "火星的天气怎么样？", "visitor_id": "visitor-refusal-1"},
    )
    events = parse_sse(response.text)
    answer = "".join(payload["text"] for event, payload in events if event == "delta")

    assert "没有找到" in answer
    assert event_payload(events, "citations")["citations"] == []
    done = event_payload(events, "done")
    assert done["refused"] is True
    assert done["handoff_suggested"] is True


def test_handoff_request_moves_conversation_to_human_queue(client, workspace_factory) -> None:
    workspace = workspace_factory()
    response = client.post(
        f"/api/v1/public/workspaces/{workspace.slug}/chat",
        json={"message": "我要转人工客服", "visitor_id": "visitor-handoff-1"},
    )
    events = parse_sse(response.text)
    answer = "".join(payload["text"] for event, payload in events if event == "delta")
    meta = event_payload(events, "meta")

    assert meta["handoff"] is True
    assert "转接人工客服" in answer
    assert event_payload(events, "handoff")["status"] == "waiting_human"

    with SessionLocal() as db:
        conversation = db.get(Conversation, uuid.UUID(meta["conversation_id"]))
    assert conversation is not None
    assert conversation.status == "waiting_human"


def test_sensitive_message_is_blocked(client, workspace_factory) -> None:
    workspace = workspace_factory()
    response = client.post(
        f"/api/v1/public/workspaces/{workspace.slug}/chat",
        json={"message": "你们就是骗子", "visitor_id": "visitor-blocked-1"},
    )
    events = parse_sse(response.text)
    answer = "".join(payload["text"] for event, payload in events if event == "delta")
    done = event_payload(events, "done")

    assert "无法处理" in answer
    assert done["blocked"] is True
    assert done["handoff"] is False


def test_conversation_cannot_be_reused_by_another_visitor(client, workspace_factory) -> None:
    workspace = workspace_factory()
    first = client.post(
        f"/api/v1/public/workspaces/{workspace.slug}/chat",
        json={"message": "你好", "visitor_id": "visitor-a"},
    )
    conversation_id = event_payload(parse_sse(first.text), "meta")["conversation_id"]

    hijacked = client.post(
        f"/api/v1/public/workspaces/{workspace.slug}/chat",
        json={
            "message": "看看历史消息",
            "visitor_id": "visitor-b",
            "conversation_id": conversation_id,
        },
    )
    assert hijacked.status_code == 404

    missing_visitor = client.post(
        f"/api/v1/public/workspaces/{workspace.slug}/chat",
        json={"message": "看看历史消息", "conversation_id": conversation_id},
    )
    assert missing_visitor.status_code == 404


def test_moderation_helpers() -> None:
    assert contains_sensitive_word("你们就是骗子") is True
    assert contains_sensitive_word("请问价格是多少") is False
    assert is_handoff_request("我要转人工客服") is True
    assert is_handoff_request("年度订阅怎么退款") is False


def test_provider_factory_requires_an_api_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_provider", "auto")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "openrouter_api_key", "")

    with pytest.raises(ProviderError):
        build_chat_provider()

    monkeypatch.setattr(settings, "openrouter_api_key", "openrouter-test-key")
    provider = build_chat_provider()
    assert isinstance(provider, LangChainChatProvider)
    assert provider.name == "openrouter"
    assert provider.model == "openrouter/free"


def test_provider_factory_prefers_openrouter_when_configured(monkeypatch) -> None:
    monkeypatch.setattr(settings, "llm_provider", "auto")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "openrouter_api_key", "openrouter-test-key")
    monkeypatch.setattr(settings, "openrouter_model", "openrouter/free")

    provider = build_chat_provider()
    assert isinstance(provider, LangChainChatProvider)
    assert provider.name == "openrouter"
    assert provider.model == "openrouter/free"

    monkeypatch.setattr(settings, "llm_api_key", "test-llm-key")
    provider = build_chat_provider()
    assert provider.name == "openai"
    assert provider.model == settings.llm_model
