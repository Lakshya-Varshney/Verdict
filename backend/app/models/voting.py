"""Vote and Comment models."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Text, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Vote(Base):
    """Public vote for a submission."""

    __tablename__ = "votes"
    __table_args__ = (
        UniqueConstraint("submission_id", "voter_fingerprint", name="uq_submission_voter"),
        Index("ix_votes_event_voter", "event_id", "voter_fingerprint"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    submission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("submissions.id"), nullable=False
    )
    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("events.id"), nullable=False, index=True
    )
    voter_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)  # SHA-256 hash
    ip_hash: Mapped[str] = mapped_column(String(64), nullable=True, index=True)
    # 1 for approval voting; n (cost n^2 credits) for quadratic voting
    weight: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    submission = relationship("Submission", back_populates="votes", lazy="raise")

    def __repr__(self):
        return f"<Vote submission={self.submission_id}>"


class Comment(Base):
    """Comment on a submission."""

    __tablename__ = "comments"

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    submission_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("submissions.id"), nullable=False
    )
    author_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True  # nullable for anonymous
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    submission = relationship("Submission", back_populates="comments", lazy="raise")
    author = relationship("User", lazy="raise")

    def __repr__(self):
        return f"<Comment submission={self.submission_id}>"
