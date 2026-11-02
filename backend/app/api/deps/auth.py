import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Membership, User, Workspace
from app.services.tokens import decode_token

security = HTTPBearer()


@dataclass(frozen=True)
class CurrentUser:
    user: User
    workspace: Workspace
    membership: Membership


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> CurrentUser:
    try:
        payload = decode_token(credentials.credentials)
        if payload.get("type") != "access":
            raise ValueError("not an access token")
        user_id = uuid.UUID(str(payload["sub"]))
        workspace_id = uuid.UUID(str(payload["workspace_id"]))
    except (KeyError, ValueError, jwt.InvalidTokenError) as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token") from error

    result = db.execute(
        select(User, Workspace, Membership)
        .join(Membership, Membership.user_id == User.id)
        .join(Workspace, Workspace.id == Membership.workspace_id)
        .where(User.id == user_id, Workspace.id == workspace_id, User.status == "active")
    ).one_or_none()
    if result is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account or workspace is unavailable")
    user, workspace, membership = result
    return CurrentUser(user=user, workspace=workspace, membership=membership)


def require_roles(*roles: str):
    def check(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:  # noqa: B008
        if current.membership.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient workspace role")
        return current

    return check
