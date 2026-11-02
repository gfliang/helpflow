"""Shared LangGraph state types."""

from typing import TypedDict


class ToolCall(TypedDict):
    name: str
    arguments: dict[str, object]


class AgentStep(TypedDict, total=False):
    name: str
    status: str
    summary: str
    payload: dict[str, object]
    duration_ms: int


class AgentState(TypedDict, total=False):
    workspace_id: str
    conversation_id: str
    visitor_id: str
    question: str
    history: list[dict[str, str]]
    intent: str
    plan: list[ToolCall]
    plan_index: int
    current_call: ToolCall | None
    steps: list[AgentStep]
    context: list[dict[str, object]]
    citations: list[dict[str, object]]
    answer: str
    outcome: str
    error: str
