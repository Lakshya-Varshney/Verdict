"""Voting-related Pydantic schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.limits import Str255


class VoteCreate(BaseModel):
    """Schema for vote creation."""
    fingerprint: Optional[str] = Field(None, max_length=200)  # optional client hint (open mode); the signed session cookie wins
    email: Optional[str] = Field(None, max_length=254)  # required when the event's voting_mode is "email"
    votes: Optional[int] = Field(default=None, ge=0, le=100)  # quadratic: votes on this project (cost votes^2)


class VoteResponse(BaseModel):
    """Schema for vote response."""
    id: UUID
    submission_id: UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class VoteCountResponse(BaseModel):
    """Schema for vote count response."""
    submission_id: UUID
    vote_count: int


class CommentCreate(BaseModel):
    """Schema for comment creation."""
    body: str = Field(min_length=1, max_length=5000)
    author_name: Optional[str] = Field(None, max_length=100)  # For anonymous comments


class CommentResponse(BaseModel):
    """Schema for comment response."""
    id: UUID
    submission_id: UUID
    author_id: Optional[UUID] = None
    author_name: Optional[str] = None
    body: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogResponse(BaseModel):
    """Schema for audit log response."""
    id: UUID
    actor_id: Optional[UUID] = None
    action: str
    target_type: str
    target_id: str
    extra_data: Optional[dict] = None
    created_at: datetime

    model_config = {"from_attributes": True}
