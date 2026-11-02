"""Lightweight guards for the public chat: sensitive words and human handoff intent."""

from app.core.config import settings


def contains_sensitive_word(text: str) -> bool:
    normalized = text.lower()
    return any(word in normalized for word in settings.sensitive_word_list)


def is_handoff_request(text: str) -> bool:
    normalized = text.lower()
    return any(keyword in normalized for keyword in settings.handoff_keyword_list)
