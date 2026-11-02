from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class MemberResponse(BaseModel):
    id: UUID
    user_id: UUID
    email: EmailStr
    name: str
    role: str


class CreateMemberRequest(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(pattern="^(admin|agent|viewer)$")


class UpdateMemberRequest(BaseModel):
    role: str = Field(pattern="^(admin|agent|viewer)$")
