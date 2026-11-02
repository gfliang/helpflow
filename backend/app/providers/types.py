"""Shared provider dataclasses used by chat, RAG and the agent."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextItem:
    index: int
    title: str
    content: str


@dataclass(frozen=True)
class ChatTurn:
    role: str
    content: str
