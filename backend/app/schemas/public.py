from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class PublicChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1_000)
    conversation_id: UUID | None = None
    visitor_id: str | None = Field(default=None, min_length=1, max_length=64)


class PublicConversationMessage(BaseModel):
    id: UUID
    role: str
    content: str
    created_at: datetime


class PublicConversationMessagesResponse(BaseModel):
    conversation_id: UUID
    status: str
    messages: list[PublicConversationMessage]
