"""Team-related Pydantic schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field
from typing import Annotated

from app.schemas.limits import Str255

from app.models.team import TeamRoleType


class TeamBase(BaseModel):
    """Base team schema."""
    name: Str255


class TeamCreate(TeamBase):
    """Schema for team creation."""
    pass


class TeamJoin(BaseModel):
    """Schema for joining a team."""
    invite_code: Annotated[str, Field(max_length=64)]


class TeamResponse(TeamBase):
    """Schema for team response."""
    id: UUID
    event_id: UUID
    invite_code: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TeamMembershipResponse(BaseModel):
    """Schema for team membership response."""
    user_id: UUID
    role_in_team: TeamRoleType

    model_config = {"from_attributes": True}


class TeamWithMembers(TeamResponse):
    """Team with member details."""
    members: list[TeamMembershipResponse] = []
