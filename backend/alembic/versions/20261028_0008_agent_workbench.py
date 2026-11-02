"""agent workbench: customers, orders, runs, approvals and evaluation tables

Revision ID: 20261028_0008
Revises: 20261028_0007
Create Date: 2026-10-28 11:00:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261028_0008"
down_revision = "20261028_0007"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB


def upgrade() -> None:
    op.create_table(
        "customers",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "workspace_id", UUID, sa.ForeignKey("workspaces.id"), nullable=False, index=True
        ),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("company", sa.String(120), nullable=True),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("workspace_id", "email", name="uq_customer_workspace_email"),
    )
    op.create_index("ix_customers_email", "customers", ["email"])

    op.create_table(
        "orders",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "workspace_id", UUID, sa.ForeignKey("workspaces.id"), nullable=False, index=True
        ),
        sa.Column(
            "customer_id",
            UUID,
            sa.ForeignKey("customers.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("order_no", sa.String(64), nullable=False),
        sa.Column("product_name", sa.String(160), nullable=False),
        sa.Column("plan", sa.String(64), nullable=False, server_default="pro"),
        sa.Column("amount", sa.Float, nullable=False, server_default="0"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="CNY"),
        sa.Column("status", sa.String(32), nullable=False, server_default="paid", index=True),
        sa.Column("purchased_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refunded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("workspace_id", "order_no", name="uq_order_workspace_no"),
    )
    op.create_index("ix_orders_order_no", "orders", ["order_no"])

    op.create_table(
        "agent_runs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "workspace_id", UUID, sa.ForeignKey("workspaces.id"), nullable=False, index=True
        ),
        sa.Column(
            "conversation_id",
            UUID,
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("thread_id", sa.String(64), nullable=False, unique=True, index=True),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("intent", sa.String(32), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="running", index=True),
        sa.Column("answer", sa.Text, nullable=True),
        sa.Column("citations", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "agent_events",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "run_id",
            UUID,
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "workspace_id", UUID, sa.ForeignKey("workspaces.id"), nullable=False, index=True
        ),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("name", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="ok"),
        sa.Column("summary", sa.Text, nullable=True),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.UniqueConstraint("run_id", "seq", name="uq_agent_event_run_seq"),
    )

    op.create_table(
        "agent_approvals",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "run_id",
            UUID,
            sa.ForeignKey("agent_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "workspace_id", UUID, sa.ForeignKey("workspaces.id"), nullable=False, index=True
        ),
        sa.Column("tool_name", sa.String(64), nullable=False),
        sa.Column("arguments", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending", index=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column(
            "decided_by_user_id",
            UUID,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "eval_runs",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "workspace_id",
            UUID,
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(120), nullable=False, server_default="baseline"),
        sa.Column("status", sa.String(16), nullable=False, server_default="running", index=True),
        sa.Column("judge", sa.String(32), nullable=False, server_default="heuristic"),
        sa.Column("total_cases", sa.Integer, nullable=False, server_default="0"),
        sa.Column("passed_cases", sa.Integer, nullable=False, server_default="0"),
        sa.Column("metrics", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "created_by_user_id",
            UUID,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )

    op.create_table(
        "eval_cases",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "run_id",
            UUID,
            sa.ForeignKey("eval_runs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "workspace_id", UUID, sa.ForeignKey("workspaces.id"), nullable=False, index=True
        ),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column(
            "expected_documents", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column("cited_documents", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("predicted_mode", sa.String(16), nullable=False),
        sa.Column("expected_mode", sa.String(16), nullable=False),
        sa.Column("passed", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("metrics", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("latency_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("eval_cases")
    op.drop_table("eval_runs")
    op.drop_table("agent_approvals")
    op.drop_table("agent_events")
    op.drop_table("agent_runs")
    op.drop_index("ix_orders_order_no", table_name="orders")
    op.drop_table("orders")
    op.drop_index("ix_customers_email", table_name="customers")
    op.drop_table("customers")
