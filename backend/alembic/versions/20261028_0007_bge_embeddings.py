"""switch knowledge embeddings to the local BGE model (512 dimensions)

Revision ID: 20261028_0007
Revises: 20261026_0006
Create Date: 2026-10-28 10:00:00
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

from alembic import op

revision = "20261028_0007"
down_revision = "20261026_0006"
branch_labels = None
depends_on = None


def _replace_embedding(dimensions: int) -> None:
    op.drop_index("ix_knowledge_chunks_embedding_cosine", table_name="knowledge_chunks")
    # Existing 256-dimension vectors cannot be cast, and they will be regenerated.
    op.execute("DELETE FROM knowledge_chunks")
    op.drop_column("knowledge_chunks", "embedding")
    op.add_column(
        "knowledge_chunks",
        sa.Column("embedding", Vector(dimensions), nullable=False),
    )
    op.create_index(
        "ix_knowledge_chunks_embedding_cosine",
        "knowledge_chunks",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"m": 16, "ef_construction": 64},
    )


def upgrade() -> None:
    _replace_embedding(512)


def downgrade() -> None:
    _replace_embedding(256)
