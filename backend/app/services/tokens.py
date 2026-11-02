import uuid
from datetime import UTC, datetime, timedelta

import jwt

from app.core.config import settings


def _encode(payload: dict[str, object], expires_at: datetime) -> str:
    return jwt.encode({**payload, "exp": expires_at}, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(*, user_id: uuid.UUID, workspace_id: uuid.UUID, role: str) -> tuple[str, datetime]:
    expires_at = datetime.now(UTC) + timedelta(minutes=settings.access_token_minutes)
    return (
        _encode(
            {"sub": str(user_id), "workspace_id": str(workspace_id), "role": role, "type": "access"},
            expires_at,
        ),
        expires_at,
    )


def create_refresh_token(*, user_id: uuid.UUID, workspace_id: uuid.UUID) -> tuple[str, uuid.UUID, datetime]:
    token_id = uuid.uuid4()
    expires_at = datetime.now(UTC) + timedelta(days=settings.refresh_token_days)
    token = _encode(
        {"sub": str(user_id), "workspace_id": str(workspace_id), "jti": str(token_id), "type": "refresh"},
        expires_at,
    )
    return token, token_id, expires_at


def decode_token(token: str) -> dict[str, object]:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
