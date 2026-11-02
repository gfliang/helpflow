"""Business tools exposed to the LangGraph agent.

Every tool returns a JSON-serialisable dict with a ``status`` and a human-readable
``summary`` so the graph can both render a timeline and synthesize an answer.
Side-effecting tools (tickets, refunds, handoff) write through the provided
session; the caller owns the transaction.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Conversation, Customer, Message, Order, Ticket
from app.services.rag import docs_to_context
from app.services.retrieval import retrieve_documents

REFUND_WINDOW_DAYS = 7
REFUND_AI_USAGE_LIMIT = 100


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def serialize_order(order: Order) -> dict[str, object]:
    return {
        "order_no": order.order_no,
        "product_name": order.product_name,
        "plan": order.plan,
        "amount": order.amount,
        "currency": order.currency,
        "status": order.status,
        "purchased_at": _iso(order.purchased_at),
        "delivered_at": _iso(order.delivered_at),
        "refunded_at": _iso(order.refunded_at),
        "ai_usage": int(order.metadata_.get("ai_usage", 0) or 0),
    }


def format_order_line(order: Order) -> str:
    return (
        f"订单 {order.order_no}（{order.product_name}，{order.currency} {order.amount:,.0f}）"
        f"当前状态：{order.status}"
    )


def _find_customer(
    db: Session,
    workspace_id: uuid.UUID,
    email: str | None = None,
    visitor_id: str | None = None,
) -> Customer | None:
    query = select(Customer).where(Customer.workspace_id == workspace_id)
    if email:
        customer = db.scalar(query.where(Customer.email == email.strip().lower()))
        if customer is not None:
            return customer
    if visitor_id:
        return db.scalar(query.where(Customer.metadata_["visitor_id"].astext == visitor_id))
    return None


def _find_order(db: Session, workspace_id: uuid.UUID, order_no: str) -> Order | None:
    return db.scalar(
        select(Order).where(
            Order.workspace_id == workspace_id,
            Order.order_no == order_no.strip().upper(),
        )
    )


def search_knowledge(
    db: Session, workspace_id: uuid.UUID, query: str, limit: int = 4
) -> dict[str, object]:
    documents = retrieve_documents(db, workspace_id, query, limit)
    context, citations, confidence = docs_to_context(documents)
    if not context:
        return {
            "status": "empty",
            "summary": "知识库中没有找到足够可靠的内容。",
            "context": [],
            "citations": [],
            "confidence": confidence,
            "data": {"documents": []},
        }
    titles = "；".join(dict.fromkeys(item["document_title"] for item in citations))
    return {
        "status": "ok",
        "summary": f"检索到 {len(context)} 段相关资料：{titles}",
        "context": [
            {"index": item.index, "title": item.title, "content": item.content} for item in context
        ],
        "citations": citations,
        "confidence": confidence,
        "data": {"documents": [item["document_title"] for item in citations]},
    }


def get_customer(
    db: Session,
    workspace_id: uuid.UUID,
    email: str | None = None,
    visitor_id: str | None = None,
) -> dict[str, object]:
    customer = _find_customer(db, workspace_id, email=email, visitor_id=visitor_id)
    if customer is None:
        return {
            "status": "not_found",
            "summary": "未找到匹配的客户档案，请提供下单邮箱。",
            "data": {},
        }
    return {
        "status": "ok",
        "summary": f"客户 {customer.name}（{customer.email}）",
        "data": {
            "id": str(customer.id),
            "name": customer.name,
            "email": customer.email,
            "company": customer.company,
        },
    }


def list_orders(
    db: Session,
    workspace_id: uuid.UUID,
    customer_id: str | None = None,
    email: str | None = None,
) -> dict[str, object]:
    query = select(Order).where(Order.workspace_id == workspace_id)
    customer = None
    if customer_id:
        query = query.where(Order.customer_id == uuid.UUID(customer_id))
    elif email:
        customer = _find_customer(db, workspace_id, email=email)
        if customer is None:
            return {
                "status": "not_found",
                "summary": "未找到该邮箱对应的客户。",
                "data": {"orders": []},
            }
        query = query.where(Order.customer_id == customer.id)
    else:
        return {
            "status": "need_identifier",
            "summary": "请提供下单邮箱或订单号，我才能查询具体订单。",
            "data": {"orders": []},
        }

    orders = db.scalars(query.order_by(Order.purchased_at.desc().nullslast()).limit(10)).all()
    return {
        "status": "ok" if orders else "empty",
        "summary": (
            "；".join(format_order_line(order) for order in orders)
            if orders
            else "该客户名下没有订单。"
        ),
        "data": {"orders": [serialize_order(order) for order in orders]},
    }


def get_order(db: Session, workspace_id: uuid.UUID, order_no: str) -> dict[str, object]:
    order = _find_order(db, workspace_id, order_no)
    if order is None:
        return {
            "status": "not_found",
            "summary": f"未找到订单 {order_no}，请确认订单号是否正确。",
            "data": {},
        }
    return {
        "status": "ok",
        "summary": format_order_line(order),
        "data": {"order": serialize_order(order)},
    }


def check_refund_eligibility(
    db: Session, workspace_id: uuid.UUID, order_no: str
) -> dict[str, object]:
    order = _find_order(db, workspace_id, order_no)
    if order is None:
        return {
            "status": "not_found",
            "summary": f"未找到订单 {order_no}。",
            "data": {"eligible": False},
        }
    reasons: list[str] = []
    eligible = True
    if order.status == "refunded":
        eligible = False
        reasons.append("该订单已经退款")
    elif order.status in {"cancelled"}:
        eligible = False
        reasons.append("该订单已取消，无需退款")
    elif order.status not in {"paid", "shipped", "delivered"}:
        eligible = False
        reasons.append("当前订单状态不在可退款范围")

    anchor = order.delivered_at or order.purchased_at
    if anchor is not None:
        anchor_aware = anchor if anchor.tzinfo else anchor.replace(tzinfo=UTC)
        if _now() - anchor_aware > timedelta(days=REFUND_WINDOW_DAYS):
            eligible = False
            reasons.append(f"已超过 {REFUND_WINDOW_DAYS} 天退款窗口")

    ai_usage = int(order.metadata_.get("ai_usage", 0) or 0)
    if ai_usage >= REFUND_AI_USAGE_LIMIT:
        eligible = False
        reasons.append(f"AI 对话已使用 {ai_usage} 次，超过 {REFUND_AI_USAGE_LIMIT} 次上限")

    if eligible:
        summary = f"订单 {order.order_no} 符合退款条件，可提交人工审批。"
    else:
        summary = f"订单 {order.order_no} 暂不符合退款条件：{'；'.join(reasons)}。"
    return {
        "status": "ok",
        "summary": summary,
        "data": {
            "eligible": eligible,
            "reasons": reasons,
            "order": serialize_order(order),
            "window_days": REFUND_WINDOW_DAYS,
            "ai_usage_limit": REFUND_AI_USAGE_LIMIT,
        },
    }


def create_ticket(
    db: Session,
    workspace_id: uuid.UUID,
    conversation_id: str | None,
    title: str,
    description: str | None = None,
    priority: str = "normal",
) -> dict[str, object]:
    ticket = Ticket(
        workspace_id=workspace_id,
        conversation_id=uuid.UUID(conversation_id) if conversation_id else None,
        title=title[:255],
        description=description,
        priority=priority if priority in {"low", "normal", "high", "urgent"} else "normal",
        status="open",
    )
    db.add(ticket)
    db.flush()
    return {
        "status": "ok",
        "summary": f"已创建工单「{ticket.title}」（优先级 {ticket.priority}）。",
        "data": {"ticket_id": str(ticket.id), "title": ticket.title, "priority": ticket.priority},
    }


def request_refund(
    db: Session,
    workspace_id: uuid.UUID,
    conversation_id: str | None,
    order_no: str,
    reason: str,
    decided_by: str | None = None,
    note: str | None = None,
) -> dict[str, object]:
    order = _find_order(db, workspace_id, order_no)
    if order is None:
        return {"status": "not_found", "summary": f"未找到订单 {order_no}。", "data": {}}
    if order.status == "refunded":
        return {
            "status": "skipped",
            "summary": f"订单 {order_no} 已退款，无需重复操作。",
            "data": {"order": serialize_order(order)},
        }
    order.status = "refunded"
    order.refunded_at = _now()
    order.metadata_ = {
        **order.metadata_,
        "refund_reason": reason,
        "refund_approved_by": decided_by or "客服",
        "refund_note": note or "",
    }
    if conversation_id:
        db.add(
            Message(
                conversation_id=uuid.UUID(conversation_id),
                workspace_id=workspace_id,
                role="assistant",
                content=(
                    f"退款申请已通过审批。订单 {order.order_no} 已标记为已退款，"
                    f"金额 {order.currency} {order.amount:,.0f} 将在 3-10 个工作日内原路退回。"
                ),
                metadata_={
                    "source": "agent",
                    "tool": "request_refund",
                    "approved_by": decided_by or "客服",
                },
            )
        )
    return {
        "status": "ok",
        "summary": (
            f"订单 {order.order_no} 已完成退款（{order.currency} {order.amount:,.0f}），"
            "预计 3-10 个工作日到账。"
        ),
        "data": {"order": serialize_order(order), "note": note or ""},
    }


def handoff_to_human(
    db: Session,
    workspace_id: uuid.UUID,
    conversation_id: str | None,
    reason: str,
) -> dict[str, object]:
    if conversation_id:
        conversation = db.get(Conversation, uuid.UUID(conversation_id))
        if conversation is not None and conversation.workspace_id == workspace_id:
            conversation.status = "waiting_human"
            conversation.metadata_ = {
                **conversation.metadata_,
                "handoff_requested_at": _now().isoformat(),
                "handoff_reason": reason,
            }
    return {
        "status": "ok",
        "summary": f"已转接人工客服（原因：{reason}）。",
        "data": {"reason": reason},
    }


TOOL_REGISTRY = {
    "search_knowledge": search_knowledge,
    "get_customer": get_customer,
    "list_orders": list_orders,
    "get_order": get_order,
    "check_refund_eligibility": check_refund_eligibility,
    "create_ticket": create_ticket,
    "request_refund": request_refund,
    "handoff_to_human": handoff_to_human,
}
