import uuid
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps.auth import CurrentUser, require_roles
from app.db.session import get_db
from app.models import Conversation, Message, Ticket
from app.schemas.dashboard import DailyPoint, DashboardSummary, KnowledgeGap

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

CLOSED_TICKET_STATUSES = {"resolved", "closed"}


def _mode_count(db: Session, workspace_id: uuid.UUID, mode: str) -> int:
    total = db.scalar(
        select(func.count())
        .select_from(Message)
        .where(
            Message.workspace_id == workspace_id,
            Message.role == "assistant",
            Message.metadata_["mode"].astext == mode,
        )
    )
    return int(total or 0)


def _knowledge_gaps(db: Session, workspace_id: uuid.UUID) -> list[KnowledgeGap]:
    since = datetime.now(UTC) - timedelta(days=30)
    rows = db.execute(
        select(Message.content, Message.created_at)
        .where(
            Message.workspace_id == workspace_id,
            Message.role == "visitor",
            Message.metadata_["mode"].astext == "refused",
            Message.created_at >= since,
        )
        .order_by(Message.created_at.desc())
        .limit(500)
    ).all()
    counter: Counter[str] = Counter()
    latest: dict[str, datetime] = {}
    display: dict[str, str] = {}
    for content, created_at in rows:
        normalized = " ".join(content.split()).strip()
        if not normalized:
            continue
        counter[normalized] += 1
        latest[normalized] = max(latest.get(normalized, created_at), created_at)
        display.setdefault(normalized, normalized)
    return [
        KnowledgeGap(question=display[key], occurrences=count, last_asked_at=latest[key])
        for key, count in counter.most_common(8)
    ]


@router.get("/summary")
def dashboard_summary(
    current: CurrentUser = Depends(require_roles("admin", "agent", "viewer")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, DashboardSummary]:
    workspace_id = current.workspace.id
    conversation_counts = dict(
        db.execute(
            select(Conversation.status, func.count())
            .where(Conversation.workspace_id == workspace_id)
            .group_by(Conversation.status)
        ).all()
    )
    total_conversations = sum(conversation_counts.values())
    ticket_counts = dict(
        db.execute(
            select(Ticket.status, func.count())
            .where(Ticket.workspace_id == workspace_id)
            .group_by(Ticket.status)
        ).all()
    )
    tickets_total = sum(ticket_counts.values())
    tickets_open = sum(count for status, count in ticket_counts.items() if status not in CLOSED_TICKET_STATUSES)

    answers = _mode_count(db, workspace_id, "answer")
    refusals = _mode_count(db, workspace_id, "refused")
    handoffs = _mode_count(db, workspace_id, "handoff") + _mode_count(db, workspace_id, "human_waiting")
    avg_confidence = db.scalar(
        select(func.avg(Message.confidence)).where(
            Message.workspace_id == workspace_id,
            Message.role == "assistant",
            Message.metadata_["mode"].astext == "answer",
            Message.confidence.is_not(None),
        )
    )

    today = datetime.now(UTC).date()
    first_day = today - timedelta(days=6)
    window_start = datetime.combine(first_day, time.min, tzinfo=UTC)
    conversation_rows = db.execute(
        select(Conversation.created_at).where(
            Conversation.workspace_id == workspace_id, Conversation.created_at >= window_start
        )
    ).scalars().all()
    message_rows = db.execute(
        select(Message.created_at, Message.metadata_["mode"].astext).where(
            Message.workspace_id == workspace_id,
            Message.role == "assistant",
            Message.created_at >= window_start,
        )
    ).all()

    conversation_by_day = Counter(
        row.astimezone(UTC).date() for row in conversation_rows if row is not None
    )
    answers_by_day = Counter(
        created_at.astimezone(UTC).date()
        for created_at, mode in message_rows
        if mode == "answer"
    )
    refusals_by_day = Counter(
        created_at.astimezone(UTC).date()
        for created_at, mode in message_rows
        if mode == "refused"
    )

    daily: list[DailyPoint] = []
    for offset in range(7):
        day: date = first_day + timedelta(days=offset)
        daily.append(
            DailyPoint(
                date=day.strftime("%m-%d"),
                conversations=conversation_by_day.get(day, 0),
                ai_answers=answers_by_day.get(day, 0),
                refusals=refusals_by_day.get(day, 0),
            )
        )

    attempts = answers + refusals
    refusal_rate = round(refusals / attempts, 4) if attempts else 0.0

    summary = DashboardSummary(
        conversations_total=total_conversations,
        waiting_human=int(conversation_counts.get("waiting_human", 0)),
        human_active=int(conversation_counts.get("human", 0)),
        closed_conversations=int(conversation_counts.get("closed", 0)),
        tickets_total=tickets_total,
        tickets_open=tickets_open,
        ai_answers=answers,
        refused_answers=refusals,
        handoff_requests=handoffs,
        refusal_rate=refusal_rate,
        avg_confidence=round(float(avg_confidence), 4) if avg_confidence is not None else None,
        daily=daily,
        knowledge_gaps=_knowledge_gaps(db, workspace_id),
    )
    return {"data": summary}
