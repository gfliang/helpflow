from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AgentEventResponse(BaseModel):
    id: UUID
    seq: int
    type: str
    name: str | None
    status: str
    summary: str | None
    payload: dict[str, object]
    created_at: datetime


class AgentApprovalResponse(BaseModel):
    id: UUID
    tool_name: str
    arguments: dict[str, object]
    status: str
    note: str | None
    requested_at: datetime
    decided_by_user_id: UUID | None
    decided_at: datetime | None


class AgentRunSummary(BaseModel):
    id: UUID
    conversation_id: UUID
    question: str
    intent: str | None
    status: str
    answer: str | None
    citations: list[dict[str, object]]
    error: str | None
    latency_ms: int | None
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class AgentRunDetail(AgentRunSummary):
    events: list[AgentEventResponse] = Field(default_factory=list)
    approvals: list[AgentApprovalResponse] = Field(default_factory=list)


class AgentDecisionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2_000)


def build_run_detail(
    run,
    events: list,
    approvals: list,
) -> AgentRunDetail:
    return AgentRunDetail(
        id=run.id,
        conversation_id=run.conversation_id,
        question=run.question,
        intent=run.intent,
        status=run.status,
        answer=run.answer,
        citations=run.citations or [],
        error=run.error,
        latency_ms=run.latency_ms,
        created_at=run.created_at,
        updated_at=run.updated_at,
        finished_at=run.finished_at,
        events=[
            AgentEventResponse(
                id=event.id,
                seq=event.seq,
                type=event.type,
                name=event.name,
                status=event.status,
                summary=event.summary,
                payload=event.payload or {},
                created_at=event.created_at,
            )
            for event in events
        ],
        approvals=[
            AgentApprovalResponse(
                id=approval.id,
                tool_name=approval.tool_name,
                arguments=approval.arguments or {},
                status=approval.status,
                note=approval.note,
                requested_at=approval.requested_at,
                decided_by_user_id=approval.decided_by_user_id,
                decided_at=approval.decided_at,
            )
            for approval in approvals
        ],
    )
