from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional, Literal


class InviteRequest(BaseModel):
    child_id: UUID


class RespondRequest(BaseModel):
    invitation_id: int
    action: Literal["accept", "reject"]


class FamilyMemberDTO(BaseModel):
    user_id: UUID
    name: str
    avatar: str | None
    role: str  # 'parent' or 'child'


class InvitationDTO(BaseModel):
    id: int
    parent_id: UUID
    child_id: UUID
    parent_name: str
    child_name: str
    status: str
    created_at: datetime
    updated_at: datetime
