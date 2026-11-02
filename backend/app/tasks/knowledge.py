import uuid
from pathlib import Path

from sqlalchemy import delete

from app.core.config import settings
from app.db.session import SessionLocal
from app.models import KnowledgeChunk, KnowledgeDocument
from app.providers.embeddings import embedding_provider
from app.services.documents import DocumentParsingError, parse_document, split_text


def process_document(document_id: uuid.UUID) -> None:
    """Parse and index a document in an isolated database session for background execution."""
    with SessionLocal() as db:
        document = db.get(KnowledgeDocument, document_id)
        if document is None:
            return
        document.status = "processing"
        document.failure_reason = None
        db.commit()
        try:
            if document.type in {"faq", "markdown", "text"} and document.content:
                content = document.content
            elif document.storage_path is not None:
                content = parse_document(Path(document.storage_path), document.type)
            else:
                raise DocumentParsingError("文档内容为空，无法建立索引。")
            chunks = split_text(content, settings.knowledge_chunk_size, settings.knowledge_chunk_overlap)
            db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id))
            document.content = content
            embeddings = embedding_provider.embed_many(chunks)
            db.add_all(
                [
                    KnowledgeChunk(
                        document_id=document.id,
                        workspace_id=document.workspace_id,
                        content=chunk,
                        embedding=embeddings[index],
                        sequence=index,
                        metadata_={"document_title": document.title, "category": document.category},
                    )
                    for index, chunk in enumerate(chunks)
                ]
            )
            document.status = "ready"
            document.failure_reason = None
            db.commit()
        except DocumentParsingError as error:
            document.status = "failed"
            document.failure_reason = str(error)
            db.commit()
        except Exception:  # noqa: BLE001 - any indexing failure must mark the document failed
            document.status = "failed"
            document.failure_reason = "文档索引失败，请检查内容后重试。"
            db.commit()
