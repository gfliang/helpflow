"""Public AI Q&A: retrieval, guardrails, citations and SSE streaming."""

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.service import astream_run, create_run, detect_agent_intent
from app.core.config import settings
from app.db.session import SessionLocal
from app.models import AiCallLog, Conversation, Message, Workspace
from app.providers.chat import (
    ChatProvider,
    ChatTurn,
    ContextItem,
    ProviderError,
    build_chat_provider,
)
from app.services.moderation import contains_sensitive_word, is_handoff_request
from app.services.rag import condense_question, docs_to_context
from app.services.retrieval import retrieve_documents

logger = logging.getLogger(__name__)

DEFAULT_GREETING = "你好，我是 HelpFlow 智能助手。可以问我产品、价格、试用、退款或接入相关的问题。"
DEFAULT_PRESET_QUESTIONS = [
    "专业版包含哪些功能？",
    "可以免费试用多久？",
    "年度订阅怎么退款？",
    "如何把聊天组件嵌入网站？",
]
DEFAULT_HANDOFF_NOTE = "已为你转接人工客服，客服会在工作时间（周一至周五 9:00-18:00）尽快回复。"

REFUSAL_ANSWER = (
    "抱歉，我在已发布的知识库中没有找到足够可靠的信息，因此不能凭空回答。\n\n"
    "你可以换个说法继续提问，或点击「转人工客服」让同事进一步确认。"
)
SENSITIVE_ANSWER = (
    "抱歉，我无法处理包含不友善或敏感内容的提问。\n\n请调整措辞后再试，或点击「转人工客服」联系人工客服。"
)
HANDOFF_ANSWER = (
    "好的，正在为你转接人工客服。\n\n"
    "请补充你的具体问题和联系方式，客服会在工作时间（周一至周五 9:00-18:00）尽快回复。"
)
UNAVAILABLE_ANSWER = "\n\n（模型服务暂时不可用，请稍后重试，或转人工客服。）"

MODE_ANSWER = "answer"
MODE_AGENT = "agent"
MODE_REFUSED = "refused"
MODE_HANDOFF = "handoff"
MODE_BLOCKED = "blocked"
MODE_WAITING = "human_waiting"

HUMAN_WAITING_ANSWER = "已收到你的补充，当前会话已转人工，客服会尽快回复你。"


class WorkspaceNotFound(Exception):
    pass


class ConversationNotFound(Exception):
    pass


@dataclass(frozen=True)
class ChatPlan:
    conversation_id: uuid.UUID
    workspace_id: uuid.UUID
    visitor_id: str
    question: str
    mode: str
    confidence: float
    context: list[ContextItem]
    citations: list[dict[str, object]]
    history: list[ChatTurn]
    provider: ChatProvider
    agent_run_id: uuid.UUID | None = None


def _workspace_settings(workspace: Workspace) -> dict[str, object]:
    try:
        parsed = json.loads(workspace.settings or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def public_workspace_config(workspace: Workspace) -> dict[str, object]:
    workspace_settings = _workspace_settings(workspace)
    presets = workspace_settings.get("preset_questions")
    greeting = workspace_settings.get("greeting")
    return {
        "slug": workspace.slug,
        "name": workspace.name,
        "greeting": greeting if isinstance(greeting, str) and greeting else DEFAULT_GREETING,
        "preset_questions": presets if isinstance(presets, list) and presets else DEFAULT_PRESET_QUESTIONS,
        "handoff_note": DEFAULT_HANDOFF_NOTE,
    }


def get_public_workspace(db: Session, slug: str) -> Workspace:
    workspace = db.scalar(select(Workspace).where(Workspace.slug == slug))
    if workspace is None:
        raise WorkspaceNotFound(slug)
    return workspace


def _resolve_conversation(
    db: Session,
    workspace: Workspace,
    visitor_id: str | None,
    conversation_id: uuid.UUID | None,
    question: str,
) -> Conversation:
    conversation: Conversation | None = None
    if conversation_id is not None:
        conversation = db.scalar(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.workspace_id == workspace.id,
            )
        )
        if conversation is None or visitor_id is None or conversation.visitor_id != visitor_id:
            raise ConversationNotFound(str(conversation_id))
    else:
        conversation = Conversation(
            workspace_id=workspace.id,
            visitor_id=visitor_id or f"anon-{uuid.uuid4().hex[:20]}",
            channel="web",
            status="active",
            subject=question[:120],
        )
        db.add(conversation)
        db.flush()
    return conversation


