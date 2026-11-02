import json
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import (
    AiCallLog,
    AuditLog,
    Conversation,
    Membership,
    Message,
    Ticket,
    User,
    Workspace,
)
from app.services.audit import check_rate_limit
from app.services.passwords import hash_password
from app.services.tokens import create_access_token


@dataclass(frozen=True)
class ObsWorkspace:
    workspace_id: uuid.UUID
    slug: str
    admin_id: uuid.UUID
    agent_id: uuid.UUID
    viewer_id: uuid.UUID
    admin_headers: dict[str, str]
    agent_headers: dict[str, str]
    viewer_headers: dict[str, str]


def _headers(user_id: uuid.UUID, workspace_id: uuid.UUID, role: str) -> dict[str, str]:
    token, _ = create_access_token(user_id=user_id, workspace_id=workspace_id, role=role)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def obs_factory() -> Iterator[Callable[[], ObsWorkspace]]:
    created: list[uuid.UUID] = []

    def make() -> ObsWorkspace:
        suffix = uuid.uuid4().hex[:10]
        with SessionLocal() as db:
            workspace = Workspace(name="Obs Test", slug=f"obs-{suffix}")
            users = {
                role: User(
                    email=f"obs-{role}-{suffix}@helpflow.test",
                    name=f"{role.title()} Ops",
                    password_hash=hash_password("test-password"),
                )
                for role in ("admin", "agent", "viewer")
            }
            db.add(workspace)
            db.add_all(users.values())
            db.flush()
            for role, user in users.items():
                db.add(Membership(user_id=user.id, workspace_id=workspace.id, role=role))
            db.commit()
            created.append(workspace.id)
            return ObsWorkspace(
                workspace_id=workspace.id,
                slug=workspace.slug,
                admin_id=users["admin"].id,
                agent_id=users["agent"].id,
                viewer_id=users["viewer"].id,
                admin_headers=_headers(users["admin"].id, workspace.id, "admin"),
                agent_headers=_headers(users["agent"].id, workspace.id, "agent"),
                viewer_headers=_headers(users["viewer"].id, workspace.id, "viewer"),
            )

    yield make

    with SessionLocal() as db:
        for workspace_id in created:
            db.execute(delete(AuditLog).where(AuditLog.workspace_id == workspace_id))
            db.execute(delete(AiCallLog).where(AiCallLog.workspace_id == workspace_id))
            db.execute(delete(Ticket).where(Ticket.workspace_id == workspace_id))
            db.execute(delete(Message).where(Message.workspace_id == workspace_id))
            db.execute(delete(Conversation).where(Conversation.workspace_id == workspace_id))
            memberships = db.execute(
                select(Membership.user_id).where(Membership.workspace_id == workspace_id)
            ).scalars().all()
            db.execute(delete(Membership).where(Membership.workspace_id == workspace_id))
            if memberships:
                db.execute(delete(User).where(User.id.in_(memberships)))
            db.execute(delete(Workspace).where(Workspace.id == workspace_id))
        db.commit()


def _conversation(workspace_id, status: str, subject: str, created_at: datetime) -> Conversation:
    return Conversation(
        workspace_id=workspace_id,
        visitor_id=f"visitor-{uuid.uuid4().hex[:8]}",
        channel="web",
        status=status,
        subject=subject,
        metadata_={"seed": "test"},
        last_message_at=created_at,
        created_at=created_at,
        updated_at=created_at,
    )


