"""Agent + human-in-the-loop coverage for the refund workflow."""

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db.session import SessionLocal
from app.main import app
from app.models import (
    AgentApproval,
    AgentEvent,
    AgentRun,
    Conversation,
    Customer,
    EvalCase,
    EvalRun,
    Membership,
    Message,
    Order,
    User,
    Workspace,
)
from app.services.passwords import hash_password
from app.services.tokens import create_access_token


@dataclass(frozen=True)
class AgentWorkspace:
    workspace_id: uuid.UUID
    slug: str
    admin_headers: dict[str, str]
    viewer_headers: dict[str, str]
    visitor_id: str
    order_no: str


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _headers(user_id: uuid.UUID, workspace_id: uuid.UUID, role: str) -> dict[str, str]:
    token, _ = create_access_token(user_id=user_id, workspace_id=workspace_id, role=role)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def agent_workspace() -> Iterator[AgentWorkspace]:
    suffix = uuid.uuid4().hex[:10]
    visitor_id = f"visitor-agent-{suffix}"
    order_no = f"HF-TEST-{suffix[:6].upper()}"
    created_users: list[uuid.UUID] = []

    with SessionLocal() as db:
        admin = User(
            email=f"agent-admin-{suffix}@helpflow.test",
            name="Agent Admin",
            password_hash=hash_password("test-password"),
        )
        viewer = User(
            email=f"agent-viewer-{suffix}@helpflow.test",
            name="Agent Viewer",
            password_hash=hash_password("test-password"),
        )
        workspace = Workspace(name="Agent Test", slug=f"agent-{suffix}")
        db.add_all([admin, viewer, workspace])
        db.flush()
        db.add_all(
            [
                Membership(user_id=admin.id, workspace_id=workspace.id, role="admin"),
                Membership(user_id=viewer.id, workspace_id=workspace.id, role="viewer"),
            ]
        )
        customer = Customer(
            workspace_id=workspace.id,
            name="测试客户",
            email=f"customer-{suffix}@helpflow.test",
            metadata_={"visitor_id": visitor_id},
        )
        db.add(customer)
        db.flush()
        db.add(
            Order(
                workspace_id=workspace.id,
                customer_id=customer.id,
                order_no=order_no,
                product_name="专业版年度订阅",
                plan="pro",
                amount=8990,
                currency="CNY",
                status="paid",
                purchased_at=datetime.now(UTC) - timedelta(days=2),
                delivered_at=datetime.now(UTC) - timedelta(days=2),
                metadata_={"ai_usage": 5},
            )
        )
        db.commit()
        workspace_id = workspace.id
        created_users = [admin.id, viewer.id]

    yield AgentWorkspace(
        workspace_id=workspace_id,
        slug=f"agent-{suffix}",
        admin_headers=_headers(created_users[0], workspace_id, "admin"),
        viewer_headers=_headers(created_users[1], workspace_id, "viewer"),
        visitor_id=visitor_id,
        order_no=order_no,
    )

    with SessionLocal() as db:
        conversation_ids = db.scalars(
            select(Conversation.id).where(Conversation.workspace_id == workspace_id)
        ).all()
        if conversation_ids:
            db.execute(delete(AgentEvent).where(AgentEvent.run_id.in_(
                select(AgentRun.id).where(AgentRun.conversation_id.in_(conversation_ids))
            )))
            db.execute(delete(AgentApproval).where(AgentApproval.run_id.in_(
                select(AgentRun.id).where(AgentRun.conversation_id.in_(conversation_ids))
            )))
            db.execute(delete(AgentRun).where(AgentRun.conversation_id.in_(conversation_ids)))
            db.execute(delete(Message).where(Message.conversation_id.in_(conversation_ids)))
            db.execute(delete(Conversation).where(Conversation.id.in_(conversation_ids)))
        db.execute(delete(EvalCase).where(EvalCase.workspace_id == workspace_id))
        db.execute(delete(EvalRun).where(EvalRun.workspace_id == workspace_id))
        db.execute(delete(Order).where(Order.workspace_id == workspace_id))
        db.execute(delete(Customer).where(Customer.workspace_id == workspace_id))
        db.execute(delete(Membership).where(Membership.workspace_id == workspace_id))
        db.execute(delete(Workspace).where(Workspace.id == workspace_id))
        db.execute(delete(User).where(User.id.in_(created_users)))
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


def _ask_refund(
    client: TestClient,
    workspace: AgentWorkspace,
    message: str | None = None,
) -> list[tuple[str, dict]]:
    response = client.post(
        f"/api/v1/public/workspaces/{workspace.slug}/chat",
        json={
            "message": message or f"我的订单 {workspace.order_no} 要退款",
            "visitor_id": workspace.visitor_id,
        },
    )
    assert response.status_code == 200
    return parse_sse(response.text)


