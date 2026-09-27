"""Judging models: RubricCriterion, JudgeAssignment, Score, NormalizedScore."""

import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import String, DateTime, Text, Float, ForeignKey, Enum, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AssignmentStatus(str, PyEnum):
    """Judge assignment status."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


class RubricCriterion(Base):
    """Judging rubric criterion."""

    __tablename__ = "rubric_criteria"

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("events.id"), nullable=False
    )
    track_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tracks.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    scale_min: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    scale_max: Mapped[float] = mapped_column(Float, nullable=False, default=10.0)

    # Relationships
    event = relationship("Event", back_populates="rubric_criteria", lazy="raise")
    track = relationship("Track", back_populates="rubric_criteria", lazy="raise")
    scores = relationship("Score", back_populates="criterion", lazy="raise")
    normalized_scores = relationship("NormalizedScore", back_populates="criterion", lazy="raise")

    def __repr__(self):
        return f"<RubricCriterion {self.name}>"


class JudgeAssignment(Base):
    """Assignment of a judge to review a submission."""

    __tablename__ = "judge_assignments"
    __table_args__ = (
        UniqueConstraint("judge_id", "submission_id", name="uq_judge_submission"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    judge_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    submission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("submissions.id"), nullable=False
    )
    batch_id: Mapped[str] = mapped_column(String(36), nullable=True)
    status: Mapped[AssignmentStatus] = mapped_column(
        Enum(AssignmentStatus), default=AssignmentStatus.PENDING, nullable=False
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    judge = relationship("User", back_populates="judge_assignments", lazy="raise")
    submission = relationship("Submission", back_populates="judge_assignments", lazy="raise")

    def __repr__(self):
        return f"<JudgeAssignment judge={self.judge_id} submission={self.submission_id}>"


class Score(Base):
    """Judge's score for a submission on a specific criterion."""

    __tablename__ = "scores"
    __table_args__ = (
        UniqueConstraint("judge_id", "submission_id", "criterion_id", name="uq_judge_submission_criterion"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    judge_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    submission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("submissions.id"), nullable=False
    )
    criterion_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("rubric_criteria.id"), nullable=False
    )
    raw_value: Mapped[float] = mapped_column(Float, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    judge = relationship("User", back_populates="scores", lazy="raise")
    submission = relationship("Submission", back_populates="scores", lazy="raise")
    criterion = relationship("RubricCriterion", back_populates="scores", lazy="raise")

    def __repr__(self):
        return f"<Score judge={self.judge_id} criterion={self.criterion_id} value={self.raw_value}>"


class NormalizedScore(Base):
    """Normalized score computed from raw scores."""

    __tablename__ = "normalized_scores"

    submission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("submissions.id"), primary_key=True
    )
    criterion_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("rubric_criteria.id"), primary_key=True
    )
    method: Mapped[str] = mapped_column(String(50), primary_key=True)  # e.g., "per_judge_z_score"
    normalized_value: Mapped[float] = mapped_column(Float, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    submission = relationship("Submission", back_populates="normalized_scores", lazy="raise")
    criterion = relationship("RubricCriterion", back_populates="normalized_scores", lazy="raise")

    def __repr__(self):
        return f"<NormalizedScore submission={self.submission_id} method={self.method}>"
