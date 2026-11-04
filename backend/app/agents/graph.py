"""LangGraph agent: plan → tool → human approval → grounded response."""

import json
import logging
import re
import time
import uuid
from typing import Any

from langchain_core.prompts import ChatPromptTemplate
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from app.agents.state import AgentState
from app.agents.tools import TOOL_REGISTRY
from app.core.config import settings
from app.db.session import SessionLocal
from app.providers.types import ChatTurn
from app.services.rag import answer_with_tools

logger = logging.getLogger(__name__)

ORDER_NO_PATTERN = re.compile(r"\b([A-Za-z]{2,}(?:-[A-Za-z0-9]+)+)\b")
EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

REFUND_WORDS = ("退款", "退钱", "退订", "退货", "退费")
ORDER_WORDS = ("订单", "物流", "发货", "快递", "签收", "购买记录")
TICKET_WORDS = ("工单", "投诉", "报障", "故障", "售后")
ACCOUNT_WORDS = ("发票", "账单", "账户", "账号")

TOOL_DESCRIPTIONS = (
    "可用工具：\n"
    "- search_knowledge(query): 检索已发布知识库\n"
    "- get_customer(email, visitor_id): 查询客户档案\n"
    "- list_orders(email, customer_id): 查询客户订单列表\n"
    "- get_order(order_no): 查询单个订单\n"
    "- check_refund_eligibility(order_no): 检查退款资格\n"
    "- create_ticket(title, description): 创建售后工单\n"
    "- request_refund(order_no, reason): 提交退款（必须人工审批）\n"
    "- handoff_to_human(reason): 转人工客服\n"
)

PLANNER_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "你是 HelpFlow 的业务规划器。根据访客问题选择最少必要的工具，"
            "输出严格 JSON：{{\"intent\":\"refund|order|ticket|knowledge\","
            "\"tools\":[{{\"name\":\"工具名\",\"arguments\":{{}}}}]}}。"
            "退款必须先调用 check_refund_eligibility，再调用 request_refund；"
            "没有订单号时不要调用退款工具。不要输出 JSON 以外的内容。\n" + TOOL_DESCRIPTIONS,
        ),
        ("human", "访客问题：{question}"),
    ]
)


def classify_intent(question: str) -> str | None:
    text = question.strip()
    if not text:
        return None
    if any(word in text for word in REFUND_WORDS):
        return "refund"
    if any(word in text for word in ORDER_WORDS):
        return "order"
    if any(word in text for word in TICKET_WORDS):
        return "ticket"
    if any(word in text for word in ACCOUNT_WORDS):
        return "knowledge"
    return None


def detect_agent_intent(question: str) -> str | None:
    """Only business intents enter the agent; general questions stay on fast RAG."""
    return classify_intent(question)


def extract_order_no(question: str) -> str | None:
    for match in ORDER_NO_PATTERN.finditer(question):
        candidate = match.group(1).strip()
        if any(character.isdigit() for character in candidate):
            return candidate.upper()
    return None


def extract_email(question: str) -> str | None:
    match = EMAIL_PATTERN.search(question)
    return match.group(0).lower() if match else None


def _rule_plan(question: str) -> tuple[str, list[dict[str, object]]]:
    intent = classify_intent(question) or "knowledge"
    order_no = extract_order_no(question)
    email = extract_email(question)

    if intent == "refund":
        if order_no:
            return intent, [
                {"name": "check_refund_eligibility", "arguments": {"order_no": order_no}},
                {"name": "request_refund", "arguments": {"order_no": order_no, "reason": question}},
            ]
        return intent, [
            {"name": "search_knowledge", "arguments": {"query": "退款与取消政策"}},
        ]
    if intent == "order":
        if order_no:
            return intent, [{"name": "get_order", "arguments": {"order_no": order_no}}]
        if email:
            return intent, [{"name": "list_orders", "arguments": {"email": email}}]
        return intent, [{"name": "list_orders", "arguments": {}}]
    if intent == "ticket":
        return intent, [
            {
                "name": "create_ticket",
                "arguments": {
                    "title": question[:80],
                    "description": question,
                    "priority": "high" if "紧急" in question else "normal",
                },
            }
        ]
    return intent, [{"name": "search_knowledge", "arguments": {"query": question}}]