def _history(db: Session, conversation_id: uuid.UUID) -> list[ChatTurn]:
    rows = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(settings.chat_history_limit)
    ).all()
    return [ChatTurn(role=message.role, content=message.content) for message in reversed(rows)]


def prepare_chat(
    db: Session,
    workspace: Workspace,
    visitor_id: str | None,
    conversation_id: uuid.UUID | None,
    question: str,
) -> ChatPlan:
    conversation = _resolve_conversation(db, workspace, visitor_id, conversation_id, question)
    history = _history(db, conversation.id)
    # Follow-ups such as "那退款呢" are rewritten with the recent turns before retrieval.
    search_query = condense_question(question, history)

    blocked = contains_sensitive_word(question)
    handoff = not blocked and is_handoff_request(question)
    context: list[ContextItem] = []
    citations: list[dict[str, object]] = []
    confidence = 0.0
    agent_run_id: uuid.UUID | None = None

    if blocked:
        mode = MODE_BLOCKED
    elif handoff:
        mode = MODE_HANDOFF
    elif conversation.status in {"waiting_human", "human"}:
        mode = MODE_WAITING
    elif settings.agent_enabled and detect_agent_intent(search_query):
        mode = MODE_AGENT
    else:
        documents = retrieve_documents(
            db, workspace.id, search_query, limit=settings.chat_context_limit
        )
        context, citations, confidence = docs_to_context(documents)
        if not documents or confidence < settings.chat_confidence_threshold:
            mode = MODE_REFUSED
        else:
            mode = MODE_ANSWER

    db.add(
        Message(
            conversation_id=conversation.id,
            workspace_id=workspace.id,
            role="visitor",
            content=question,
            metadata_={"mode": mode},
        )
    )
    conversation.last_message_at = datetime.now(UTC)
    if mode == MODE_HANDOFF:
        conversation.status = "waiting_human"
        conversation.metadata_ = {
            **conversation.metadata_,
            "handoff_requested_at": datetime.now(UTC).isoformat(),
        }
    db.commit()

    if mode == MODE_AGENT:
        agent_run_id = create_run(db, conversation, search_query).id

    return ChatPlan(
        conversation_id=conversation.id,
        workspace_id=workspace.id,
        visitor_id=conversation.visitor_id,
        question=question,
        mode=mode,
        confidence=round(confidence, 4),
        context=context,
        citations=citations,
        history=history,
        provider=build_chat_provider(),
        agent_run_id=agent_run_id,
    )


