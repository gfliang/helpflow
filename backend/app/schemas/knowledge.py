from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class CreateFaqRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=100_000)
    category: str | None = Field(default=None, max_length=120)


class UpdateDocumentRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, min_length=1, max_length=100_000)
    category: str | None = Field(default=None, max_length=120)


class KnowledgeDocumentResponse(BaseModel):
    id: UUID
    title: str
    type: str
    category: str | None
    status: str
    version: int
    source_filename: str | None
    failure_reason: str | None
    chunk_count: int
    created_at: datetime
    updated_at: datetime
    published_at: datetime | None


class KnowledgeDocumentDetailResponse(KnowledgeDocumentResponse):
    content: str | None


class KnowledgeChunkResponse(BaseModel):
    id: UUID
    sequence: int
    content: str
    metadata: dict[str, object]


class TestQueryRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1_000)
    limit: int = Field(default=4, ge=1, le=8)


class TestQueryMatch(BaseModel):
    document_id: UUID
    document_title: str
    chunk_id: UUID
    content: str
    score: float


class TestQueryResponse(BaseModel):
    answer_preview: str
    matches: list[TestQueryMatch]
