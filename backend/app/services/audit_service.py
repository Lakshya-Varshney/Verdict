"""Audit log service."""

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


async def create_audit_log(
    db: AsyncSession,
    action: str,
    target_type: str,
    target_id: str,
    actor_id: Optional[UUID] = None,
    extra_data: Optional[dict] = None,
    event_id: Optional[UUID] = None,
) -> AuditLog:
    """Create an audit log entry (flushed into the caller's transaction)."""
    log = AuditLog(
        event_id=str(event_id) if event_id else None,
        actor_id=str(actor_id) if actor_id else None,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        extra_data=extra_data or {},
    )
    db.add(log)
    await db.flush()
    return log


async def get_audit_logs(
    db: AsyncSession,
    event_id: Optional[UUID] = None,
    actor_id: Optional[UUID] = None,
    action: Optional[str] = None,
    page: int = 1,
    limit: int = 50,
    only_events: Optional[list[str]] = None,
) -> tuple[list[AuditLog], int]:
    """Get audit logs with filters. `only_events` restricts to those events (None = unrestricted, admins only)."""
    query = select(AuditLog)
    if only_events is not None:
        query = query.where(AuditLog.event_id.in_(only_events or [""]))

    if event_id:
        query = query.where(AuditLog.event_id == str(event_id))
    if actor_id:
        query = query.where(AuditLog.actor_id == str(actor_id))
    if action:
        query = query.where(AuditLog.action == action)

    # Count
    from sqlalchemy import func

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0

    # Paginate
    query = query.order_by(AuditLog.created_at.desc())
    query = query.offset((page - 1) * limit).limit(limit)
    result = await db.execute(query)
    logs = list(result.scalars().all())

    return logs, total