def _llm_plan(question: str) -> tuple[str, list[dict[str, object]]] | None:
    if not settings.agent_use_llm:
        return None
    try:
        from app.services.rag import build_chat_model

        model = build_chat_model(temperature=0.0, streaming=False)
        raw = (PLANNER_PROMPT | model).invoke({"question": question}).content
        text = str(raw).strip().strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
        payload = json.loads(text)
        intent = str(payload.get("intent", "knowledge"))
        tools = payload.get("tools")
        if not isinstance(tools, list) or not tools:
            return None
        plan: list[dict[str, object]] = []
        for item in tools[: settings.agent_max_steps]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", ""))
            if name not in TOOL_REGISTRY:
                continue
            arguments = item.get("arguments")
            plan.append({"name": name, "arguments": arguments if isinstance(arguments, dict) else {}})
        return (intent, plan) if plan else None
    except Exception as error:  # noqa: BLE001 - LLM planning is best-effort
        logger.warning("Agent LLM planning failed, using rules: %s", error)
        return None


def _validated_plan(question: str) -> tuple[str, list[dict[str, object]]]:
    planned = _llm_plan(question)
    intent, plan = planned or _rule_plan(question)
    order_no = extract_order_no(question)
    allowed: list[dict[str, object]] = []
    for call in plan:
        name = call["name"]
        if name == "request_refund":
            if not order_no:
                continue
            if not any(item["name"] == "check_refund_eligibility" for item in allowed):
                allowed.append(
                    {"name": "check_refund_eligibility", "arguments": {"order_no": order_no}}
                )
            call = {"name": name, "arguments": {**call["arguments"], "order_no": order_no}}
        allowed.append(call)
    # 退款意图且带订单号时必须走到审批环节：LLM 规划器偶尔只查资格就结束，
    # 会导致回复谎称"已提交审批"但实际没有审批单。
    if (
        classify_intent(question) == "refund"
        and order_no
        and not any(item["name"] == "request_refund" for item in allowed)
    ):
        if not any(item["name"] == "check_refund_eligibility" for item in allowed):
            allowed.append(
                {"name": "check_refund_eligibility", "arguments": {"order_no": order_no}}
            )
        allowed.append(
            {"name": "request_refund", "arguments": {"order_no": order_no, "reason": question}}
        )
        intent = "refund"
    if len(allowed) > settings.agent_max_steps and any(
        item["name"] == "request_refund" for item in allowed
    ):
        # 步数上限不能挤掉退款链路，其余工具让位。
        allowed = [
            item
            for item in allowed
            if item["name"] in {"check_refund_eligibility", "request_refund"}
        ]
    return intent, allowed[: settings.agent_max_steps]


def _step(
    name: str,
    result: dict[str, object],
    duration_ms: int,
    arguments: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "name": name,
        "status": str(result.get("status", "ok")),
        "summary": str(result.get("summary", "")),
        "payload": result.get("data", {}),
        "arguments": arguments or {},
        "duration_ms": duration_ms,
    }


def _state_ids(state: AgentState) -> tuple[uuid.UUID, str | None, str]:
    workspace_id = uuid.UUID(state["workspace_id"])
    conversation_id = state.get("conversation_id")
    visitor_id = state.get("visitor_id", "")
    return workspace_id, conversation_id, visitor_id


