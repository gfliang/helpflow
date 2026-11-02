"""LangGraph runtime: checkpointing and compiled graph cache."""

import logging
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from app.agents.graph import build_graph
from app.core.config import settings

logger = logging.getLogger(__name__)

_graphs: dict[str, Any] = {}
_pools: dict[str, Any] = {}


def _postgres_checkpointer():
    from langgraph.checkpoint.postgres import PostgresSaver
    from psycopg_pool import ConnectionPool

    url = settings.langgraph_database_url
    pool = _pools.get(url)
    if pool is None:
        pool = ConnectionPool(
            url,
            max_size=5,
            kwargs={"autocommit": True, "prepare_threshold": 0},
            open=True,
        )
        _pools[url] = pool
    saver = PostgresSaver(pool)
    _ensure_checkpoint_tables(pool, saver)
    return saver


def _ensure_checkpoint_tables(pool: Any, saver: Any) -> None:
    """Run schema setup only on first use.

    ``PostgresSaver.setup()`` issues ``CREATE INDEX CONCURRENTLY``, which blocks
    behind any other open transaction on the checkpoint tables. Skipping it when
    the tables already exist keeps API startup fast and avoids startup deadlocks.
    """
    with pool.connection() as connection:
        exists = connection.execute("SELECT to_regclass('public.checkpoints')").fetchone()
    if exists and exists[0] is not None:
        return
    saver.setup()


def get_checkpointer() -> Any:
    if settings.agent_checkpoint_backend.strip().lower() != "postgres":
        return MemorySaver()
    try:
        return _postgres_checkpointer()
    except Exception as error:  # noqa: BLE001 - degrade instead of blocking approvals
        logger.warning(
            "PostgresSaver unavailable (%s); falling back to in-memory checkpoints. "
            "Pending approvals will not survive a process restart.",
            error,
        )
        return MemorySaver()


def get_graph() -> Any:
    backend = settings.agent_checkpoint_backend.strip().lower()
    if backend not in _graphs:
        _graphs[backend] = build_graph(get_checkpointer())
    return _graphs[backend]


def thread_config(thread_id: str) -> dict[str, object]:
    return {"configurable": {"thread_id": thread_id}}