def _sse(event: str, payload: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _stream_text(text: str, chunk_size: int = 14, delay_seconds: float = 0.006):
    for start in range(0, len(text), chunk_size):
        yield text[start : start + chunk_size]
        if delay_seconds:
            await asyncio.sleep(delay_seconds)


def _persist_assistant(
    plan: ChatPlan,
    content: str,
    latency_ms: int,
    success: bool = True,
    provider_error: str | None = None,
) -> uuid.UUID | None:
    with SessionLocal() as db:
        conversation = db.get(Conversation, plan.conversation_id)
        if conversation is None:
            return None
        message = Message(
            conversation_id=plan.conversation_id,
            workspace_id=plan.workspace_id,
            role="assistant",
            content=content,
            confidence=plan.confidence if plan.mode == MODE_ANSWER else None,
            citations=plan.citations,
            metadata_={
                "mode": plan.mode,
                "provider": plan.provider.name,
                "handoff_suggested": plan.mode == MODE_REFUSED,
            },
        )
        db.add(message)
        db.flush()
        used_provider = plan.mode == MODE_ANSWER
        db.add(
            AiCallLog(
                workspace_id=plan.workspace_id,
                conversation_id=plan.conversation_id,
                message_id=message.id,
                provider=plan.provider.name if used_provider else "rules",
                model=getattr(plan.provider, "model", None) if used_provider else None,
                mode=plan.mode,
                confidence=plan.confidence if plan.mode == MODE_ANSWER else None,
                latency_ms=latency_ms,
                success=success,
                error=provider_error[:255] if provider_error else None,
            )
        )
        conversation.last_message_at = datetime.now(UTC)
        if plan.mode == MODE_HANDOFF:
            conversation.status = "waiting_human"
        db.commit()
        db.refresh(message)
        return message.id


async def stream_chat(plan: ChatPlan):
    meta = {
        "conversation_id": str(plan.conversation_id),
        "visitor_id": plan.visitor_id,
        "provider": plan.provider.name,
        "mode": plan.mode,
        "confidence": plan.confidence,
        "refused": plan.mode == MODE_REFUSED,
        "blocked": plan.mode == MODE_BLOCKED,
        "handoff": plan.mode in {MODE_HANDOFF, MODE_WAITING},
        "handoff_suggested": plan.mode == MODE_REFUSED,
        "agent_run_id": str(plan.agent_run_id) if plan.agent_run_id else None,
    }
    yield _sse("meta", meta)

    if plan.mode == MODE_AGENT and plan.agent_run_id is not None:
        final_status = "failed"
        agent_citations: list[dict[str, object]] = []
        agent_message_id: str | None = None
        async for event in astream_run(plan.agent_run_id):
            kind = event.get("event")
            if kind == "step":
                yield _sse("agent_step", {"run_id": str(plan.agent_run_id), **event["data"]})
            elif kind == "approval_required":
                yield _sse("approval_required", {key: value for key, value in event.items() if key != "event"})
            elif kind == "delta":
                yield _sse("delta", {"text": event.get("text", "")})
            elif kind == "citations":
                agent_citations = event.get("citations", [])
                yield _sse("citations", {"citations": agent_citations})
            elif kind == "finished":
                final_status = str(event.get("status", "failed"))
                agent_message_id = event.get("message_id")  # type: ignore[assignment]
        yield _sse(
            "done",
            {
                "conversation_id": str(plan.conversation_id),
                "message_id": agent_message_id,
                "provider": "langgraph",
                "mode": MODE_AGENT,
                "confidence": plan.confidence,
                "refused": final_status in {"failed", "rejected"},
                "blocked": False,
                "handoff": False,
                "handoff_suggested": False,
                "agent_run_id": str(plan.agent_run_id),
                "agent_status": final_status,
                "citations": agent_citations,
            },
        )
        return

    collected: list[str] = []
    message_id: uuid.UUID | None = None
    provider_error: str | None = None
    started = time.perf_counter()

    async def emit(text: str) -> None:
        collected.append(text)

    try:
        if plan.mode == MODE_ANSWER:
            try:
                async for piece in plan.provider.stream_answer(
                    plan.question, plan.context, plan.history
                ):
                    await emit(piece)
                    yield _sse("delta", {"text": piece})
            except ProviderError as error:
                provider_error = str(error)
                logger.warning("Chat provider failed: %s", error)
                await emit(UNAVAILABLE_ANSWER)
                yield _sse("delta", {"text": UNAVAILABLE_ANSWER})
        else:
            fixed = {
                MODE_REFUSED: REFUSAL_ANSWER,
                MODE_BLOCKED: SENSITIVE_ANSWER,
                MODE_HANDOFF: HANDOFF_ANSWER,
                MODE_WAITING: HUMAN_WAITING_ANSWER,
            }[plan.mode]
            async for piece in _stream_text(fixed):
                await emit(piece)
                yield _sse("delta", {"text": piece})
    finally:
        if collected:
            latency_ms = int((time.perf_counter() - started) * 1000)
            message_id = _persist_assistant(
                plan,
                "".join(collected),
                latency_ms=latency_ms,
                success=provider_error is None,
                provider_error=provider_error,
            )

    yield _sse("citations", {"citations": plan.citations})
    if plan.mode == MODE_HANDOFF:
        yield _sse("handoff", {"status": "waiting_human", "note": DEFAULT_HANDOFF_NOTE})
    yield _sse(
        "done",
        {
            "conversation_id": str(plan.conversation_id),
            "message_id": str(message_id) if message_id else None,
            "provider": plan.provider.name,
            "mode": plan.mode,
            "confidence": plan.confidence,
            "refused": plan.mode == MODE_REFUSED,
            "blocked": plan.mode == MODE_BLOCKED,
            "handoff": plan.mode in {MODE_HANDOFF, MODE_WAITING},
            "handoff_suggested": plan.mode == MODE_REFUSED,
        },
    )
