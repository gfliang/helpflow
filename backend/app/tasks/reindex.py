"""Rebuild vector chunks for already-published documents.

Run after an embedding-model or dimension migration:

    cd backend && uv run python -m app.tasks.reindex
"""

import argparse

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import KnowledgeDocument, Workspace
from app.providers.embeddings import embedding_provider
from app.tasks.knowledge import process_document


def reindex_documents(workspace_slug: str | None = None) -> int:
    with SessionLocal() as db:
        query = select(KnowledgeDocument).where(
            KnowledgeDocument.status.in_(("published", "ready"))
        )
        if workspace_slug:
            workspace = db.scalar(select(Workspace).where(Workspace.slug == workspace_slug))
            if workspace is None:
                raise SystemExit(f"Workspace '{workspace_slug}' not found")
            query = query.where(KnowledgeDocument.workspace_id == workspace.id)
        documents = db.scalars(query.order_by(KnowledgeDocument.created_at.asc())).all()
        snapshots = [
            (document.id, document.status, document.published_at) for document in documents
        ]

    for document_id, status, published_at in snapshots:
        process_document(document_id)
        if status == "published":
            with SessionLocal() as db:
                document = db.get(KnowledgeDocument, document_id)
                if document is not None and document.status == "ready":
                    document.status = "published"
                    document.published_at = published_at
                    db.commit()

    print(
        f"Reindexed {len(snapshots)} document(s) with embedding backend "
        f"'{embedding_provider.name}' ({embedding_provider.dimensions} dimensions)."
    )
    return len(snapshots)


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild knowledge chunks and embeddings")
    parser.add_argument("--workspace", default=None, help="Optional workspace slug")
    args = parser.parse_args()
    reindex_documents(args.workspace)


if __name__ == "__main__":
    main()
