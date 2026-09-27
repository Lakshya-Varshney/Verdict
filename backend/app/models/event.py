"""Event, Track, and EventRole models."""

import uuid
from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import String, DateTime, Text, ForeignKey, Enum, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class EventStatus(str, PyEnum):
    """Event lifecycle status."""
    DRAFT = "draft"
    LIVE = "live"
    JUDGING = "judging"
    VOTING = "voting"
    CLOSED = "closed"


class EventRoleType(str, PyEnum):
    """Role types scoped per event."""
    PARTICIPANT = "participant"
    JUDGE = "judge"
    ORGANIZER = "organizer"
    ADMIN = "admin"


class Event(Base):
    """Hackathon event model."""

    __tablename__ = "events"

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    organizer_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    start_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    submission_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    judging_opens_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    judging_closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    voting_opens_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    voting_closes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    # Team formation timeline
    team_formation_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    team_formation_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[EventStatus] = mapped_column(
        Enum(EventStatus), default=EventStatus.DRAFT, nullable=False
    )
    # Public voting config: open (cookie+IP) | email (email-gated) | auth (signed-in) | quadratic (signed-in, credits)
    voting_mode: Mapped[str] = mapped_column(String(20), default="auth", server_default="auth", nullable=False)
    votes_per_voter: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    vote_credits: Mapped[int] = mapped_column(Integer, default=25, server_default="25", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    organizer = relationship("User", back_populates="organized_events", lazy="raise")
    tracks = relationship("Track", back_populates="event", lazy="raise", cascade="all, delete-orphan")
    event_roles = relationship("EventRole", back_populates="event", lazy="raise", cascade="all, delete-orphan")
    teams = relationship("Team", back_populates="event", lazy="raise", cascade="all, delete-orphan")
    submissions = relationship("Submission", back_populates="event", lazy="raise", cascade="all, delete-orphan")
    rubric_criteria = relationship("RubricCriterion", back_populates="event", lazy="raise", cascade="all, delete-orphan")
    certificates = relationship("Certificate", back_populates="event", lazy="raise")

    def __repr__(self):
        return f"<Event {self.slug}>"


class Track(Base):
    """Event track/category model."""

    __tablename__ = "tracks"

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("events.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)

    # Relationships
    event = relationship("Event", back_populates="tracks", lazy="raise")
    submissions = relationship("Submission", back_populates="track", lazy="raise")
    rubric_criteria = relationship("RubricCriterion", back_populates="track", lazy="raise")

    def __repr__(self):
        return f"<Track {self.name}>"


class EventRole(Base):
    """User role within an event (per-event scoping)."""

    __tablename__ = "event_roles"
    __table_args__ = (
        UniqueConstraint("user_id", "event_id", "role", name="uq_user_event_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("events.id"), nullable=False
    )
    role: Mapped[EventRoleType] = mapped_column(
        Enum(EventRoleType), nullable=False
    )

    # Relationships
    user = relationship("User", back_populates="event_roles", lazy="raise")
    event = relationship("Event", back_populates="event_roles", lazy="raise")

    def __repr__(self):
        return f"<EventRole {self.role} for user {self.user_id}>"