def _tool_arguments(state: AgentState, call: dict[str, object]) -> dict[str, object]:
    arguments = dict(call.get("arguments") or {})
    _workspace_id, conversation_id, visitor_id = _state_ids(state)
    question = state.get("question", "")
    order_no = extract_order_no(question)
    name = str(call["name"])
    if name == "search_knowledge":
        arguments.setdefault("query", question)
    if name in {"get_order", "check_refund_eligibility", "request_refund"} and order_no:
        arguments.setdefault("order_no", order_no)
    if name in {"get_customer", "list_orders"}:
        arguments.setdefault("visitor_id", visitor_id)
    if name == "create_ticket":
        arguments.setdefault("title", question[:80])
        arguments.setdefault("description", question)
        arguments.setdefault("priority", "normal")
    if name in {"create_ticket", "request_refund", "handoff_to_human"}:
        arguments.setdefault("conversation_id", conversation_id)
        if name == "handoff_to_human":
            arguments.setdefault("reason", question)
    return arguments


def plan_node(state: AgentState) -> dict[str, object]:
    plan = state.get("plan")
    index = state.get("plan_index", 0)
    intent = state.get("intent", "knowledge")
    if not plan:
        intent, plan = _validated_plan(state.get("question", ""))
        index = 0
    if index >= len(plan) or index >= settings.agent_max_steps:
        return {"plan": plan, "intent": intent, "plan_index": index, "current_call": None}
    call = plan[index]
    return {
        "plan": plan,
        "intent": intent,
        "plan_index": index + 1,
        "current_call": call,
    }


def route_after_plan(state: AgentState) -> str:
    call = state.get("current_call")
    if not call:
        return "respond"
    if call.get("name") == "request_refund":
        return "request_refund"
    return "run_tool"


def run_tool_node(state: AgentState) -> dict[str, object]:
    call = state["current_call"]
    name = str(call["name"])
    arguments = _tool_arguments(state, call)
    workspace_id, _conversation_id, _ = _state_ids(state)
    started = time.perf_counter()
    with SessionLocal() as db:
        result = TOOL_REGISTRY[name](db, workspace_id, **arguments)
        db.commit()
    duration = int((time.perf_counter() - started) * 1000)
    steps = [*state.get("steps", []), _step(name, result, duration, arguments)]
    context = [*state.get("context", []), *result.get("context", [])]
    citations = [*state.get("citations", []), *result.get("citations", [])]
    return {
        "steps": steps,
        "context": context,
        "citations": citations,
        "current_call": None,
    }


def request_refund_node(state: AgentState) -> dict[str, object]:
    call = state["current_call"]
    arguments = _tool_arguments(state, call)
    prior = next(
        (
            step
            for step in reversed(state.get("steps", []))
            if step.get("name") == "check_refund_eligibility"
        ),
        None,
    )
    if prior is not None and not (prior.get("payload") or {}).get("eligible"):
        return {
            "steps": [
                *state.get("steps", []),
                {
                    "name": "request_refund",
                    "status": "skipped",
                    "summary": "订单不符合退款条件，未提交审批。",
                    "payload": {"eligible": False},
                    "arguments": arguments,
                    "duration_ms": 0,
                },
            ],
            "outcome": "refund_ineligible",
            "current_call": None,
        }
    decision = interrupt(
        {
            "type": "approval_required",
            "tool": "request_refund",
            "arguments": {
                "order_no": arguments.get("order_no"),
                "reason": arguments.get("reason"),
            },
        }
    )
    approved = bool(decision.get("approved")) if isinstance(decision, dict) else False
    note = str(decision.get("note", "")) if isinstance(decision, dict) else ""
    decided_by = str(decision.get("decided_by", "")) if isinstance(decision, dict) else ""
    if not approved:
        step = {
            "name": "request_refund",
            "status": "rejected",
            "summary": f"退款申请未通过审批。{('备注：' + note) if note else ''}",
            "payload": {"approved": False, "note": note},
            "arguments": {"order_no": arguments.get("order_no"), "reason": arguments.get("reason")},
            "duration_ms": 0,
        }
        return {
            "steps": [*state.get("steps", []), step],
            "outcome": "refund_rejected",
            "current_call": None,
        }

    workspace_id, conversation_id, _ = _state_ids(state)
    started = time.perf_counter()
    with SessionLocal() as db:
        result = TOOL_REGISTRY["request_refund"](
            db,
            workspace_id,
            conversation_id=conversation_id,
            order_no=arguments.get("order_no"),
            reason=str(arguments.get("reason", "")),
            decided_by=decided_by,
            note=note,
        )
        db.commit()
    duration = int((time.perf_counter() - started) * 1000)
    return {
        "steps": [*state.get("steps", []), _step("request_refund", result, duration, arguments)],
        "outcome": "refund_completed" if result.get("status") == "ok" else "refund_failed",
        "current_call": None,
    }


