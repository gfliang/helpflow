import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps.auth import CurrentUser, require_roles
from app.db.session import get_db
from app.models import Conversation, Membership, Ticket, User
from app.schemas.ticket import CreateTicketRequest, TicketResponse, UpdateTicketRequest
from app.services.audit import record_audit

router = APIRouter(prefix="/tickets", tags=["tickets"])

TICKET_STATUSES = {"open", "in_progress", "waiting", "resolved", "closed"}
ALLOWED_TRANSITIONS = {
    "open": {"in_progress", "waiting", "resolved", "closed"},
    "in_progress": {"waiting", "resolved", "closed"},
    "waiting": {"in_progress", "resolved", "closed"},
    "resolved": {"in_progress", "closed"},
    "closed": {"open"},
}


def _get_ticket(ticket_id: uuid.UUID, current: CurrentUser, db: Session) -> Ticket:
    ticket = db.scalar(
        select(Ticket).where(Ticket.id == ticket_id, Ticket.workspace_id == current.workspace.id)
    )
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return ticket


def _assert_member(user_id: uuid.UUID, workspace_id: uuid.UUID, db: Session) -> None:
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user_id, Membership.workspace_id == workspace_id
        )
    )
    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Assignee must be a member of this workspace",
        )


def _serialize(ticket: Ticket, db: Session) -> TicketResponse:
    names = {}
    user_ids = {user_id for user_id in (ticket.assignee_id, ticket.created_by_user_id) if user_id}
    if user_ids:
        names = dict(db.execute(select(User.id, User.name).where(User.id.in_(user_ids))).all())
    subject = None
    if ticket.conversation_id:
        subject = db.scalar(
            select(Conversation.subject).where(Conversation.id == ticket.conversation_id)
        )
    return TicketResponse(
        id=ticket.id,
        conversation_id=ticket.conversation_id,
        conversation_subject=subject,
        title=ticket.title,
        description=ticket.description,
        priority=ticket.priority,
        status=ticket.status,
        assignee_id=ticket.assignee_id,
        assignee_name=names.get(ticket.assignee_id) if ticket.assignee_id else None,
        created_by_user_id=ticket.created_by_user_id,
        created_by_name=(
            names.get(ticket.created_by_user_id) if ticket.created_by_user_id else None
        ),
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
    )


@router.get("")
def list_tickets(
    status_filter: str | None = Query(default=None, alias="status"),
    priority: str | None = Query(default=None),
    assignee: str = Query(default="all", pattern="^(all|me|unassigned)$"),
    current: CurrentUser = Depends(require_roles("admin", "agent", "viewer")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, list[TicketResponse]]:
    query = select(Ticket).where(Ticket.workspace_id == current.workspace.id)
    if status_filter:
        if status_filter not in TICKET_STATUSES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Unknown status filter")
        query = query.where(Ticket.status == status_filter)
    if priority:
        query = query.where(Ticket.priority == priority)
    if assignee == "me":
        query = query.where(Ticket.assignee_id == current.user.id)
    elif assignee == "unassigned":
        query = query.where(Ticket.assignee_id.is_(None))
    tickets = db.scalars(query.order_by(Ticket.created_at.desc())).all()
    return {"data": [_serialize(ticket, db) for ticket in tickets]}


@router.post("", status_code=status.HTTP_201_CREATED)
def create_ticket(
    payload: CreateTicketRequest,
    current: CurrentUser = Depends(require_roles("admin", "agent")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, TicketResponse]:
    conversation: Conversation | None = None
    if payload.conversation_id is not None:
        conversation = db.scalar(
            select(Conversation).where(
                Conversation.id == payload.conversation_id,
                Conversation.workspace_id == current.workspace.id,
            )
        )
        if conversation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
            )
        existing = db.scalar(
            select(Ticket).where(
                Ticket.conversation_id == conversation.id,
                Ticket.workspace_id == current.workspace.id,
                Ticket.status != "closed",
            )
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This conversation already has an open ticket",
            )
    if payload.assignee_id is not None:
        _assert_member(payload.assignee_id, current.workspace.id, db)

    ticket = Ticket(
        workspace_id=current.workspace.id,
        conversation_id=conversation.id if conversation else None,
        title=payload.title.strip(),
        description=payload.description.strip() if payload.description else None,
        priority=payload.priority,
        status="open",
        assignee_id=payload.assignee_id,
        created_by_user_id=current.user.id,
    )
    db.add(ticket)
    db.flush()
    record_audit(
        db,
        current.workspace.id,
        current.user.id,
        "ticket.create",
        "ticket",
        ticket.id,
        {
            "title": ticket.title,
            "priority": ticket.priority,
            "conversation_id": str(ticket.conversation_id) if ticket.conversation_id else None,
        },
    )
    db.commit()
    db.refresh(ticket)
    return {"data": _serialize(ticket, db)}


@router.get("/{ticket_id}")
def get_ticket(
    ticket_id: uuid.UUID,
    current: CurrentUser = Depends(require_roles("admin", "agent", "viewer")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, TicketResponse]:
    return {"data": _serialize(_get_ticket(ticket_id, current, db), db)}


@router.patch("/{ticket_id}")
def update_ticket(
    ticket_id: uuid.UUID,
    payload: UpdateTicketRequest,
    current: CurrentUser = Depends(require_roles("admin", "agent")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, TicketResponse]:
    ticket = _get_ticket(ticket_id, current, db)
    updates = payload.model_fields_set

    if payload.title is not None and "title" in updates:
        ticket.title = payload.title.strip()
    if "description" in updates:
        ticket.description = payload.description.strip() if payload.description else None
    if payload.priority is not None:
        ticket.priority = payload.priority
    if payload.status is not None and payload.status != ticket.status:
        if payload.status not in ALLOWED_TRANSITIONS.get(ticket.status, set()):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot move ticket from {ticket.status} to {payload.status}",
            )
        ticket.status = payload.status
    if "assignee_id" in updates:
        if payload.assignee_id is not None:
            _assert_member(payload.assignee_id, current.workspace.id, db)
        ticket.assignee_id = payload.assignee_id

    record_audit(
        db,
        current.workspace.id,
        current.user.id,
        "ticket.update",
        "ticket",
        ticket.id,
        {
            "status": ticket.status,
            "priority": ticket.priority,
            "assignee_id": str(ticket.assignee_id) if ticket.assignee_id else None,
        },
    )
    db.commit()
    db.refresh(ticket)
    return {"data": _serialize(ticket, db)}
