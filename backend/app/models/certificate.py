"""Certificate model (T4 stretch feature)."""

import uuid
import hashlib
from datetime import datetime, timezone

from sqlalchemy import JSON, String, DateTime, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Certificate(Base):
    """Participation/achievement certificate."""

    __tablename__ = "certificates"
    __table_args__ = (UniqueConstraint("user_id", "event_id", "type", name="uq_certificate_user_event_kind"),)

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("events.id"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g., "participant", "winner", "judge"
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    verification_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False,
        default=lambda: hashlib.sha256(f"{uuid.uuid4()}".encode()).hexdigest()
    )

    # The exact signed document: canonical payload + Ed25519 signature (base64url). verification_hash = sha256(payload).
    payload: Mapped[dict] = mapped_column(JSON, nullable=True)
    signature: Mapped[str] = mapped_column(Text, nullable=True)

    # Relationships
    user = relationship("User", back_populates="certificates", lazy="raise")
    event = relationship("Event", back_populates="certificates", lazy="raise")

    def __repr__(self):
        return f"<Certificate {self.type} for user {self.user_id}>"
