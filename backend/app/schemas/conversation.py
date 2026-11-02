from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.agent import AgentRunDetail


class ConversationSummary(BaseModel):
    id: UUID
    visitor_id: str
    channel: str
    status: str
    subject: str | None
    assigned_user_id: UUID | None
    assigned_user_name: str | None
    message_count: int
    last_message: str | None
    ticket_id: UUID | None
    last_message_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ConversationMessageResponse(BaseModel):
    id: UUID
    role: str
    content: str
    confidence: float | None
    citations: list[dict[str, object]]
    visibility: str
    author_user_id: UUID | None
    author_user_name: str | None
    created_at: datetime


class ConversationDetailResponse(ConversationSummary):
    messages: list[ConversationMessageResponse]
    agent_runs: list[AgentRunDetail] = Field(default_factory=list)


class AgentReplyRequest(BaseModel):
    content: str = Field(min_length=1, max_length=5_000)
    internal: bool = False
