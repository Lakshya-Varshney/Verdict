"""Judging-related Pydantic schemas."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from app.schemas.limits import Str255, Str2000, Text20k
from pydantic import BaseModel

from app.models.judging import AssignmentStatus


class RubricCriterionBase(BaseModel):
    """Base rubric criterion schema."""
    name: Str255
    description: Optional[Str2000] = None
    weight: float = 1.0
    scale_min: float = 1.0
    scale_max: float = 10.0


class RubricCriterionCreate(RubricCriterionBase):
    """Schema for rubric criterion creation."""
    track_id: Optional[UUID] = None


class RubricCriterionResponse(RubricCriterionBase):
    """Schema for rubric criterion response."""
    id: UUID
    event_id: UUID
    track_id: Optional[UUID] = None

    model_config = {"from_attributes": True}


class JudgeAssignmentCreate(BaseModel):
    """Schema for judge assignment."""
    strategy: str = "round_robin"  # round_robin | balanced
    reviews_per_submission: int = 3


class JudgeAssignmentResponse(BaseModel):
    """Schema for judge assignment response."""
    id: UUID
    judge_id: UUID
    submission_id: UUID
    batch_id: Optional[str] = None
    status: AssignmentStatus
    assigned_at: datetime

    model_config = {"from_attributes": True}


class ScoreCreate(BaseModel):
    """Schema for score submission."""
    criterion_id: UUID
    raw_value: float
    comment: Optional[Text20k] = None


class ScoreBatchCreate(BaseModel):
    """Schema for batch score submission (or single-score alias)."""
    scores: list[ScoreCreate] = []
    criterion_id: Optional[UUID] = None
    raw_value: Optional[float] = None
    value: Optional[float] = None
    comment: Optional[str] = None


class ScoreResponse(BaseModel):
    """Schema for score response."""
    id: UUID
    judge_id: UUID
    submission_id: UUID
    criterion_id: UUID
    raw_value: float
    comment: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class NormalizedScoreResponse(BaseModel):
    """Schema for normalized score response."""
    submission_id: UUID
    criterion_id: UUID
    method: str
    normalized_value: float
    computed_at: datetime

    model_config = {"from_attributes": True}


class JudgingProgress(BaseModel):
    """Schema for judging progress dashboard."""
    total_submissions: int
    total_judges: int
    assignments_total: int
    assignments_completed: int
    completion_percentage: float


class JudgingResult(BaseModel):
    """Schema for final judging results."""
    submission_id: UUID
    submission_name: str
    raw_weighted_score: float
    normalized_score: float
    judge_count: int
    rank: int
