"""Admin API routes."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import is_global_admin, require_role, require_role_global
from app.services.audit_service import get_audit_logs, verify_chain
from app.schemas.voting import AuditLogResponse
from app.schemas.api import AuditChainStatus
from app.models.user import User

router = APIRouter(tags=["admin"])

NL = chr(10)


@router.get("/admin/audit", response_model=None)
async def list_audit_logs(
    event_id: Optional[UUID] = Query(None),
    actor_id: Optional[UUID] = Query(None),
    action: Optional[str] = Query(None),
    page: int = Query(1, ge=1, le=100_000),
    limit: int = Query(50, ge=1, le=100),
    format: str = Query("json", pattern="^(json|text)$", description="json (default) or text: one readable line per entry"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_global(["organizer", "admin"])),
):
    """Get audit logs (organizer/admin only) as UI-shaped Page."""
    from sqlalchemy import select as sa_select
    from app.models.event import EventRole, EventRoleType
    from app.models.user import User as UserModel

    # Organizers see the audit trail of the events THEY organize, nothing else (it holds other people's IPs and
    # actions); only a site admin sees everything.
    only_events = None
    if not await is_global_admin(db, current_user.id):
        only_events = [e for (e,) in (await db.execute(
            sa_select(EventRole.event_id).where(
                EventRole.user_id == str(current_user.id),
                EventRole.role.in_([EventRoleType.ORGANIZER, EventRoleType.ADMIN])))).all()]
        if event_id is not None and str(event_id) not in only_events:
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail="You are not an organizer of that event")

    logs, total = await get_audit_logs(
        db,
        only_events=only_events,
        event_id=event_id,
        actor_id=actor_id,
        action=action,
        page=page,
        limit=limit,
    )
    items = []
    for log in logs:
        actor_name = "system"
        if log.actor_id:
            result = await db.execute(sa_select(UserModel).where(UserModel.id == str(log.actor_id)))
            user = result.scalar_one_or_none()
            if user:
                actor_name = user.name
        extra = log.extra_data or {}
        items.append({
            "id": log.id,
            "at": log.created_at.isoformat() if hasattr(log.created_at, "isoformat") else log.created_at,
            "created_at": log.created_at.isoformat() if hasattr(log.created_at, "isoformat") else log.created_at,
            "actor_id": log.actor_id,
            "actor_name": actor_name,
            "actor_role": extra.get("role", "participant"),
            "action": log.action,
            "target": f"{log.target_type}/{log.target_id}",
            "target_type": log.target_type,
            "target_id": log.target_id,
            "outcome": extra.get("outcome", "ok"),
            "detail": extra.get("detail", ""),
            "ip": extra.get("ip", "127.0.0.1"),
            "event_id": log.event_id,
            "extra_data": extra,
        })
    if format == "text":
        lines = [
            f"{i['at']}  {i['actor_name']:<18} {i['actor_role']:<10} {i['action']:<20} {i['outcome']:<6} {i['target']}  {i['detail']}  [{i['ip']}]"
            for i in items
        ]
        header = f"# audit log, page {page}, {len(items)} of {total} entries (newest first)"
        return PlainTextResponse(NL.join([header, *lines]) + NL)
    return {"items": items, "total": total, "page": page, "limit": limit}


@router.get("/admin/audit/verify", response_model=AuditChainStatus)
async def verify_audit_chain(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_global(["organizer", "admin"])),
):
    """Recompute the whole audit log's hash chain and report whether it is intact.

    Any organizer or admin can call this (not just admins): a hash chain's integrity is a
    property of the *whole* sequence, so verifying it neither requires nor exposes any other
    event's audit content - on failure the response names only the first broken row's `seq`
    and `id`, never its action, actor or target.
    """
    return await verify_chain(db)
