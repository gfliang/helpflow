import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models import Conversation, Message
from app.schemas.public import (
    PublicChatRequest,
    PublicConversationMessage,
    PublicConversationMessagesResponse,
)
from app.services.audit import check_rate_limit
from app.services.chat import (
    ConversationNotFound,
    WorkspaceNotFound,
    get_public_workspace,
    prepare_chat,
    public_workspace_config,
    stream_chat,
)

router = APIRouter(prefix="/public", tags=["public"])

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


@router.get("/workspaces/{slug}")
def get_workspace_config(
    slug: str,
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, object]:
    try:
        workspace = get_public_workspace(db, slug)
    except WorkspaceNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found"
        ) from error
    return {"data": public_workspace_config(workspace)}


@router.post("/workspaces/{slug}/chat")
def chat(
    slug: str,
    payload: PublicChatRequest,
    request: Request,
    db: Session = Depends(get_db),  # noqa: B008
) -> StreamingResponse:
    question = payload.message.strip()
    if not question:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Message cannot be blank"
        )
    identifier = payload.visitor_id or (request.client.host if request.client else "anonymous")
    if not check_rate_limit("chat", identifier, settings.public_chat_limit_per_minute):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="提问过于频繁，请稍后再试。",
        )
    try:
        workspace = get_public_workspace(db, slug)
        plan = prepare_chat(
            db,
            workspace,
            visitor_id=payload.visitor_id,
            conversation_id=payload.conversation_id,
            question=question,
        )
    except WorkspaceNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found"
        ) from error
    except ConversationNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found"
        ) from error
    return StreamingResponse(stream_chat(plan), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/workspaces/{slug}/conversations/{conversation_id}/messages")
def get_conversation_messages(
    slug: str,
    conversation_id: uuid.UUID,
    visitor_id: str = Query(min_length=1, max_length=64),
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, PublicConversationMessagesResponse]:
    try:
        workspace = get_public_workspace(db, slug)
    except WorkspaceNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found"
        ) from error
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.workspace_id == workspace.id,
            Conversation.visitor_id == visitor_id,
        )
    )
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    messages = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation.id, Message.visibility == "public")
        .order_by(Message.created_at.asc())
    ).all()
    return {
        "data": PublicConversationMessagesResponse(
            conversation_id=conversation.id,
            status=conversation.status,
            messages=[
                PublicConversationMessage(
                    id=message.id,
                    role=message.role,
                    content=message.content,
                    created_at=message.created_at,
                )
                for message in messages
            ],
        )
    }
