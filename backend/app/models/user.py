"""User model."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    """User account model."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationships
    event_roles = relationship("EventRole", back_populates="user", lazy="raise")
    organized_events = relationship("Event", back_populates="organizer", lazy="raise")
    team_memberships = relationship("TeamMembership", back_populates="user", lazy="raise")
    judge_assignments = relationship("JudgeAssignment", back_populates="judge", lazy="raise")
    scores = relationship("Score", back_populates="judge", lazy="raise")
    certificates = relationship("Certificate", back_populates="user", lazy="raise")

    def __repr__(self):
        return f"<User {self.email}>"
