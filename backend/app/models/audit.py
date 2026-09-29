"""AuditLog model - append-only, hash-chained audit trail.

Each row records the sha256 hash of its own immutable fields plus the previous row's hash
(`prev_hash`), in strict insertion order (`seq`, a DB-assigned identity column - independent of
wall-clock time, which can collide under load). Editing, reordering or deleting any past row
changes what every later row's hash *should* be, so `audit_service.verify_chain` can detect
tampering by a database operator - not just by application convention (see THREAT-MODEL.md R4).
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, String, DateTime, Text, ForeignKey, Identity, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

GENESIS_HASH = "0" * 64  # prev_hash of the very first row in the chain


class AuditLog(Base):
    """Append-only, hash-chained audit log for all judgment-related actions."""

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=False), unique=True, index=True, nullable=False)
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
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False, default=GENESIS_HASH)
    hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    # Relationships
    actor = relationship("User", lazy="raise")

    def __repr__(self):
        return f"<AuditLog seq={self.seq} action={self.action} target={self.target_type}/{self.target_id}>"
