from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class AiCallLogResponse(BaseModel):
    id: UUID
    conversation_id: UUID | None
    conversation_subject: str | None
    provider: str
    model: str | None
    mode: str
    confidence: float | None
    latency_ms: int | None
    success: bool
    error: str | None
    created_at: datetime


class AuditLogResponse(BaseModel):
    id: UUID
    actor_name: str | None
    action: str
    target_type: str
    target_id: UUID | None
    detail: dict[str, object]
    created_at: datetime
