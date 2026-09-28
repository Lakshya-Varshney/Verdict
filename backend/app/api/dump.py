"""Bulk JSON export / import of a whole event (T4)."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import is_global_admin, require_role
from app.database import get_db
from app.models.event import Event
from app.models.user import User
from app.schemas.dump import EventDump, ImportResultOut
from app.services.audit_service import create_audit_log
from app.services.event_dump import DumpError, build_dump, import_dump

router = APIRouter(tags=["data"])

MAX_IMPORT_BYTES = 50 * 1024 * 1024


@router.post("/events/{event_id}/export", response_model=EventDump)
async def export_event(
    event_id: UUID,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(["organizer", "admin"])),
):
    """Download a complete, checksummed JSON snapshot of the event (see `EventDump`)."""
    event = (await db.execute(select(Event).where(Event.id == str(event_id)))).scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    dump = await build_dump(db, str(event_id))
    await create_audit_log(
        db, "event.export", "event", event.id, actor_id=current_user.id, event_id=event.id,
        extra_data={"role": "organizer", "detail": "exported full JSON dump", "checksum": dump.checksum},
    )
    response.headers["Content-Disposition"] = f'attachment; filename="{event.slug}-dump.json"'
    return dump


@router.post("/events/{event_id}/import", response_model=ImportResultOut)
async def import_event(
    event_id: UUID,
    dump: EventDump,
    dry_run: bool = Query(False, description="Validate and count everything, write nothing"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(["organizer", "admin"])),
):
    """Restore a dump into this event: validated first, one transaction, idempotent, never deletes."""
    event = (await db.execute(select(Event).where(Event.id == str(event_id)))).scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    try:
        return await import_dump(db, str(event_id), dump, actor_id=current_user.id, dry_run=dry_run,
                                 actor_is_admin=await is_global_admin(db, current_user.id))
    except DumpError as e:
        shown = "; ".join(e.problems[:10]) + (f" (+{len(e.problems) - 10} more)" if len(e.problems) > 10 else "")
        prefix = "Dump rejected" if e.status_code == 422 else "Import conflict"
        raise HTTPException(status_code=e.status_code, detail=f"{prefix}: {shown}")
