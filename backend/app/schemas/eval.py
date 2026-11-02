from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class EvalCaseResponse(BaseModel):
    id: UUID
    question: str
    expected_documents: list[str]
    cited_documents: list[str]
    predicted_mode: str
    expected_mode: str
    passed: bool
    metrics: dict[str, object]
    latency_ms: int
    error: str | None
    created_at: datetime


class EvalRunSummary(BaseModel):
    id: UUID
    name: str
    status: str
    judge: str
    total_cases: int
    passed_cases: int
    metrics: dict[str, object]
    created_at: datetime
    started_at: datetime
    finished_at: datetime | None


class EvalRunDetail(EvalRunSummary):
    cases: list[EvalCaseResponse] = Field(default_factory=list)


class EvalTrendPoint(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    pass_rate: float


class EvalSummaryResponse(BaseModel):
    latest: EvalRunSummary | None
    history: list[EvalTrendPoint] = Field(default_factory=list)
    golden_total: int
