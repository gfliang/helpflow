import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps.auth import CurrentUser, require_roles
from app.db.session import get_db
from app.models import AgentApproval, AgentEvent, AgentRun, Conversation, Message, Ticket, User
from app.schemas.agent import build_run_detail
from app.schemas.conversation import (
    AgentReplyRequest,
    ConversationDetailResponse,
    ConversationMessageResponse,
    ConversationSummary,
)
from app.services.audit import record_audit

router = APIRouter(prefix="/conversations", tags=["conversations"])

ALLOWED_STATUSES = {"active", "waiting_human", "human", "closed"}
CLOSING_NOTE = "本次会话已由人工客服结束，如仍有问题可以重新发起咨询。"


def _get_conversation(
    conversation_id: uuid.UUID, current: CurrentUser, db: Session
) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.workspace_id == current.workspace.id,
        )
    )
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    return conversation


def _user_names(db: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = db.execute(select(User.id, User.name).where(User.id.in_(ids))).all()
    return {user_id: name for user_id, name in rows}


def _serialize_message(
    message: Message, names: dict[uuid.UUID, str]
) -> ConversationMessageResponse:
    return ConversationMessageResponse(
        id=message.id,
        role=message.role,
        content=message.content,
        confidence=message.confidence,
        citations=message.citations or [],
        visibility=message.visibility,
        author_user_id=message.author_user_id,
        author_user_name=names.get(message.author_user_id) if message.author_user_id else None,
        created_at=message.created_at,
    )


def _ticket_map(db: Session, workspace_id: uuid.UUID, ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
    if not ids:
        return {}
    rows = db.execute(
        select(Ticket.conversation_id, Ticket.id)
        .where(
            Ticket.workspace_id == workspace_id,
            Ticket.conversation_id.in_(ids),
            Ticket.status != "closed",
        )
        .order_by(Ticket.created_at.desc())
    ).all()
    mapping: dict[uuid.UUID, uuid.UUID] = {}
    for conversation_id, ticket_id in rows:
        if conversation_id is not None and conversation_id not in mapping:
            mapping[conversation_id] = ticket_id
    return mapping


def _summaries(
    db: Session, workspace_id: uuid.UUID, conversations: list[Conversation]
) -> list[ConversationSummary]:
    ids = [conversation.id for conversation in conversations]
    if not ids:
        return []

    messages = db.execute(
        select(Message)
        .where(Message.conversation_id.in_(ids))
        .order_by(Message.created_at.asc())
    ).scalars().all()
    grouped: dict[uuid.UUID, list[Message]] = {conversation_id: [] for conversation_id in ids}
    for message in messages:
        grouped.setdefault(message.conversation_id, []).append(message)
    assignee_names = _user_names(
        db, {conversation.assigned_user_id for conversation in conversations if conversation.assigned_user_id}
    )
    tickets = _ticket_map(db, workspace_id, ids)

    summaries = []
    for conversation in conversations:
        public_messages = [message for message in grouped[conversation.id] if message.visibility == "public"]
        last = public_messages[-1] if public_messages else None
        summaries.append(
            ConversationSummary(
                id=conversation.id,
                visitor_id=conversation.visitor_id,
                channel=conversation.channel,
                status=conversation.status,
                subject=conversation.subject,
                assigned_user_id=conversation.assigned_user_id,
                assigned_user_name=(
                    assignee_names.get(conversation.assigned_user_id)
                    if conversation.assigned_user_id
                    else None
                ),
                message_count=len(public_messages),
                last_message=last.content[:160] if last else None,
                ticket_id=tickets.get(conversation.id),
                last_message_at=conversation.last_message_at,
                created_at=conversation.created_at,
                updated_at=conversation.updated_at,
            )
        )
    return summaries


@router.get("")
def list_conversations(
    status_filter: str | None = Query(default=None, alias="status"),
    assigned: str = Query(default="all", pattern="^(all|me|unassigned)$"),
    q: str | None = Query(default=None, max_length=120),
    current: CurrentUser = Depends(require_roles("admin", "agent", "viewer")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, list[ConversationSummary]]:
    query = select(Conversation).where(Conversation.workspace_id == current.workspace.id)
    if status_filter:
        if status_filter not in ALLOWED_STATUSES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown status filter")
        query = query.where(Conversation.status == status_filter)
    if assigned == "me":
        query = query.where(Conversation.assigned_user_id == current.user.id)
    elif assigned == "unassigned":
        query = query.where(Conversation.assigned_user_id.is_(None))
    if q and q.strip():
        keyword = f"%{q.strip()}%"
        query = query.where(
            or_(Conversation.subject.ilike(keyword), Conversation.visitor_id.ilike(keyword))
        )
    conversations = db.scalars(
        query.order_by(
            func.coalesce(Conversation.last_message_at, Conversation.created_at).desc()
        )
    ).all()
    return {"data": _summaries(db, current.workspace.id, list(conversations))}


@router.get("/{conversation_id}")
def get_conversation(
    conversation_id: uuid.UUID,
    current: CurrentUser = Depends(require_roles("admin", "agent", "viewer")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, ConversationDetailResponse]:
    conversation = _get_conversation(conversation_id, current, db)
    include_internal = current.membership.role != "viewer"
    message_query = select(Message).where(Message.conversation_id == conversation.id)
    if not include_internal:
        message_query = message_query.where(Message.visibility == "public")
    messages = db.scalars(message_query.order_by(Message.created_at.asc())).all()
    names = _user_names(
        db,
        {message.author_user_id for message in messages if message.author_user_id}
        | ({conversation.assigned_user_id} if conversation.assigned_user_id else set()),
    )
    summary = _summaries(db, current.workspace.id, [conversation])[0]
    runs = db.scalars(
        select(AgentRun)
        .where(AgentRun.conversation_id == conversation.id)
        .order_by(AgentRun.created_at.desc())
        .limit(5)
    ).all()
    run_ids = [run.id for run in runs]
    events = (
        db.scalars(
            select(AgentEvent).where(AgentEvent.run_id.in_(run_ids)).order_by(AgentEvent.seq)
        ).all()
        if run_ids
        else []
    )
    approvals = (
        db.scalars(
            select(AgentApproval)
            .where(AgentApproval.run_id.in_(run_ids))
            .order_by(AgentApproval.requested_at)
        ).all()
        if run_ids
        else []
    )
    events_by_run: dict[uuid.UUID, list[AgentEvent]] = {}
    approvals_by_run: dict[uuid.UUID, list[AgentApproval]] = {}
    for event in events:
        events_by_run.setdefault(event.run_id, []).append(event)
    for approval in approvals:
        approvals_by_run.setdefault(approval.run_id, []).append(approval)
    return {
        "data": ConversationDetailResponse(
            **summary.model_dump(),
            messages=[_serialize_message(message, names) for message in messages],
            agent_runs=[
                build_run_detail(
                    run, events_by_run.get(run.id, []), approvals_by_run.get(run.id, [])
                )
                for run in runs
            ],
        )
    }


@router.post("/{conversation_id}/join")
def join_conversation(
    conversation_id: uuid.UUID,
    current: CurrentUser = Depends(require_roles("admin", "agent")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, ConversationDetailResponse]:
    conversation = _get_conversation(conversation_id, current, db)
    if conversation.status == "closed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conversation is already closed")
    if conversation.assigned_user_id and conversation.assigned_user_id != current.user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conversation is already assigned to another agent",
        )
    conversation.assigned_user_id = current.user.id
    conversation.assigned_at = conversation.assigned_at or datetime.now(UTC)
    conversation.status = "human"
    record_audit(
        db,
        current.workspace.id,
        current.user.id,
        "conversation.join",
        "conversation",
        conversation.id,
        {"visitor_id": conversation.visitor_id},
    )
    db.commit()
    db.refresh(conversation)
    return get_conversation(conversation.id, current, db)


@router.post("/{conversation_id}/messages", status_code=status.HTTP_201_CREATED)
def reply_to_conversation(
    conversation_id: uuid.UUID,
    payload: AgentReplyRequest,
    current: CurrentUser = Depends(require_roles("admin", "agent")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, ConversationMessageResponse]:
    conversation = _get_conversation(conversation_id, current, db)
    if conversation.status == "closed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Conversation is already closed")
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Message cannot be blank")

    now = datetime.now(UTC)
    if conversation.assigned_user_id is None:
        conversation.assigned_user_id = current.user.id
        conversation.assigned_at = now
    if not payload.internal:
        conversation.status = "human"
        conversation.last_message_at = now
    message = Message(
        conversation_id=conversation.id,
        workspace_id=current.workspace.id,
        role="agent",
        content=content,
        visibility="internal" if payload.internal else "public",
        author_user_id=current.user.id,
        metadata_={"internal": payload.internal},
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    names = _user_names(db, {current.user.id})
    return {"data": _serialize_message(message, names)}


@router.post("/{conversation_id}/close")
def close_conversation(
    conversation_id: uuid.UUID,
    current: CurrentUser = Depends(require_roles("admin", "agent")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, ConversationDetailResponse]:
    conversation = _get_conversation(conversation_id, current, db)
    if conversation.status != "closed":
        now = datetime.now(UTC)
        conversation.status = "closed"
        conversation.closed_at = now
        conversation.last_message_at = now
        if conversation.assigned_user_id is None:
            conversation.assigned_user_id = current.user.id
            conversation.assigned_at = now
        db.add(
            Message(
                conversation_id=conversation.id,
                workspace_id=current.workspace.id,
                role="system",
                content=CLOSING_NOTE,
                visibility="public",
                author_user_id=current.user.id,
                metadata_={"closed_by": str(current.user.id)},
            )
        )
        record_audit(
            db,
            current.workspace.id,
            current.user.id,
            "conversation.close",
            "conversation",
            conversation.id,
            {"visitor_id": conversation.visitor_id},
        )
        db.commit()
        db.refresh(conversation)
    return get_conversation(conversation.id, current, db)
