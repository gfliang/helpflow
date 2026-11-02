"""Optional Langfuse tracing.

Everything here is a no-op unless ``LANGFUSE_ENABLED=true`` and both keys are
configured. Failures never propagate into the chat or agent path.
"""

import logging
from collections.abc import Callable

from app.core.config import settings

logger = logging.getLogger(__name__)
_warned = False
_client = None


def _langfuse_client():
    global _client
    if not settings.langfuse_enabled:
        return None
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        return None
    if _client is not None:
        return _client
    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
    except Exception as error:  # noqa: BLE001 - observability must never break requests
        logger.warning("Langfuse client unavailable: %s", error)
        return None
    return _client


def get_langchain_callbacks() -> list[object]:
    if not settings.langfuse_enabled:
        return []
    try:
        _langfuse_client()
        from langfuse.langchain import CallbackHandler

        return [CallbackHandler()]
    except Exception as error:  # noqa: BLE001
        global _warned
        if not _warned:
            _warned = True
            logger.warning("Langfuse callback handler unavailable: %s", error)
        return []


def trace_agent_run(
    name: str,
    run_id: str,
    metadata: dict[str, object],
    output: str | None = None,
) -> Callable[[], None]:
    """Record one agent run; returns a no-op closer for symmetry with span APIs."""

    def _noop() -> None:
        return None

    client = _langfuse_client()
    if client is None:
        return _noop
    try:
        client.create_event(
            name=name,
            metadata={**metadata, "run_id": run_id},
            output=output,
        )
    except Exception as error:  # noqa: BLE001
        logger.debug("Langfuse event dropped: %s", error)
    return _noop
