"""add human handoff fields, message visibility and tickets

Revision ID: 20261026_0005
Revises: 20261026_0004
Create Date: 2026-10-26 21:10:00
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261026_0005"
down_revision = "20261026_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("assigned_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_conversations_assigned_user_id", "conversations", ["assigned_user_id"]
    )
    op.create_foreign_key(
        "fk_conversations_assigned_user_id",
        "conversations",
        "users",
        ["assigned_user_id"],
        ["id"],
    )

    op.add_column(
        "messages",
        sa.Column(
            "visibility", sa.String(length=16), server_default="public", nullable=False
        ),
    )
    op.add_column(
        "messages",
        sa.Column("author_user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_messages_author_user_id", "messages", "users", ["author_user_id"], ["id"]
    )

    op.create_table(
        "tickets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("assignee_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"]),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["assignee_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tickets_workspace_id", "tickets", ["workspace_id"])
    op.create_index("ix_tickets_conversation_id", "tickets", ["conversation_id"])
    op.create_index("ix_tickets_status", "tickets", ["status"])
    op.create_index("ix_tickets_assignee_id", "tickets", ["assignee_id"])


def downgrade() -> None:
    op.drop_index("ix_tickets_assignee_id", table_name="tickets")
    op.drop_index("ix_tickets_status", table_name="tickets")
    op.drop_index("ix_tickets_conversation_id", table_name="tickets")
    op.drop_index("ix_tickets_workspace_id", table_name="tickets")
    op.drop_table("tickets")

    op.drop_constraint("fk_messages_author_user_id", "messages", type_="foreignkey")
    op.drop_column("messages", "author_user_id")
    op.drop_column("messages", "visibility")

    op.drop_constraint("fk_conversations_assigned_user_id", "conversations", type_="foreignkey")
    op.drop_index("ix_conversations_assigned_user_id", table_name="conversations")
    op.drop_column("conversations", "closed_at")
    op.drop_column("conversations", "assigned_at")
    op.drop_column("conversations", "assigned_user_id")
