import json
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.models import Conversation, Membership, Message, Ticket, User, Workspace
from app.services.passwords import hash_password
from app.services.tokens import create_access_token


@dataclass(frozen=True)
class InboxWorkspace:
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
def inbox_factory() -> Iterator[Callable[[], InboxWorkspace]]:
    created: list[uuid.UUID] = []

    def make() -> InboxWorkspace:
        suffix = uuid.uuid4().hex[:10]
        with SessionLocal() as db:
            workspace = Workspace(name="Inbox Test", slug=f"inbox-{suffix}")
            users = {
                role: User(
                    email=f"inbox-{role}-{suffix}@helpflow.test",
                    name=f"{role.title()} User",
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
            return InboxWorkspace(
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


def start_handoff(client: TestClient, workspace: InboxWorkspace, visitor_id: str) -> str:
    response = client.post(
        f"/api/v1/public/workspaces/{workspace.slug}/chat",
        json={"message": "我要人工客服", "visitor_id": visitor_id},
    )
    assert response.status_code == 200
    meta = next(payload for event, payload in parse_sse(response.text) if event == "meta")
    assert meta["handoff"] is True
    return meta["conversation_id"]


def test_agent_handles_handoff_and_creates_ticket(
    client: TestClient, inbox_factory
) -> None:
    workspace = inbox_factory()
    conversation_id = start_handoff(client, workspace, "visitor-flow-1")

    follow_up = client.post(
        f"/api/v1/public/workspaces/{workspace.slug}/chat",
        json={
            "message": "补充一下，我还需要发票",
            "visitor_id": "visitor-flow-1",
            "conversation_id": conversation_id,
        },
    )
    follow_up_events = parse_sse(follow_up.text)
    follow_up_answer = "".join(
        payload["text"] for event, payload in follow_up_events if event == "delta"
    )
    assert "已收到你的补充" in follow_up_answer
    assert next(payload for event, payload in follow_up_events if event == "meta")["mode"] == "human_waiting"

    queue = client.get(
        "/api/v1/conversations", params={"status": "waiting_human"}, headers=workspace.agent_headers
    )
    assert queue.status_code == 200
    items = queue.json()["data"]
    assert [item["id"] for item in items] == [conversation_id]
    assert items[0]["assigned_user_name"] is None
    assert items[0]["ticket_id"] is None

    joined = client.post(
        f"/api/v1/conversations/{conversation_id}/join", headers=workspace.agent_headers
    )
    assert joined.status_code == 200
    detail = joined.json()["data"]
    assert detail["status"] == "human"
    assert detail["assigned_user_id"] == str(workspace.agent_id)

    internal = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "内部备注：客户提到续费问题", "internal": True},
        headers=workspace.agent_headers,
    )
    assert internal.status_code == 201
    assert internal.json()["data"]["visibility"] == "internal"

    reply = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "你好，我是客服小李，已看到你的问题。"},
        headers=workspace.agent_headers,
    )
    assert reply.status_code == 201
    assert reply.json()["data"]["role"] == "agent"

    visitor_view = client.get(
        f"/api/v1/public/workspaces/{workspace.slug}/conversations/{conversation_id}/messages",
        params={"visitor_id": "visitor-flow-1"},
    )
    assert visitor_view.status_code == 200
    visitor_messages = visitor_view.json()["data"]["messages"]
    assert any("客服小李" in message["content"] for message in visitor_messages)
    assert all("内部备注" not in message["content"] for message in visitor_messages)

    ticket = client.post(
        "/api/v1/tickets",
        json={
            "conversation_id": conversation_id,
            "title": "续费与发票问题",
            "description": "客户需要续费方案与发票，请跟进。",
            "priority": "high",
            "assignee_id": str(workspace.agent_id),
        },
        headers=workspace.agent_headers,
    )
    assert ticket.status_code == 201
    ticket_data = ticket.json()["data"]
    assert ticket_data["status"] == "open"
    assert ticket_data["priority"] == "high"
    assert ticket_data["assignee_name"] == "Agent User"
    assert ticket_data["conversation_id"] == conversation_id

    duplicate = client.post(
        "/api/v1/tickets",
        json={"conversation_id": conversation_id, "title": "重复工单"},
        headers=workspace.agent_headers,
    )
    assert duplicate.status_code == 409

    conversation_with_ticket = client.get(
        f"/api/v1/conversations/{conversation_id}", headers=workspace.agent_headers
    )
    assert conversation_with_ticket.json()["data"]["ticket_id"] == ticket_data["id"]

    moved = client.patch(
        f"/api/v1/tickets/{ticket_data['id']}",
        json={"status": "in_progress"},
        headers=workspace.agent_headers,
    )
    assert moved.status_code == 200
    assert moved.json()["data"]["status"] == "in_progress"

    resolved = client.patch(
        f"/api/v1/tickets/{ticket_data['id']}",
        json={"status": "resolved", "assignee_id": str(workspace.admin_id)},
        headers=workspace.admin_headers,
    )
    assert resolved.status_code == 200
    assert resolved.json()["data"]["status"] == "resolved"
    assert resolved.json()["data"]["assignee_name"] == "Admin User"

    closed_ticket = client.patch(
        f"/api/v1/tickets/{ticket_data['id']}",
        json={"status": "closed"},
        headers=workspace.admin_headers,
    )
    assert closed_ticket.status_code == 200

    invalid = client.patch(
        f"/api/v1/tickets/{ticket_data['id']}",
        json={"status": "waiting"},
        headers=workspace.admin_headers,
    )
    assert invalid.status_code == 409

    reopened = client.patch(
        f"/api/v1/tickets/{ticket_data['id']}",
        json={"status": "open"},
        headers=workspace.admin_headers,
    )
    assert reopened.status_code == 200
    assert reopened.json()["data"]["status"] == "open"

    client.patch(
        f"/api/v1/tickets/{ticket_data['id']}",
        json={"status": "closed"},
        headers=workspace.admin_headers,
    )

    closed = client.post(
        f"/api/v1/conversations/{conversation_id}/close", headers=workspace.agent_headers
    )
    assert closed.status_code == 200
    assert closed.json()["data"]["status"] == "closed"

    after_close = client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "还能回复吗？"},
        headers=workspace.agent_headers,
    )
    assert after_close.status_code == 409

    final_visitor_view = client.get(
        f"/api/v1/public/workspaces/{workspace.slug}/conversations/{conversation_id}/messages",
        params={"visitor_id": "visitor-flow-1"},
    )
    final_status = final_visitor_view.json()["data"]["status"]
    assert final_status == "closed"
    assert any(
        "会话已由人工客服结束" in message["content"]
        for message in final_visitor_view.json()["data"]["messages"]
    )


