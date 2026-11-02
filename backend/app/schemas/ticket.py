from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

TicketPriority = Literal["low", "normal", "high", "urgent"]
TicketStatus = Literal["open", "in_progress", "waiting", "resolved", "closed"]


class TicketResponse(BaseModel):
    id: UUID
    conversation_id: UUID | None
    conversation_subject: str | None
    title: str
    description: str | None
    priority: str
    status: str
    assignee_id: UUID | None
    assignee_name: str | None
    created_by_user_id: UUID | None
    created_by_name: str | None
    created_at: datetime
    updated_at: datetime


class CreateTicketRequest(BaseModel):
    conversation_id: UUID | None = None
    title: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5_000)
    priority: TicketPriority = "normal"
    assignee_id: UUID | None = None


class UpdateTicketRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=5_000)
    priority: TicketPriority | None = None
    status: TicketStatus | None = None
    assignee_id: UUID | None = None
