import logging
import threading
import time
import uuid

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AuditLog

logger = logging.getLogger(__name__)

_rate_state: dict[str, tuple[int, float]] = {}
_rate_lock = threading.Lock()
_redis_warning_emitted = False


def record_audit(
    db: Session,
    workspace_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    action: str,
    target_type: str,
    target_id: uuid.UUID | None = None,
    detail: dict[str, object] | None = None,
) -> None:
    """Queue an audit entry; the caller commits it together with the business change."""
    db.add(
        AuditLog(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            detail=detail or {},
        )
    )


def _memory_allow(key: str, limit: int, window_seconds: int) -> bool:
    """Process-local fallback so rate limiting still works when Redis is unavailable."""
    now = time.monotonic()
    with _rate_lock:
        count, reset_at = _rate_state.get(key, (0, now + window_seconds))
        if now >= reset_at:
            count, reset_at = 0, now + window_seconds
        count += 1
        _rate_state[key] = (count, reset_at)
        if len(_rate_state) > 5_000:
            expired = [name for name, (_, expiry) in _rate_state.items() if expiry <= now]
            for name in expired:
                _rate_state.pop(name, None)
        return count <= limit


def check_rate_limit(scope: str, identifier: str, limit: int, window_seconds: int = 60) -> bool:
    """Fixed-window limiter; Redis outages never block the product."""
    if not settings.rate_limit_enabled:
        return True
    key = f"helpflow:rate:{scope}:{identifier}"
    try:
        from app.db.redis import get_redis

        client = get_redis()
        if client is not None:
            current = int(client.incr(key))
            if current == 1:
                client.expire(key, window_seconds)
            return current <= limit
    except Exception as error:  # noqa: BLE001 - Redis must never break the API
        global _redis_warning_emitted
        if not _redis_warning_emitted:
            _redis_warning_emitted = True
            logger.warning("Redis rate limiter unavailable, using in-memory fallback: %s", error)
    return _memory_allow(key, limit, window_seconds)
