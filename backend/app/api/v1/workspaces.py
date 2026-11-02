from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps.auth import CurrentUser, require_roles
from app.db.session import get_db
from app.models import Membership, User
from app.schemas.members import CreateMemberRequest, MemberResponse, UpdateMemberRequest

router = APIRouter(prefix="/workspaces/current", tags=["workspaces"])


def serialize_member(membership: Membership, user: User) -> MemberResponse:
    return MemberResponse(
        id=membership.id,
        user_id=user.id,
        email=user.email,
        name=user.name,
        role=membership.role,
    )


@router.get("/members")
def list_members(
    current: CurrentUser = Depends(require_roles("admin", "agent", "viewer")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, list[MemberResponse]]:
    rows = db.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.workspace_id == current.workspace.id)
        .order_by(Membership.created_at)
    ).all()
    return {"data": [serialize_member(membership, user) for membership, user in rows]}


@router.post("/members", status_code=status.HTTP_201_CREATED)
def add_member(
    payload: CreateMemberRequest,
    current: CurrentUser = Depends(require_roles("admin")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, MemberResponse]:
    user = db.scalar(select(User).where(User.email == payload.email))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User must register before being added to a workspace",
        )
    existing = db.scalar(
        select(Membership).where(
            Membership.user_id == user.id, Membership.workspace_id == current.workspace.id
        )
    )
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="User is already a workspace member")
    user.name = payload.name
    membership = Membership(user_id=user.id, workspace_id=current.workspace.id, role=payload.role)
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return {"data": serialize_member(membership, user)}


@router.patch("/members/{member_id}")
def update_member(
    member_id: UUID,
    payload: UpdateMemberRequest,
    current: CurrentUser = Depends(require_roles("admin")),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, MemberResponse]:
    membership = db.scalar(
        select(Membership).where(Membership.id == member_id, Membership.workspace_id == current.workspace.id)
    )
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    membership.role = payload.role
    db.commit()
    user = db.get(User, membership.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member user not found")
    return {"data": serialize_member(membership, user)}