def test_refund_question_enters_agent_and_pauses_for_approval(client, agent_workspace) -> None:
    events = _ask_refund(client, agent_workspace)
    meta = event_payload(events, "meta")
    assert meta["mode"] == "agent"
    assert meta["agent_run_id"]

    steps = [payload for event, payload in events if event == "agent_step"]
    assert any(step["name"] == "check_refund_eligibility" for step in steps)
    assert any(step["status"] == "ok" for step in steps)

    approval = event_payload(events, "approval_required")
    assert approval["tool"] == "request_refund"
    assert approval["arguments"]["order_no"] == agent_workspace.order_no

    done = event_payload(events, "done")
    assert done["agent_status"] == "waiting_approval"
    assert done["agent_run_id"] == meta["agent_run_id"]

    with SessionLocal() as db:
        run = db.get(AgentRun, uuid.UUID(done["agent_run_id"]))
        assert run is not None
        assert run.status == "waiting_approval"
        approvals = db.scalars(
            select(AgentApproval).where(AgentApproval.run_id == run.id)
        ).all()
    assert [approval.status for approval in approvals] == ["pending"]


def test_approving_refund_marks_order_refunded(client, agent_workspace) -> None:
    events = _ask_refund(client, agent_workspace)
    run_id = event_payload(events, "done")["agent_run_id"]

    response = client.post(
        f"/api/v1/agents/runs/{run_id}/approve",
        headers=agent_workspace.admin_headers,
        json={"note": "符合退款条件，同意"},
    )
    assert response.status_code == 200
    run = response.json()["data"]
    assert run["status"] == "completed"
    assert run["approvals"][0]["status"] == "approved"
    assert "退款" in run["answer"]

    with SessionLocal() as db:
        order = db.scalar(
            select(Order).where(Order.order_no == agent_workspace.order_no)
        )
        conversation = db.get(Conversation, uuid.UUID(run["conversation_id"]))
    assert order is not None
    assert order.status == "refunded"
    assert conversation is not None
    assert conversation.status != "waiting_human"


def test_rejecting_refund_keeps_order_status(client, agent_workspace) -> None:
    events = _ask_refund(client, agent_workspace)
    run_id = event_payload(events, "done")["agent_run_id"]

    response = client.post(
        f"/api/v1/agents/runs/{run_id}/reject",
        headers=agent_workspace.admin_headers,
        json={"note": "该订单已交付超过约定时间"},
    )
    assert response.status_code == 200
    run = response.json()["data"]
    assert run["status"] == "rejected"
    assert run["approvals"][0]["status"] == "rejected"
    assert "未通过" in run["answer"]

    with SessionLocal() as db:
        order = db.scalar(
            select(Order).where(Order.order_no == agent_workspace.order_no)
        )
    assert order is not None
    assert order.status == "paid"


def test_viewer_cannot_approve_refund(client, agent_workspace) -> None:
    events = _ask_refund(client, agent_workspace)
    run_id = event_payload(events, "done")["agent_run_id"]

    response = client.post(
        f"/api/v1/agents/runs/{run_id}/approve",
        headers=agent_workspace.viewer_headers,
        json={"note": "只读角色不应通过"},
    )
    assert response.status_code == 403


def test_ineligible_order_skips_approval(client, agent_workspace) -> None:
    with SessionLocal() as db:
        order = db.scalar(select(Order).where(Order.order_no == agent_workspace.order_no))
        assert order is not None
        order.status = "refunded"
        order.refunded_at = datetime.now(UTC)
        db.commit()

    events = _ask_refund(client, agent_workspace)
    assert all(event != "approval_required" for event, _ in events)
    done = event_payload(events, "done")
    assert done["agent_status"] == "completed"
    answer = "".join(payload["text"] for event, payload in events if event == "delta")
    assert "退款" in answer


def test_approval_without_checkpoint_is_applied_directly(client, agent_workspace) -> None:
    """Seeded runs carry no LangGraph checkpoint; approval must still complete."""
    with SessionLocal() as db:
        conversation = Conversation(
            workspace_id=agent_workspace.workspace_id,
            visitor_id=agent_workspace.visitor_id,
            channel="web",
            status="waiting_human",
            subject="申请退款",
        )
        db.add(conversation)
        db.flush()
        run = AgentRun(
            workspace_id=agent_workspace.workspace_id,
            conversation_id=conversation.id,
            thread_id=uuid.uuid4().hex,
            question=f"我的订单 {agent_workspace.order_no} 要退款",
            intent="refund",
            status="waiting_approval",
            answer="等待人工审批。",
        )
        db.add(run)
        db.flush()
        db.add(
            AgentApproval(
                run_id=run.id,
                workspace_id=agent_workspace.workspace_id,
                tool_name="request_refund",
                arguments={"order_no": agent_workspace.order_no, "reason": "访客申请退款"},
                status="pending",
                requested_at=datetime.now(UTC),
            )
        )
        db.commit()
        run_id = run.id

    response = client.post(
        f"/api/v1/agents/runs/{run_id}/approve",
        headers=agent_workspace.admin_headers,
        json={"note": "符合退款条件"},
    )
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["status"] == "completed"
    assert payload["approvals"][0]["status"] == "approved"
    assert "退款" in payload["answer"]

    with SessionLocal() as db:
        order = db.scalar(select(Order).where(Order.order_no == agent_workspace.order_no))
    assert order is not None
    assert order.status == "refunded"
