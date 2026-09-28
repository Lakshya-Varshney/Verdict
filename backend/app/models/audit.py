"""AuditLog model - append-only audit trail."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Text, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AuditLog(Base):
    """Append-only audit log for all judgment-related actions."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    actor_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True  # nullable for system actions
    )
    event_id: Mapped[str] = mapped_column(String(36), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g., "score", "vote", "event_role"
    target_id: Mapped[str] = mapped_column(String(36), nullable=False)
    extra_data: Mapped[dict] = mapped_column(JSON, default=dict, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )

    # Relationships
    actor = relationship("User", lazy="raise")

    def __repr__(self):
        return f"<AuditLog action={self.action} target={self.target_type}/{self.target_id}>"
