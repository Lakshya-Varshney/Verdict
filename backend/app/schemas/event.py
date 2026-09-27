"""Event-related Pydantic schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.event import EventStatus, EventRoleType
from app.schemas.limits import Str255, Str500, Str2000, Text20k


class EventBase(BaseModel):
    """Base event schema."""
    name: Str255
    description: Optional[Text20k] = None


class EventCreate(EventBase):
    """Schema for event creation (UI sends slug + schedule fields)."""
    slug: Optional[Str255] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    submission_deadline: Optional[datetime] = None
    # Team formation timeline
    team_formation_start: Optional[datetime] = None
    team_formation_end: Optional[datetime] = None
    # UI aliases (accepted, ignored or mapped)
    tagline: Optional[Str500] = None
    deadline_at: Optional[datetime] = None
    starts_at: Optional[datetime] = None
    voting_opens_at: Optional[datetime] = None
    voting_closes_at: Optional[datetime] = None
    voting_mode: Optional[str] = None
    votes_per_voter: Optional[int] = Field(default=None, ge=1, le=100)
    vote_credits: Optional[int] = Field(default=None, ge=1, le=10000)
    team_size_max: Optional[int] = None
    prizes: Optional[list] = None
    custom_questions: Optional[list] = None
    judging_opens_at: Optional[datetime] = None
    judging_closes_at: Optional[datetime] = None


class EventUpdate(BaseModel):
    """Schema for event update (UI status + field aliases)."""
    name: Optional[Str255] = None
    tagline: Optional[Str500] = None
    description: Optional[Text20k] = None
    # UI status values mapped in the API layer before coercion
    status: Optional[str] = None
    starts_at: Optional[datetime] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    deadline_at: Optional[datetime] = None
    submission_deadline: Optional[datetime] = None
    team_formation_start: Optional[datetime] = None
    team_formation_end: Optional[datetime] = None
    judging_opens_at: Optional[datetime] = None
    judging_closes_at: Optional[datetime] = None
    voting_opens_at: Optional[datetime] = None
    voting_closes_at: Optional[datetime] = None
    voting_mode: Optional[str] = None
    votes_per_voter: Optional[int] = Field(default=None, ge=1, le=100)
    vote_credits: Optional[int] = Field(default=None, ge=1, le=10000)
    team_size_max: Optional[int] = None
    prizes: Optional[list] = None
    custom_questions: Optional[list] = None


class EventResponse(EventBase):
    """Schema for event response."""
    id: UUID
    slug: str
    organizer_id: UUID
    status: EventStatus
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    submission_deadline: Optional[datetime] = None
    team_formation_start: Optional[datetime] = None
    team_formation_end: Optional[datetime] = None
    judging_opens_at: Optional[datetime] = None
    judging_closes_at: Optional[datetime] = None
    voting_opens_at: Optional[datetime] = None
    voting_closes_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TrackBase(BaseModel):
    """Base track schema."""
    name: Str255
    description: Optional[Str2000] = None


class TrackCreate(TrackBase):
    """Schema for track creation."""
    pass


class TrackResponse(TrackBase):
    """Schema for track response."""
    id: UUID
    event_id: UUID

    model_config = {"from_attributes": True}


class EventRoleCreate(BaseModel):
    """Schema for event role assignment (user_id or email)."""
    user_id: Optional[UUID] = None
    email: Optional[Str255] = None
    role: EventRoleType


class EventRoleResponse(BaseModel):
    """Schema for event role response."""
    id: UUID
    user_id: UUID
    event_id: UUID
    role: EventRoleType
    user_name: Optional[str] = None
    user_email: Optional[str] = None

    model_config = {"from_attributes": True}
