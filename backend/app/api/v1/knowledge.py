import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps.auth import CurrentUser, require_roles
from app.core.config import settings
from app.db.session import get_db
from app.models import KnowledgeChunk, KnowledgeDocument
from app.schemas.knowledge import (
    CreateFaqRequest,
    KnowledgeChunkResponse,
    KnowledgeDocumentDetailResponse,
    KnowledgeDocumentResponse,
    TestQueryMatch,
    TestQueryRequest,
    TestQueryResponse,
    UpdateDocumentRequest,
)
from app.services.audit import record_audit
from app.services.retrieval import retrieve_published_chunks
from app.tasks.knowledge import process_document

router = APIRouter(prefix="/knowledge", tags=["knowledge"])
SUPPORTED_UPLOADS = {".md": "markdown", ".txt": "text", ".pdf": "pdf"}


def _document_count(document_id: uuid.UUID, db: Session) -> int:
    return db.scalar(select(func.count()).select_from(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id)) or 0


def _serialize_document(document: KnowledgeDocument, db: Session) -> KnowledgeDocumentResponse:
    return KnowledgeDocumentResponse(
        id=document.id,
        title=document.title,
        type=document.type,
        category=document.category,
        status=document.status,
        version=document.version,
        source_filename=document.source_filename,
        failure_reason=document.failure_reason,
        chunk_count=_document_count(document.id, db),
        created_at=document.created_at,
        updated_at=document.updated_at,
        published_at=document.published_at,
    )


def _get_document(document_id: uuid.UUID, current: CurrentUser, db: Session) -> KnowledgeDocument:
    document = db.scalar(
        select(KnowledgeDocument).where(
            KnowledgeDocument.id == document_id, KnowledgeDocument.workspace_id == current.workspace.id
        )
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Knowledge document not found")
    return document


@router.get("/documents")
def list_documents(
    current: CurrentUser = Depends(require_roles("admin", "agent", "viewer")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, list[KnowledgeDocumentResponse]]:
    documents = db.scalars(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.workspace_id == current.workspace.id)
        .order_by(KnowledgeDocument.updated_at.desc())
    ).all()
    return {"data": [_serialize_document(document, db) for document in documents]}


@router.post("/documents", status_code=status.HTTP_201_CREATED)
def create_faq(
    payload: CreateFaqRequest,
    background_tasks: BackgroundTasks,
    current: CurrentUser = Depends(require_roles("admin", "agent")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, KnowledgeDocumentResponse]:
    document = KnowledgeDocument(
        workspace_id=current.workspace.id,
        title=payload.title,
        type="faq",
        content=payload.content,
        category=payload.category,
        status="uploading",
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    background_tasks.add_task(process_document, document.id)
    return {"data": _serialize_document(document, db)}


@router.post("/documents/upload", status_code=status.HTTP_201_CREATED)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),  # noqa: B008
    title: str | None = Form(default=None),
    category: str | None = Form(default=None),
    current: CurrentUser = Depends(require_roles("admin", "agent")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, KnowledgeDocumentResponse]:
    original_filename = file.filename or "document"
    extension = Path(original_filename).suffix.lower()
    document_type = SUPPORTED_UPLOADS.get(extension)
    if document_type is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Only .md, .txt and .pdf are supported")
    payload = await file.read()
    if not payload:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Uploaded file is empty")
    if len(payload) > 10 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Maximum upload size is 10 MB")

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    storage_path = settings.upload_dir / f"{uuid.uuid4()}{extension}"
    storage_path.write_bytes(payload)
    document = KnowledgeDocument(
        workspace_id=current.workspace.id,
        title=title.strip() if title and title.strip() else Path(original_filename).stem,
        type=document_type,
        category=category.strip() if category and category.strip() else None,
        status="uploading",
        source_filename=original_filename,
        storage_path=str(storage_path.resolve()),
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    background_tasks.add_task(process_document, document.id)
    return {"data": _serialize_document(document, db)}


@router.get("/documents/{document_id}")
def get_document(
    document_id: uuid.UUID,
    current: CurrentUser = Depends(require_roles("admin", "agent", "viewer")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, KnowledgeDocumentDetailResponse]:
    document = _get_document(document_id, current, db)
    summary = _serialize_document(document, db)
    return {"data": KnowledgeDocumentDetailResponse(**summary.model_dump(), content=document.content)}


@router.patch("/documents/{document_id}")
def update_document(
    document_id: uuid.UUID,
    payload: UpdateDocumentRequest,
    background_tasks: BackgroundTasks,
    current: CurrentUser = Depends(require_roles("admin", "agent")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, KnowledgeDocumentResponse]:
    document = _get_document(document_id, current, db)
    if payload.title is not None:
        document.title = payload.title
    if payload.category is not None:
        document.category = payload.category
    reindex = payload.content is not None
    if reindex:
        if document.type == "pdf":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="PDF content cannot be edited directly; upload a new file instead",
            )
        document.content = payload.content
        document.version += 1
        document.status = "uploading"
        document.published_at = None
    db.commit()
    db.refresh(document)
    if reindex:
        background_tasks.add_task(process_document, document.id)
    return {"data": _serialize_document(document, db)}


@router.post("/documents/{document_id}/publish")
def publish_document(
    document_id: uuid.UUID,
    current: CurrentUser = Depends(require_roles("admin", "agent")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, KnowledgeDocumentResponse]:
    document = _get_document(document_id, current, db)
    if document.status not in {"ready", "archived"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only ready or archived documents can be published",
        )
    document.status = "published"
    document.published_at = datetime.now(UTC)
    record_audit(
        db,
        current.workspace.id,
        current.user.id,
        "knowledge.publish",
        "knowledge_document",
        document.id,
        {"title": document.title, "version": document.version},
    )
    db.commit()
    db.refresh(document)
    return {"data": _serialize_document(document, db)}


@router.post("/documents/{document_id}/archive")
def archive_document(
    document_id: uuid.UUID,
    current: CurrentUser = Depends(require_roles("admin", "agent")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, KnowledgeDocumentResponse]:
    document = _get_document(document_id, current, db)
    document.status = "archived"
    document.published_at = None
    record_audit(
        db,
        current.workspace.id,
        current.user.id,
        "knowledge.archive",
        "knowledge_document",
        document.id,
        {"title": document.title},
    )
    db.commit()
    db.refresh(document)
    return {"data": _serialize_document(document, db)}


@router.get("/documents/{document_id}/chunks")
def list_chunks(
    document_id: uuid.UUID,
    current: CurrentUser = Depends(require_roles("admin", "agent", "viewer")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, list[KnowledgeChunkResponse]]:
    _get_document(document_id, current, db)
    chunks = db.scalars(
        select(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id).order_by(KnowledgeChunk.sequence)
    ).all()
    return {
        "data": [
            KnowledgeChunkResponse(id=chunk.id, sequence=chunk.sequence, content=chunk.content, metadata=chunk.metadata_)
            for chunk in chunks
        ]
    }


@router.post("/test-query")
def test_query(
    payload: TestQueryRequest,
    current: CurrentUser = Depends(require_roles("admin", "agent", "viewer")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, TestQueryResponse]:
    results = retrieve_published_chunks(db, current.workspace.id, payload.query, payload.limit)
    matches = [
        TestQueryMatch(
            document_id=item.document.id,
            document_title=item.document.title,
            chunk_id=item.chunk.id,
            content=item.chunk.content,
            score=item.score,
        )
        for item in results
    ]
    preview = matches[0].content if matches else "没有找到已发布知识库中的相关内容。"
    return {"data": TestQueryResponse(answer_preview=preview, matches=matches)}
