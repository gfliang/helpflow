import re
import uuid
from datetime import UTC, datetime

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps.auth import CurrentUser, get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.models import Membership, RefreshToken, User, Workspace
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserSummary,
    WorkspaceSummary,
)
from app.services.audit import check_rate_limit
from app.services.passwords import hash_password, verify_password
from app.services.tokens import create_access_token, create_refresh_token, decode_token

router = APIRouter(prefix="/auth", tags=["auth"])


def slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "workspace"


def serialize_token_response(user: User, workspace: Workspace, role: str, db: Session) -> TokenResponse:
    access_token, access_expires_at = create_access_token(user_id=user.id, workspace_id=workspace.id, role=role)
    refresh_token, token_id, refresh_expires_at = create_refresh_token(user_id=user.id, workspace_id=workspace.id)
    db.add(RefreshToken(id=token_id, user_id=user.id, workspace_id=workspace.id, expires_at=refresh_expires_at))
    db.commit()
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        access_token_expires_at=access_expires_at,
        user=UserSummary(id=user.id, email=user.email, name=user.name),
        workspace=WorkspaceSummary(id=workspace.id, name=workspace.name, slug=workspace.slug, role=role),
    )


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> dict[str, TokenResponse]:  # noqa: B008
    if db.scalar(select(User.id).where(User.email == payload.email)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered")

    base_slug = slugify(payload.workspace_name)
    slug = base_slug
    while db.scalar(select(Workspace.id).where(Workspace.slug == slug)) is not None:
        slug = f"{base_slug}-{uuid.uuid4().hex[:6]}"

    user = User(email=payload.email, name=payload.name, password_hash=hash_password(payload.password))
    workspace = Workspace(name=payload.workspace_name, slug=slug)
    db.add_all([user, workspace])
    db.flush()
    membership = Membership(user_id=user.id, workspace_id=workspace.id, role="admin")
    db.add(membership)
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Unable to create account") from error
    return {"data": serialize_token_response(user, workspace, membership.role, db)}


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, TokenResponse]:
    identifier = payload.email.strip().lower()
    if not check_rate_limit(
        "login",
        f"{request.client.host if request.client else 'unknown'}:{identifier}",
        settings.login_limit_per_minute,
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="登录尝试过于频繁，请稍后再试。",
        )
    user = db.scalar(select(User).where(User.email == payload.email, User.status == "active"))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")

    result = db.execute(
        select(Workspace, Membership)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Membership.user_id == user.id)
        .order_by(Membership.created_at)
    ).first()
    if result is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No workspace membership found")
    workspace, membership = result
    return {"data": serialize_token_response(user, workspace, membership.role, db)}


@router.post("/refresh")
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> dict[str, TokenResponse]:  # noqa: B008
    try:
        claims = decode_token(payload.refresh_token)
        if claims.get("type") != "refresh":
            raise ValueError("not a refresh token")
        token_id = uuid.UUID(str(claims["jti"]))
        user_id = uuid.UUID(str(claims["sub"]))
        workspace_id = uuid.UUID(str(claims["workspace_id"]))
    except (KeyError, ValueError, jwt.InvalidTokenError) as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token") from error

    refresh_token = db.get(RefreshToken, token_id)
    if refresh_token is None or refresh_token.revoked_at is not None or refresh_token.expires_at < datetime.now(UTC):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token is expired or revoked")
    result = db.execute(
        select(User, Workspace, Membership)
        .join(Membership, Membership.user_id == User.id)
        .join(Workspace, Workspace.id == Membership.workspace_id)
        .where(User.id == user_id, Workspace.id == workspace_id, User.status == "active")
    ).one_or_none()
    if result is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account or workspace is unavailable")
    user, workspace, membership = result
    refresh_token.revoked_at = datetime.now(UTC)
    return {"data": serialize_token_response(user, workspace, membership.role, db)}


@router.get("/me")
def me(current: CurrentUser = Depends(get_current_user)) -> dict[str, object]:  # noqa: B008
    return {
        "data": {
            "user": UserSummary(id=current.user.id, email=current.user.email, name=current.user.name),
            "workspace": WorkspaceSummary(
                id=current.workspace.id,
                name=current.workspace.name,
                slug=current.workspace.slug,
                role=current.membership.role,
            ),
        }
    }
