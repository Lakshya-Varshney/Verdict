"""Team and TeamMembership models."""

import uuid
import secrets
from datetime import datetime, timezone
from enum import Enum as PyEnum

from sqlalchemy import String, DateTime, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TeamRoleType(str, PyEnum):
    """Role within a team."""
    LEADER = "leader"
    MEMBER = "member"


class Team(Base):
    """Team model for hackathon submissions."""

    __tablename__ = "teams"

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("events.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    invite_code: Mapped[str] = mapped_column(
        String(32), unique=True, index=True, nullable=False,
        default=lambda: secrets.token_hex(16)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    event = relationship("Event", back_populates="teams", lazy="raise")
    memberships = relationship("TeamMembership", back_populates="team", lazy="raise", cascade="all, delete-orphan")
    submissions = relationship("Submission", back_populates="team", lazy="raise", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Team {self.name}>"


class TeamMembership(Base):
    """User membership in a team."""

    __tablename__ = "team_memberships"

    team_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("teams.id"), primary_key=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), primary_key=True
    )
    role_in_team: Mapped[TeamRoleType] = mapped_column(
        Enum(TeamRoleType), default=TeamRoleType.MEMBER, nullable=False
    )

    # Relationships
    team = relationship("Team", back_populates="memberships", lazy="raise")
    user = relationship("User", back_populates="team_memberships", lazy="raise")

    def __repr__(self):
        return f"<TeamMembership {self.user_id} in {self.team_id}>"
