import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.service import ApprovalError, resume_run
from app.api.deps.auth import CurrentUser, require_roles
from app.db.session import get_db
from app.models import AgentApproval, AgentEvent, AgentRun
from app.schemas.agent import (
    AgentDecisionRequest,
    AgentRunDetail,
    AgentRunSummary,
    build_run_detail,
)
from app.services.audit import record_audit

router = APIRouter(prefix="/agents", tags=["agents"])

ALLOWED_STATUSES = {"running", "waiting_approval", "completed", "rejected", "failed"}


def _get_run(run_id: uuid.UUID, current: CurrentUser, db: Session) -> AgentRun:
    run = db.scalar(
        select(AgentRun).where(
            AgentRun.id == run_id, AgentRun.workspace_id == current.workspace.id
        )
    )
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent run not found")
    return run


def _serialize(db: Session, runs: list[AgentRun]) -> list[AgentRunDetail]:
    if not runs:
        return []
    ids = [run.id for run in runs]
    events = db.scalars(
        select(AgentEvent).where(AgentEvent.run_id.in_(ids)).order_by(AgentEvent.seq)
    ).all()
    approvals = db.scalars(
        select(AgentApproval)
        .where(AgentApproval.run_id.in_(ids))
        .order_by(AgentApproval.requested_at)
    ).all()
    events_by_run: dict[uuid.UUID, list[AgentEvent]] = {}
    approvals_by_run: dict[uuid.UUID, list[AgentApproval]] = {}
    for event in events:
        events_by_run.setdefault(event.run_id, []).append(event)
    for approval in approvals:
        approvals_by_run.setdefault(approval.run_id, []).append(approval)
    return [
        build_run_detail(run, events_by_run.get(run.id, []), approvals_by_run.get(run.id, []))
        for run in runs
    ]


@router.get("/runs")
def list_runs(
    run_status: str | None = Query(default=None, alias="status"),
    conversation_id: uuid.UUID | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    current: CurrentUser = Depends(require_roles("admin", "agent", "viewer")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, list[AgentRunSummary]]:
    query = select(AgentRun).where(AgentRun.workspace_id == current.workspace.id)
    if run_status:
        if run_status not in ALLOWED_STATUSES:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid status")
        query = query.where(AgentRun.status == run_status)
    if conversation_id:
        query = query.where(AgentRun.conversation_id == conversation_id)
    runs = db.scalars(query.order_by(AgentRun.created_at.desc()).limit(limit)).all()
    return {"data": [AgentRunSummary.model_validate(run, from_attributes=True) for run in runs]}


@router.get("/runs/{run_id}")
def get_run(
    run_id: uuid.UUID,
    current: CurrentUser = Depends(require_roles("admin", "agent", "viewer")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, AgentRunDetail]:
    run = _get_run(run_id, current, db)
    return {"data": _serialize(db, [run])[0]}


@router.post("/runs/{run_id}/approve")
def approve_run(
    run_id: uuid.UUID,
    payload: AgentDecisionRequest,
    current: CurrentUser = Depends(require_roles("admin", "agent")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, AgentRunDetail]:
    return _decide(run_id, payload, current, db, approved=True)


@router.post("/runs/{run_id}/reject")
def reject_run(
    run_id: uuid.UUID,
    payload: AgentDecisionRequest,
    current: CurrentUser = Depends(require_roles("admin", "agent")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, AgentRunDetail]:
    return _decide(run_id, payload, current, db, approved=False)


def _decide(
    run_id: uuid.UUID,
    payload: AgentDecisionRequest,
    current: CurrentUser,
    db: Session,
    *,
    approved: bool,
) -> dict[str, AgentRunDetail]:
    _get_run(run_id, current, db)
    try:
        run = resume_run(
            db,
            run_id,
            approved=approved,
            note=payload.note,
            decided_by=current.user,
        )
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ApprovalError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    record_audit(
        db,
        current.workspace.id,
        current.user.id,
        "agent.approval.approve" if approved else "agent.approval.reject",
        "agent_run",
        run.id,
        {"approved": approved, "note": payload.note or ""},
    )
    db.commit()
    db.refresh(run)
    return {"data": _serialize(db, [run])[0]}