def test_viewer_is_read_only_and_cannot_see_internal_notes(
    client: TestClient, inbox_factory
) -> None:
    workspace = inbox_factory()
    conversation_id = start_handoff(client, workspace, "visitor-viewer-1")

    listed = client.get("/api/v1/conversations", headers=workspace.viewer_headers)
    assert listed.status_code == 200
    assert listed.json()["data"][0]["id"] == conversation_id

    assert (
        client.post(
            f"/api/v1/conversations/{conversation_id}/join", headers=workspace.viewer_headers
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/conversations/{conversation_id}/messages",
            json={"content": "只读角色不能回复"},
            headers=workspace.viewer_headers,
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/conversations/{conversation_id}/close", headers=workspace.viewer_headers
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/tickets",
            json={"conversation_id": conversation_id, "title": "只读不能建单"},
            headers=workspace.viewer_headers,
        ).status_code
        == 403
    )

    client.post(
        f"/api/v1/conversations/{conversation_id}/messages",
        json={"content": "内部备注，不对访客展示", "internal": True},
        headers=workspace.agent_headers,
    )
    viewer_detail = client.get(
        f"/api/v1/conversations/{conversation_id}", headers=workspace.viewer_headers
    )
    assert all(
        message["visibility"] == "public" for message in viewer_detail.json()["data"]["messages"]
    )
    agent_detail = client.get(
        f"/api/v1/conversations/{conversation_id}", headers=workspace.agent_headers
    )
    assert any(
        message["visibility"] == "internal"
        for message in agent_detail.json()["data"]["messages"]
    )


def test_workspace_isolation_and_assignee_validation(
    client: TestClient, inbox_factory
) -> None:
    workspace = inbox_factory()
    other = inbox_factory()
    conversation_id = start_handoff(client, workspace, "visitor-isolation-1")

    ticket = client.post(
        "/api/v1/tickets",
        json={"conversation_id": conversation_id, "title": "隔离测试"},
        headers=workspace.admin_headers,
    )
    ticket_id = ticket.json()["data"]["id"]

    assert (
        client.get(
            f"/api/v1/conversations/{conversation_id}", headers=other.admin_headers
        ).status_code
        == 404
    )
    assert (
        client.get(f"/api/v1/tickets/{ticket_id}", headers=other.admin_headers).status_code == 404
    )
    assert client.get("/api/v1/tickets", headers=other.admin_headers).json()["data"] == []

    cross_assign = client.post(
        "/api/v1/tickets",
        json={
            "title": "跨工作空间指派",
            "assignee_id": str(other.agent_id),
        },
        headers=workspace.admin_headers,
    )
    assert cross_assign.status_code == 422

    wrong_visitor = client.get(
        f"/api/v1/public/workspaces/{workspace.slug}/conversations/{conversation_id}/messages",
        params={"visitor_id": "someone-else"},
    )
    assert wrong_visitor.status_code == 404


def test_closed_conversation_cannot_be_reopened_or_joined(
    client: TestClient, inbox_factory
) -> None:
    workspace = inbox_factory()
    conversation_id = start_handoff(client, workspace, "visitor-closed-1")

    assert (
        client.post(
            f"/api/v1/conversations/{conversation_id}/close", headers=workspace.agent_headers
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/v1/conversations/{conversation_id}/join", headers=workspace.admin_headers
        ).status_code
        == 409
    )
