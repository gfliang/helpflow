"""Admin endpoints for creating demo orders used by the refund agent flow."""

import re
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps.auth import CurrentUser, require_roles
from app.db.session import get_db
from app.models import Customer, Order
from app.services.audit import record_audit

router = APIRouter(prefix="/orders", tags=["orders"])

DEMO_CUSTOMER_EMAIL = "demo-customer@helpflow.com"


class CreateOrderRequest(BaseModel):
    product_name: str = Field(default="专业版年度订阅", max_length=160)
    plan: str = Field(default="pro", max_length=64)
    amount: float = 8990.0
    ai_usage: int = Field(default=0, ge=0)
    customer_name: str = Field(default="演示客户", max_length=120)


def _next_order_no(db: Session, workspace_id: uuid.UUID) -> str:
    numbers = db.scalars(select(Order.order_no).where(Order.workspace_id == workspace_id)).all()
    highest = 0
    for number in numbers:
        match = re.fullmatch(r"HF-2026-(\d{4})", number)
        if match:
            highest = max(highest, int(match.group(1)))
    return f"HF-2026-{highest + 1:04d}"


def _get_or_create_demo_customer(db: Session, workspace_id: uuid.UUID, name: str) -> Customer:
    customer = db.scalar(
        select(Customer).where(
            Customer.workspace_id == workspace_id,
            Customer.email == DEMO_CUSTOMER_EMAIL,
        )
    )
    if customer is None:
        customer = Customer(workspace_id=workspace_id, name=name, email=DEMO_CUSTOMER_EMAIL)
        db.add(customer)
        db.flush()
    return customer


@router.post("", status_code=status.HTTP_201_CREATED)
def create_demo_order(
    payload: CreateOrderRequest,
    current: CurrentUser = Depends(require_roles("admin", "agent")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, dict[str, object]]:
    customer = _get_or_create_demo_customer(db, current.workspace.id, payload.customer_name)
    order = Order(
        workspace_id=current.workspace.id,
        customer_id=customer.id,
        order_no=_next_order_no(db, current.workspace.id),
        product_name=payload.product_name,
        plan=payload.plan,
        amount=payload.amount,
        currency="CNY",
        status="shipped",
        purchased_at=datetime.now(UTC),
        metadata_={"seed": "demo_console", "ai_usage": payload.ai_usage},
    )
    db.add(order)
    db.flush()
    record_audit(
        db,
        current.workspace.id,
        current.user.id,
        "order.create",
        "order",
        order.id,
        {"order_no": order.order_no, "amount": order.amount},
    )
    db.commit()
    return {
        "data": {
            "id": str(order.id),
            "order_no": order.order_no,
            "product_name": order.product_name,
            "plan": order.plan,
            "amount": order.amount,
            "currency": order.currency,
            "status": order.status,
        }
    }
