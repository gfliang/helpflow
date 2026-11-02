from datetime import datetime

from pydantic import BaseModel


class DailyPoint(BaseModel):
    date: str
    conversations: int
    ai_answers: int
    refusals: int


class KnowledgeGap(BaseModel):
    question: str
    occurrences: int
    last_asked_at: datetime


class DashboardSummary(BaseModel):
    conversations_total: int
    waiting_human: int
    human_active: int
    closed_conversations: int
    tickets_total: int
    tickets_open: int
    ai_answers: int
    refused_answers: int
    handoff_requests: int
    refusal_rate: float
    avg_confidence: float | None
    daily: list[DailyPoint]
    knowledge_gaps: list[KnowledgeGap]
