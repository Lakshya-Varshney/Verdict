"""Submission-related Pydantic schemas."""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field

from app.models.submission import SubmissionStatus
from app.schemas.limits import CustomAnswers, Markdown50k, Str255, Str500, Tags30, Url500, Urls20


class SubmissionBase(BaseModel):
    """Base submission schema."""
    name: Str255
    tagline: Optional[Str500] = None
    description_md: Optional[Markdown50k] = None
    thumbnail_url: Optional[Str500] = None
    gallery_image_urls: Urls20 = []
    demo_video_url: Optional[Str500] = None
    repo_url: Optional[Str500] = None
    live_url: Optional[Str500] = None
    tech_tags: Tags30 = []
    custom_answers: CustomAnswers = {}


class SubmissionCreate(SubmissionBase):
    """Schema for submission creation.

    ``title`` / ``summary`` are accepted as aliases of ``name`` / ``tagline`` so the
    payload shape used by the DOGFOOD fixtures and checker works unchanged.
    """
    thumbnail_url: Optional[Url500] = None
    gallery_image_urls: list[Url500] = Field(default=[], max_length=20)
    demo_video_url: Optional[Url500] = None
    repo_url: Optional[Url500] = None
    live_url: Optional[Url500] = None
    name: Str255 = Field(validation_alias=AliasChoices("name", "title"))
    tagline: Optional[Str500] = Field(
        default=None, validation_alias=AliasChoices("tagline", "summary")
    )
    track_id: Optional[UUID] = None


class SubmissionUpdate(BaseModel):
    """Schema for submission update."""
    name: Optional[Str255] = None
    tagline: Optional[Str500] = None
    description_md: Optional[Markdown50k] = None
    thumbnail_url: Optional[Url500] = None
    gallery_image_urls: Optional[list[Url500]] = Field(default=None, max_length=20)
    demo_video_url: Optional[Url500] = None
    repo_url: Optional[Url500] = None
    live_url: Optional[Url500] = None
    tech_tags: Optional[Tags30] = None
    custom_answers: Optional[CustomAnswers] = None
    track_id: Optional[UUID] = None


class SubmissionResponse(SubmissionBase):
    """Schema for submission response."""
    id: UUID
    team_id: UUID
    event_id: UUID
    track_id: Optional[UUID] = None
    status: SubmissionStatus
    submitted_at: Optional[datetime] = None
    last_edited_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class SubmissionGalleryItem(BaseModel):
    """Lightweight submission for public gallery."""
    id: UUID
    name: str
    tagline: Optional[str] = None
    thumbnail_url: Optional[str] = None
    tech_tags: list[str] = []
    team_name: Optional[str] = None
    vote_count: int = 0
