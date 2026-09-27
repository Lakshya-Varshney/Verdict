"""Submission model."""

import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import String, DateTime, Text, ForeignKey, Enum, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SubmissionStatus(str, PyEnum):
    """Submission lifecycle status."""
    DRAFT = "draft"
    SUBMITTED = "submitted"


class Submission(Base):
    """Hackathon submission model."""

    __tablename__ = "submissions"

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    team_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("teams.id"), nullable=False
    )
    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("events.id"), nullable=False
    )
    track_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tracks.id"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    tagline: Mapped[str] = mapped_column(String(500), nullable=True)
    description_md: Mapped[str] = mapped_column(Text, nullable=True)
    thumbnail_url: Mapped[str] = mapped_column(String(500), nullable=True)
    gallery_image_urls: Mapped[list] = mapped_column(JSON, default=list, nullable=True)
    demo_video_url: Mapped[str] = mapped_column(String(500), nullable=True)
    repo_url: Mapped[str] = mapped_column(String(500), nullable=True)
    live_url: Mapped[str] = mapped_column(String(500), nullable=True)
    tech_tags: Mapped[list] = mapped_column(JSON, default=list, nullable=True)
    custom_answers: Mapped[dict] = mapped_column(JSON, default=dict, nullable=True)
    status: Mapped[SubmissionStatus] = mapped_column(
        Enum(SubmissionStatus), default=SubmissionStatus.DRAFT, nullable=False
    )
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    last_edited_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    team = relationship("Team", back_populates="submissions", lazy="raise")
    event = relationship("Event", back_populates="submissions", lazy="raise")
    track = relationship("Track", back_populates="submissions", lazy="raise")
    judge_assignments = relationship("JudgeAssignment", back_populates="submission", lazy="raise")
    scores = relationship("Score", back_populates="submission", lazy="raise")
    normalized_scores = relationship("NormalizedScore", back_populates="submission", lazy="raise")
    votes = relationship("Vote", back_populates="submission", lazy="raise")
    comments = relationship("Comment", back_populates="submission", lazy="raise")

    def __repr__(self):
        return f"<Submission {self.name}>"
