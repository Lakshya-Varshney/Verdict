"""Audit log service: append, hash-chain, and verify.

The log is append-only by application convention *and* hash-chained (see `app/models/audit.py`):
`create_audit_log` is the one place a row is ever written, and `verify_chain` recomputes every
row's hash from its own stored fields to detect an operator editing history directly in the
database (THREAT-MODEL.md R4).
"""

import hashlib
from datetime import timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select, text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog, GENESIS_HASH
from app.services import signing

# One fixed key: a Postgres advisory lock held for the transaction serializes chain appends
# across concurrent requests. Without it, two concurrent writers could both read the same "tip"
# hash and each link their new row onto it, forking the chain instead of extending it in a
# single line. On dialects without advisory locks (e.g. the sqlite fallback used for quick local
# runs outside Docker) this is skipped - sqlite already serializes writes at the file level, so
# the fork this guards against cannot happen there. Every mutating request that logs an action
# now takes this one lock; a deliberate, documented cost (see ARCHITECTURE.md's trade-off table)
# for a linear, verifiable history instead of a merely conventional one.
_CHAIN_LOCK_KEY = 990099001


def _chain_payload(log: AuditLog, prev_hash: str) -> dict:
    return {
        "seq": log.seq,
        "id": log.id,
        "actor_id": log.actor_id,
        "event_id": log.event_id,
        "action": log.action,
        "target_type": log.target_type,
        "target_id": log.target_id,
        "extra_data": log.extra_data or {},
        "created_at": log.created_at.astimezone(timezone.utc).isoformat(),
        "prev_hash": prev_hash,
    }


def _chain_hash(payload: dict) -> str:
    return hashlib.sha256(signing.canonical(payload)).hexdigest()


async def append_to_chain(db: AsyncSession, log: AuditLog) -> AuditLog:
    """Hash-chain an `AuditLog` instance onto the current tip and add it, flushed into the
    caller's transaction. Shared by `create_audit_log` (the normal write path) and
    `event_dump.import_event` (which restores historical rows, preserving their original id and
    created_at, but still has to chain them as new rows in *this* database - a hash chain proves
    nothing here was altered after being written, not that a row looks identical to how it
    looked in the database it was exported from)."""
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        await db.execute(sa_text("SELECT pg_advisory_xact_lock(:key)"), {"key": _CHAIN_LOCK_KEY})

    tip = (await db.execute(select(AuditLog.hash).order_by(AuditLog.seq.desc()).limit(1))).scalar_one_or_none()
    prev_hash = tip or GENESIS_HASH
    log.prev_hash = prev_hash

    db.add(log)
    await db.flush()  # assigns seq (DB identity) and, unless the caller set it, id/created_at's default
    log.hash = _chain_hash(_chain_payload(log, prev_hash))
    await db.flush()
    return log


async def create_audit_log(
    db: AsyncSession,
    action: str,
    target_type: str,
    target_id: str,
    actor_id: Optional[UUID] = None,
    extra_data: Optional[dict] = None,
    event_id: Optional[UUID] = None,
) -> AuditLog:
    """Create an audit log entry, hash-chained onto the current tip (flushed into the caller's
    transaction, so a rolled-back action never appends a row)."""
    log = AuditLog(
        event_id=str(event_id) if event_id else None,
        actor_id=str(actor_id) if actor_id else None,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        extra_data=extra_data or {},
    )
    return await append_to_chain(db, log)


async def verify_chain(db: AsyncSession, limit: int = 500_000) -> dict:
    """Recompute every row's hash from its own stored fields, in insertion order. On failure,
    `broken` names only the first bad row's `seq`/`id` - never its content - so this stays safe
    to expose to any organizer, not just admins: it proves platform-wide integrity (or the lack
    of it) without revealing another event's audit content."""
    rows = list((await db.execute(select(AuditLog).order_by(AuditLog.seq.asc()).limit(limit))).scalars().all())
    prev_hash = GENESIS_HASH
    for i, row in enumerate(rows):
        if row.prev_hash != prev_hash:
            return {"valid": False, "checked": i, "broken": {"seq": row.seq, "id": row.id, "reason": "prev_hash does not match the previous row's hash"}}
        expected = _chain_hash(_chain_payload(row, prev_hash))
        if expected != row.hash:
            return {"valid": False, "checked": i, "broken": {"seq": row.seq, "id": row.id, "reason": "stored hash does not match this row's own recomputed content"}}
        prev_hash = row.hash
    return {"valid": True, "checked": len(rows), "head_seq": rows[-1].seq if rows else None, "head_hash": prev_hash}


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
