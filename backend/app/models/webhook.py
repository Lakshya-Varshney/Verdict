"""Webhook subscriptions and their delivery outbox (T4)."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Webhook(Base):
    """A registered endpoint. `event_id` NULL = every event the owner organizes."""

    __tablename__ = "webhooks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    event_id: Mapped[str] = mapped_column(String(36), ForeignKey("events.id"), nullable=True, index=True)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    event_types: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    secret: Mapped[str] = mapped_column(String(80), nullable=False)  # HMAC key; shown to the owner once, at creation
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    disabled_reason: Mapped[str] = mapped_column(String(200), nullable=True)
    last_delivery_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)


class WebhookDelivery(Base):
    """One event -> one endpoint. Written in the same transaction as the change that caused it (outbox)."""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (Index("ix_webhook_deliveries_due", "status", "next_attempt_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    webhook_id: Mapped[str] = mapped_column(String(36), ForeignKey("webhooks.id"), nullable=False, index=True)
    event_id: Mapped[str] = mapped_column(String(36), nullable=True, index=True)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)  # the exact JSON that is sent (and signed)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="pending")  # pending|sending|retry|success|dead
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    response_status: Mapped[int] = mapped_column(Integer, nullable=True)
    last_error: Mapped[str] = mapped_column(String(300), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_now)
    delivered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