def test_dashboard_summary_logs_and_permissions(
    client: TestClient, obs_factory
) -> None:
    workspace = obs_factory()
    now = datetime.now(UTC)
    with SessionLocal() as db:
        waiting = _conversation(workspace.workspace_id, "waiting_human", "退款政策？", now - timedelta(hours=1))
        closed = _conversation(workspace.workspace_id, "closed", "试用期多久？", now - timedelta(days=2))
        active = _conversation(workspace.workspace_id, "active", "基础版价格？", now - timedelta(days=3))
        db.add_all([waiting, closed, active])
        db.flush()

        db.add_all(
            [
                Message(
                    conversation_id=waiting.id,
                    workspace_id=workspace.workspace_id,
                    role="visitor",
                    content="退款政策？",
                    metadata_={"mode": "refused"},
                    created_at=now - timedelta(hours=1),
                ),
                Message(
                    conversation_id=waiting.id,
                    workspace_id=workspace.workspace_id,
                    role="assistant",
                    content="抱歉，知识库中没有退款政策。",
                    metadata_={"mode": "refused"},
                    created_at=now - timedelta(minutes=59),
                ),
                Message(
                    conversation_id=closed.id,
                    workspace_id=workspace.workspace_id,
                    role="visitor",
                    content="试用期多久？",
                    metadata_={"mode": "answer"},
                    created_at=now - timedelta(days=2),
                ),
                Message(
                    conversation_id=closed.id,
                    workspace_id=workspace.workspace_id,
                    role="assistant",
                    content="可以免费试用 14 天。",
                    confidence=0.8,
                    metadata_={"mode": "answer"},
                    created_at=now - timedelta(days=2),
                ),
                Message(
                    conversation_id=active.id,
                    workspace_id=workspace.workspace_id,
                    role="assistant",
                    content="基础版每月 299 元。",
                    confidence=0.6,
                    metadata_={"mode": "answer"},
                    created_at=now - timedelta(days=3),
                ),
            ]
        )
        db.add_all(
            [
                Ticket(
                    workspace_id=workspace.workspace_id,
                    conversation_id=waiting.id,
                    title="退款政策缺口",
                    priority="high",
                    status="open",
                    assignee_id=workspace.admin_id,
                    created_by_user_id=workspace.admin_id,
                ),
                Ticket(
                    workspace_id=workspace.workspace_id,
                    conversation_id=closed.id,
                    title="试用咨询",
                    priority="low",
                    status="closed",
                    created_by_user_id=workspace.admin_id,
                ),
            ]
        )
        db.add_all(
            [
                AiCallLog(
                    workspace_id=workspace.workspace_id,
                    conversation_id=closed.id,
                    provider="openrouter",
                    model="openrouter/free",
                    mode="answer",
                    confidence=0.8,
                    latency_ms=420,
                    success=True,
                ),
                AiCallLog(
                    workspace_id=workspace.workspace_id,
                    conversation_id=waiting.id,
                    provider="rules",
                    mode="refused",
                    success=True,
                ),
            ]
        )
        db.add(
            AuditLog(
                workspace_id=workspace.workspace_id,
                actor_user_id=workspace.admin_id,
                action="ticket.create",
                target_type="ticket",
                detail={"title": "退款政策缺口"},
            )
        )
        db.commit()

    summary = client.get("/api/v1/dashboard/summary", headers=workspace.viewer_headers)
    assert summary.status_code == 200
    data = summary.json()["data"]
    assert data["conversations_total"] == 3
    assert data["waiting_human"] == 1
    assert data["closed_conversations"] == 1
    assert data["tickets_total"] == 2
    assert data["tickets_open"] == 1
    assert data["ai_answers"] == 2
    assert data["refused_answers"] == 1
    assert data["refusal_rate"] == 0.3333
    assert data["avg_confidence"] == 0.7
    assert len(data["daily"]) == 7
    assert data["knowledge_gaps"][0]["question"] == "退款政策？"
    assert data["knowledge_gaps"][0]["occurrences"] == 1

    ai_logs = client.get("/api/v1/ai-logs", headers=workspace.viewer_headers)
    assert ai_logs.status_code == 200
    assert len(ai_logs.json()["data"]) == 2

    assert client.get("/api/v1/audit-logs", headers=workspace.agent_headers).status_code == 403
    audit_logs = client.get("/api/v1/audit-logs", headers=workspace.admin_headers)
    assert audit_logs.status_code == 200
    assert audit_logs.json()["data"][0]["action"] == "ticket.create"
    assert audit_logs.json()["data"][0]["actor_name"] == "Admin Ops"


def test_audit_hooks_and_rate_limit(client: TestClient, obs_factory, monkeypatch) -> None:
    workspace = obs_factory()
    chat = client.post(
        f"/api/v1/public/workspaces/{workspace.slug}/chat",
        json={"message": "我要人工客服", "visitor_id": "obs-visitor-1"},
    )
    assert chat.status_code == 200
    conversation_id = next(
        json.loads(line[5:].strip())
        for line in chat.text.splitlines()
        if line.startswith("data:")
        and "conversation_id" in line
        and "visitor_id" in line
    )["conversation_id"]

    assert (
        client.post(
            f"/api/v1/conversations/{conversation_id}/join", headers=workspace.agent_headers
        ).status_code
        == 200
    )
    ticket = client.post(
        "/api/v1/tickets",
        json={"conversation_id": conversation_id, "title": "人工跟进退款"},
        headers=workspace.agent_headers,
    )
    assert ticket.status_code == 201
    assert (
        client.post(
            f"/api/v1/conversations/{conversation_id}/close", headers=workspace.agent_headers
        ).status_code
        == 200
    )

    audit = client.get("/api/v1/audit-logs", headers=workspace.admin_headers)
    actions = {entry["action"] for entry in audit.json()["data"]}
    assert {"conversation.join", "conversation.close", "ticket.create"} <= actions

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    identifier = f"rl-{uuid.uuid4().hex}"
    assert check_rate_limit("test", identifier, limit=2) is True
    assert check_rate_limit("test", identifier, limit=2) is True
    assert check_rate_limit("test", identifier, limit=2) is False

    monkeypatch.setattr(settings, "public_chat_limit_per_minute", 1)
    visitor_id = f"limited-{uuid.uuid4().hex}"
    payload = {"message": "我要人工客服", "visitor_id": visitor_id}
    first = client.post(f"/api/v1/public/workspaces/{workspace.slug}/chat", json=payload)
    assert first.status_code == 200
    second = client.post(f"/api/v1/public/workspaces/{workspace.slug}/chat", json=payload)
    assert second.status_code == 429
