from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps.auth import CurrentUser, require_roles
from app.db.session import get_db
from app.models import AiCallLog, AuditLog, Conversation, User
from app.schemas.logs import AiCallLogResponse, AuditLogResponse

router = APIRouter(tags=["observability"])


@router.get("/ai-logs")
def list_ai_logs(
    limit: int = Query(default=50, ge=1, le=200),
    success: bool | None = Query(default=None),
    provider: str | None = Query(default=None, max_length=32),
    current: CurrentUser = Depends(require_roles("admin", "agent", "viewer")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, list[AiCallLogResponse]]:
    query = (
        select(AiCallLog, Conversation.subject)
        .outerjoin(Conversation, Conversation.id == AiCallLog.conversation_id)
        .where(AiCallLog.workspace_id == current.workspace.id)
    )
    if success is not None:
        query = query.where(AiCallLog.success.is_(success))
    if provider:
        query = query.where(AiCallLog.provider == provider)
    rows = db.execute(query.order_by(AiCallLog.created_at.desc()).limit(limit)).all()
    return {
        "data": [
            AiCallLogResponse(
                id=log.id,
                conversation_id=log.conversation_id,
                conversation_subject=subject,
                provider=log.provider,
                model=log.model,
                mode=log.mode,
                confidence=log.confidence,
                latency_ms=log.latency_ms,
                success=log.success,
                error=log.error,
                created_at=log.created_at,
            )
            for log, subject in rows
        ]
    }


@router.get("/audit-logs")
def list_audit_logs(
    limit: int = Query(default=50, ge=1, le=200),
    action: str | None = Query(default=None, max_length=64),
    current: CurrentUser = Depends(require_roles("admin")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, list[AuditLogResponse]]:
    query = (
        select(AuditLog, User.name)
        .outerjoin(User, User.id == AuditLog.actor_user_id)
        .where(AuditLog.workspace_id == current.workspace.id)
    )
    if action:
        query = query.where(AuditLog.action == action)
    rows = db.execute(query.order_by(AuditLog.created_at.desc()).limit(limit)).all()
    return {
        "data": [
            AuditLogResponse(
                id=log.id,
                actor_name=actor_name,
                action=log.action,
                target_type=log.target_type,
                target_id=log.target_id,
                detail=log.detail or {},
                created_at=log.created_at,
            )
            for log, actor_name in rows
        ]
    }
