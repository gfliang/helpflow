"""Agent orchestration: create runs, stream LangGraph events and resume approvals."""

import asyncio
import logging
import threading
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from langgraph.types import Command
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.agents.graph import classify_intent, detect_agent_intent
from app.agents.runtime import get_graph, thread_config
from app.agents.state import AgentState
from app.agents.tools import TOOL_REGISTRY
from app.core.config import settings
from app.db.session import SessionLocal
from app.models import (
    AgentApproval,
    AgentEvent,
    AgentRun,
    AiCallLog,
    Conversation,
    Message,
    User,
)
from app.services.tracing import trace_agent_run

logger = logging.getLogger(__name__)

INTERIM_REFUND_ANSWER = (
    "已收到你的退款申请，订单信息已核验。退款需要人工客服审批，"
    "审批通过后会在 3-10 个工作日内原路退回。你可以在会话中查看审批进度。"
)
FAILURE_ANSWER = "抱歉，这次业务处理没有完成。请稍后重试，或转人工客服。"


class ApprovalError(Exception):
    pass


def _chunk_text(text: str, size: int = 18) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)]


def _next_seq(db: Session, run_id: uuid.UUID) -> int:
    current = db.scalar(select(func.max(AgentEvent.seq)).where(AgentEvent.run_id == run_id))
    return int(current or 0) + 1