def _template_answer(state: AgentState) -> str:
    question = state.get("question", "")
    steps = state.get("steps", [])
    outcome = state.get("outcome", "")
    if outcome == "refund_rejected":
        last = steps[-1] if steps else {}
        note = (last.get("payload") or {}).get("note") if isinstance(last, dict) else ""
        return (
            "退款申请未通过审批。"
            + (f"客服备注：{note}。" if note else "如需进一步说明，可以转人工客服。")
        )
    if not steps:
        return "抱歉，这次没有获取到可用的业务信息。你可以补充订单号、下单邮箱，或转人工客服。"

    last = steps[-1]
    name = str(last.get("name", ""))
    summary = str(last.get("summary", ""))
    if name == "search_knowledge":
        context = state.get("context", [])
        if not context:
            return summary + "\n\n你可以换个说法，或转人工客服确认。"
        lines = [f"[{item['index']}] {item['title']}：{str(item['content'])[:320]}" for item in context[:3]]
        return "根据已发布的知识库：\n\n" + "\n\n".join(lines)
    if name == "request_refund":
        return summary
    if name == "check_refund_eligibility":
        eligible = (last.get("payload") or {}).get("eligible")
        if eligible:
            return summary + " 正在提交人工审批，请稍候。"
        return summary + "\n\n如属于特殊情况，可转人工客服进一步处理。"
    if name == "list_orders" and last.get("status") == "need_identifier":
        return "请提供下单邮箱或订单号，我才能查询你的订单。"
    if name == "list_orders" and last.get("status") == "empty":
        return summary
    if "退款" in question and not extract_order_no(question) and name == "search_knowledge":
        return (
            summary
            + "\n\n如需提交退款，请补充订单号（例如 HF-2026-0001）；"
            "退款需要人工审批后才会执行。"
        )
    return summary


def respond_node(state: AgentState) -> dict[str, object]:
    observations = "\n".join(
        f"- {step.get('name')}（{step.get('status')}）：{step.get('summary')}"
        for step in state.get("steps", [])
    )
    answer = ""
    if settings.agent_use_llm and state.get("steps"):
        try:
            answer = answer_with_tools(
                state.get("question", ""),
                observations,
                [
                    ChatTurn(role=str(item.get("role", "visitor")), content=str(item.get("content", "")))
                    for item in state.get("history", [])
                ],
            )
        except Exception as error:  # noqa: BLE001 - template fallback keeps the run usable
            logger.warning("Agent synthesis failed, using template: %s", error)
    if not answer:
        answer = _template_answer(state)
    return {"answer": answer, "outcome": state.get("outcome") or "answered"}


def build_graph(checkpointer: Any):
    workflow = StateGraph(AgentState)
    workflow.add_node("plan", plan_node)
    workflow.add_node("run_tool", run_tool_node)
    workflow.add_node("request_refund", request_refund_node)
    workflow.add_node("respond", respond_node)

    workflow.set_entry_point("plan")
    workflow.add_conditional_edges(
        "plan",
        route_after_plan,
        {"run_tool": "run_tool", "request_refund": "request_refund", "respond": "respond"},
    )
    workflow.add_edge("run_tool", "plan")
    workflow.add_edge("request_refund", "respond")
    workflow.add_edge("respond", END)
    return workflow.compile(checkpointer=checkpointer)