def add_event(
    db: Session,
    run: AgentRun,
    event_type: str,
    *,
    name: str | None = None,
    status: str = "ok",
    summary: str | None = None,
    payload: dict[str, object] | None = None,
) -> AgentEvent:
    event = AgentEvent(
        run_id=run.id,
        workspace_id=run.workspace_id,
        seq=_next_seq(db, run.id),
        type=event_type,
        name=name,
        status=status,
        summary=summary,
        payload=payload or {},
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def create_run(
    db: Session,
    conversation: Conversation,
    question: str,
) -> AgentRun:
    run_id = uuid.uuid4()
    run = AgentRun(
        id=run_id,
        workspace_id=conversation.workspace_id,
        conversation_id=conversation.id,
        thread_id=run_id.hex,
        question=question,
        intent=classify_intent(question),
        status="running",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _initial_state(run: AgentRun, history: list[dict[str, str]], visitor_id: str) -> AgentState:
    return {
        "workspace_id": str(run.workspace_id),
        "conversation_id": str(run.conversation_id),
        "visitor_id": visitor_id,
        "question": run.question,
        "history": history,
        "intent": run.intent or "knowledge",
        "plan": [],
        "plan_index": 0,
        "steps": [],
        "context": [],
        "citations": [],
        "answer": "",
        "outcome": "",
    }


def _conversation_history(db: Session, run: AgentRun) -> list[dict[str, str]]:
    rows = db.scalars(
        select(Message)
        .where(Message.conversation_id == run.conversation_id)
        .order_by(Message.created_at.desc())
        .limit(settings.chat_history_limit + 1)
    ).all()
    messages = list(reversed(rows))
    # 最新一条访客消息就是本轮问题；run.question 可能是结合上下文改写后的检索问题。
    if messages and messages[-1].role == "visitor":
        messages = messages[:-1]
    return [{"role": message.role, "content": message.content} for message in messages]


def _persist_message(
    run_id: uuid.UUID,
    content: str,
    citations: list[dict[str, object]],
    *,
    status: str,
    latency_ms: int,
) -> uuid.UUID | None:
    with SessionLocal() as db:
        run = db.get(AgentRun, run_id)
        if run is None:
            return None
        message = Message(
            conversation_id=run.conversation_id,
            workspace_id=run.workspace_id,
            role="assistant",
            content=content,
            confidence=None,
            citations=citations,
            metadata_={
                "source": "agent",
                "agent_run_id": str(run.id),
                "status": status,
            },
        )
        db.add(message)
        db.flush()
        db.add(
            AiCallLog(
                workspace_id=run.workspace_id,
                conversation_id=run.conversation_id,
                message_id=message.id,
                provider="langgraph",
                model="langgraph",
                mode="agent",
                confidence=None,
                latency_ms=latency_ms,
                success=status != "failed",
            )
        )
        conversation = db.get(Conversation, run.conversation_id)
        if conversation is not None:
            conversation.last_message_at = datetime.now(UTC)
        db.commit()
        db.refresh(message)
        return message.id


def _extract_interrupt(chunk: dict) -> dict[str, object] | None:
    interrupts = chunk.get("__interrupt__")
    if not interrupts:
        return None
    first = interrupts[0] if isinstance(interrupts, (list, tuple)) else interrupts
    value = getattr(first, "value", first)
    return value if isinstance(value, dict) else {}


def _step_events(step: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
    name = str(step.get("name", "tool"))
    arguments = step.get("arguments") or {}
    call_event = {
        "type": "tool_call",
        "name": name,
        "status": "running",
        "summary": f"调用工具 {name}",
        "payload": {"arguments": arguments},
    }
    result_event = {
        "type": "tool_result",
        "name": name,
        "status": str(step.get("status", "ok")),
        "summary": str(step.get("summary", "")),
        "payload": {
            "data": step.get("payload", {}),
            "duration_ms": step.get("duration_ms", 0),
        },
    }
    return call_event, result_event


def _record_step_events(db: Session, run: AgentRun, event: dict[str, object]) -> None:
    add_event(
        db,
        run,
        str(event["type"]),
        name=str(event.get("name") or "") or None,
        status=str(event.get("status", "ok")),
        summary=str(event.get("summary") or "") or None,
        payload=dict(event.get("payload") or {}),
    )


async def _iterate_in_thread(factory: Any) -> AsyncIterator[dict]:
    """Bridge a sync LangGraph stream into the async SSE generator.

    LangGraph's PostgresSaver only implements the sync checkpointer API, so
    ``astream`` raises ``NotImplementedError``. Running ``graph.stream`` in a
    worker thread keeps the event loop responsive and works with both savers.
    """
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()

    def run() -> None:
        try:
            for chunk in factory():
                loop.call_soon_threadsafe(queue.put_nowait, ("chunk", chunk))
        except BaseException as error:  # noqa: BLE001 - propagate to the consumer
            loop.call_soon_threadsafe(queue.put_nowait, ("error", error))
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, ("end", None))

    threading.Thread(target=run, daemon=True).start()
    while True:
        kind, payload = await queue.get()
        if kind == "chunk":
            yield payload  # type: ignore[misc]
        elif kind == "error":
            raise payload  # type: ignore[misc]
        else:
            return


async def astream_run(run_id: uuid.UUID | str) -> AsyncIterator[dict[str, object]]:
    run_uuid = uuid.UUID(str(run_id))
    with SessionLocal() as db:
        run = db.get(AgentRun, run_uuid)
        if run is None:
            yield {"event": "finished", "status": "failed", "message_id": None}
            return
        history = _conversation_history(db, run)
        conversation = db.get(Conversation, run.conversation_id)
        visitor_id = conversation.visitor_id if conversation else ""
        thread_id = run.thread_id

    graph = get_graph()
    config = thread_config(thread_id)
    state = _initial_state(run, history, visitor_id)
    started = time.perf_counter()
    steps_seen = 0
    citations: list[dict[str, object]] = []
    answer = ""
    outcome = ""
    interrupted = False

    try:
        stream = _iterate_in_thread(
            lambda: graph.stream(state, config, stream_mode="updates")
        )
        async for chunk in stream:
            interrupt_value = _extract_interrupt(chunk)
            if interrupt_value is not None:
                arguments = dict(interrupt_value.get("arguments") or {})
                with SessionLocal() as db:
                    run = db.get(AgentRun, run_uuid)
                    approval = AgentApproval(
                        run_id=run_uuid,
                        workspace_id=run.workspace_id,
                        tool_name=str(interrupt_value.get("tool", "request_refund")),
                        arguments=arguments,
                        status="pending",
                    )
                    db.add(approval)
                    run.status = "waiting_approval"
                    run.answer = INTERIM_REFUND_ANSWER
                    run.intent = "refund"
                    db.commit()
                    db.refresh(approval)
                    add_event(
                        db,
                        run,
                        "approval_required",
                        name=approval.tool_name,
                        status="pending",
                        summary="退款申请等待人工审批",
                        payload={"approval_id": str(approval.id), **arguments},
                    )
                    approval_id = str(approval.id)
                    tool_name = approval.tool_name
                latency_ms = int((time.perf_counter() - started) * 1000)
                message_id = _persist_message(
                    run_uuid,
                    INTERIM_REFUND_ANSWER,
                    citations,
                    status="waiting_approval",
                    latency_ms=latency_ms,
                )
                yield {
                    "event": "approval_required",
                    "approval_id": approval_id,
                    "run_id": str(run_uuid),
                    "tool": tool_name,
                    "arguments": arguments,
                }
                for piece in _chunk_text(INTERIM_REFUND_ANSWER):
                    yield {"event": "delta", "text": piece}
                yield {"event": "citations", "citations": citations}
                yield {
                    "event": "finished",
                    "status": "waiting_approval",
                    "message_id": str(message_id) if message_id else None,
                    "citations": citations,
                    "answer": INTERIM_REFUND_ANSWER,
                }
                interrupted = True
                break

            for node, update in chunk.items():
                if not isinstance(update, dict):
                    continue
                if "steps" in update:
                    steps = update["steps"]
                    for step in steps[steps_seen:]:
                        call_event, result_event = _step_events(step)
                        with SessionLocal() as db:
                            run = db.get(AgentRun, run_uuid)
                            _record_step_events(db, run, call_event)
                            _record_step_events(db, run, result_event)
                        yield {"event": "step", "data": call_event, "run_id": str(run_uuid)}
                        yield {"event": "step", "data": result_event, "run_id": str(run_uuid)}
                    steps_seen = len(steps)
                if "citations" in update:
                    citations = update["citations"]
                if update.get("intent"):
                    with SessionLocal() as db:
                        run = db.get(AgentRun, run_uuid)
                        run.intent = str(update["intent"])
                        db.commit()
                if node == "respond":
                    answer = str(update.get("answer", ""))
                    outcome = str(update.get("outcome", ""))
    except Exception as error:
        logger.exception("Agent run %s failed", run_uuid)
        with SessionLocal() as db:
            run = db.get(AgentRun, run_uuid)
            if run is not None:
                run.status = "failed"
                run.error = str(error)[:2000]
                run.finished_at = datetime.now(UTC)
                add_event(db, run, "error", status="failed", summary=str(error)[:500])
                db.commit()
        latency_ms = int((time.perf_counter() - started) * 1000)
        message_id = _persist_message(
            run_uuid, FAILURE_ANSWER, citations, status="failed", latency_ms=latency_ms
        )
        for piece in _chunk_text(FAILURE_ANSWER):
            yield {"event": "delta", "text": piece}
        yield {"event": "finished", "status": "failed", "message_id": str(message_id) if message_id else None}
        return

    if interrupted:
        return

    latency_ms = int((time.perf_counter() - started) * 1000)
    status = "rejected" if outcome == "refund_rejected" else "completed"
    if not answer:
        answer = FAILURE_ANSWER
        status = "failed"
    with SessionLocal() as db:
        run = db.get(AgentRun, run_uuid)
        if run is None:
            yield {"event": "finished", "status": "failed", "message_id": None}
            return
        run.status = status
        run.answer = answer
        run.citations = citations
        run.latency_ms = latency_ms
        run.finished_at = datetime.now(UTC)
        db.commit()
        trace_agent_run(
            "agent_run",
            str(run.id),
            {
                "workspace_id": str(run.workspace_id),
                "intent": run.intent,
                "status": status,
                "latency_ms": latency_ms,
            },
            answer,
        )
    message_id = _persist_message(run_uuid, answer, citations, status=status, latency_ms=latency_ms)
    for piece in _chunk_text(answer):
        yield {"event": "delta", "text": piece}
    yield {"event": "citations", "citations": citations}
    yield {
        "event": "finished",
        "status": status,
        "message_id": str(message_id) if message_id else None,
        "citations": citations,
        "answer": answer,
    }


def _consume_resume(run: AgentRun, graph, config: dict, decision: dict) -> tuple[str, str, list[dict]]:
    answer = ""
    outcome = ""
    citations: list[dict[str, object]] = []
    steps_seen = 0
    for chunk in graph.stream(Command(resume=decision), config, stream_mode="updates"):
        interrupt_value = _extract_interrupt(chunk)
        if interrupt_value is not None:
            continue
        for node, update in chunk.items():
            if not isinstance(update, dict):
                continue
            if "steps" in update:
                for step in update["steps"][steps_seen:]:
                    call_event, result_event = _step_events(step)
                    with SessionLocal() as db:
                        current = db.get(AgentRun, run.id)
                        _record_step_events(db, current, call_event)
                        _record_step_events(db, current, result_event)
                steps_seen = len(update["steps"])
            if "citations" in update:
                citations = update["citations"]
            if node == "respond":
                answer = str(update.get("answer", ""))
                outcome = str(update.get("outcome", ""))
    return answer, outcome, citations


def _has_checkpoint(graph: Any, config: dict) -> bool:
    try:
        snapshot = graph.get_state(config)
    except Exception:  # noqa: BLE001 - missing checkpoint must not block approval
        return False
    return bool(getattr(snapshot, "values", None))


def _finish_seeded_resume(
    db: Session,
    run: AgentRun,
    approval: AgentApproval,
    *,
    approved: bool,
    note: str | None,
    decided_by: User,
    started: float,
) -> AgentRun:
    """Complete an approval for runs without a saved graph checkpoint.

    Seed data and historical imports have AgentRun rows but no LangGraph
    checkpoint, so ``Command(resume=...)`` has nothing to resume. Apply the
    decision directly instead of leaving the run stuck in ``waiting_approval``.
    """
    arguments = dict(approval.arguments or {})
    order_no = str(arguments.get("order_no") or "")
    reason = str(arguments.get("reason") or "访客申请退款")
    citations: list[dict[str, object]] = []

    if approved and order_no:
        result = TOOL_REGISTRY["request_refund"](
            db,
            run.workspace_id,
            conversation_id=str(run.conversation_id),
            order_no=order_no,
            reason=reason,
            decided_by=decided_by.name,
            note=note,
        )
        step = {
            "name": "request_refund",
            "status": str(result.get("status", "ok")),
            "summary": str(result.get("summary", "")),
            "payload": result.get("data", {}),
            "arguments": {"order_no": order_no, "reason": reason},
        }
        for event in _step_events(step):
            _record_step_events(db, run, event)
        answer = str(result.get("summary", "")) or FAILURE_ANSWER
        status = "completed" if result.get("status") == "ok" else "failed"
        if note:
            answer = f"{answer}\n\n客服备注：{note}"
    elif approved:
        answer, status = FAILURE_ANSWER, "failed"
    else:
        answer = "退款申请未通过审批。" + (
            f"客服备注：{note}。" if note else "如需进一步说明，可以转人工客服。"
        )
        status = "rejected"

    latency_ms = int((time.perf_counter() - started) * 1000)
    run.status = status
    run.answer = answer
    run.citations = citations
    run.latency_ms = latency_ms
    run.finished_at = datetime.now(UTC)
    db.commit()
    _persist_message(run.id, answer, citations, status=status, latency_ms=latency_ms)
    trace_agent_run(
        "agent_approval",
        str(run.id),
        {
            "workspace_id": str(run.workspace_id),
            "status": status,
            "approved": approved,
            "decided_by": decided_by.name,
        },
        answer,
    )
    db.refresh(run)
    return run


def resume_run(
    db: Session,
    run_id: uuid.UUID,
    *,
    approved: bool,
    note: str | None,
    decided_by: User,
) -> AgentRun:
    run = db.get(AgentRun, run_id)
    if run is None:
        raise LookupError("agent run not found")
    approval = db.scalar(
        select(AgentApproval)
        .where(AgentApproval.run_id == run.id, AgentApproval.status == "pending")
        .order_by(AgentApproval.requested_at.desc())
    )
    if approval is None:
        raise ApprovalError("该运行没有待审批的请求")
    if run.status != "waiting_approval":
        raise ApprovalError("该运行不在等待审批状态")

    approval.status = "approved" if approved else "rejected"
    approval.note = note
    approval.decided_by_user_id = decided_by.id
    approval.decided_at = datetime.now(UTC)
    run.status = "running"
    db.commit()
    add_event(
        db,
        run,
        "approval_decided",
        name=approval.tool_name,
        status=approval.status,
        summary=f"{decided_by.name} {'通过' if approved else '拒绝'}了退款申请",
        payload={"note": note or "", "decided_by": decided_by.name},
    )

    started = time.perf_counter()
    graph = get_graph()
    config = thread_config(run.thread_id)
    if not _has_checkpoint(graph, config):
        logger.info("No checkpoint for run %s; applying approval directly", run_id)
        return _finish_seeded_resume(
            db,
            run,
            approval,
            approved=approved,
            note=note,
            decided_by=decided_by,
            started=started,
        )
    try:
        answer, outcome, citations = _consume_resume(
            run,
            graph,
            config,
            {"approved": approved, "note": note or "", "decided_by": decided_by.name},
        )
    except Exception as error:
        logger.exception("Agent resume %s failed", run_id)
        run = db.get(AgentRun, run.id)
        run.status = "failed"
        run.error = str(error)[:2000]
        run.finished_at = datetime.now(UTC)
        add_event(db, run, "error", status="failed", summary=str(error)[:500])
        db.commit()
        return run

    latency_ms = int((time.perf_counter() - started) * 1000)
    status = "rejected" if (not approved or outcome == "refund_rejected") else "completed"
    if not answer:
        answer = FAILURE_ANSWER
        status = "failed"
    run = db.get(AgentRun, run.id)
    run.status = status
    run.answer = answer
    run.citations = citations
    run.latency_ms = latency_ms
    run.finished_at = datetime.now(UTC)
    db.commit()
    _persist_message(run.id, answer, citations, status=status, latency_ms=latency_ms)
    trace_agent_run(
        "agent_approval",
        str(run.id),
        {
            "workspace_id": str(run.workspace_id),
            "status": status,
            "approved": approved,
            "decided_by": decided_by.name,
        },
        answer,
    )
    db.refresh(run)
    return run


__all__ = [
    "ApprovalError",
    "add_event",
    "astream_run",
    "create_run",
    "detect_agent_intent",
    "resume_run",
]
