"""Event API routes."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import require_role, require_role_global, get_current_user, get_current_user_optional, hide_draft_event, is_global_admin
from app.services.event_service import (
    create_event,
    get_event,
    list_events,
    update_event,
    delete_event,
    create_track,
    list_tracks,
    assign_role,
    list_event_roles,
)
from app.schemas.event import (
    EventCreate,
    EventUpdate,
    EventResponse,
    TrackCreate,
    TrackResponse,
    EventRoleCreate,
    EventRoleResponse,
)
from app.models.user import User
from app.models.event import EventRoleType
from app.services.audit_service import create_audit_log
from app.services.webhook_service import emit as emit_webhook
from app.services.voting_service import VOTING_MODES
from app.utils.fingerprint import client_ip
from app.schemas.api import EventOut

router = APIRouter(tags=["events"])


def _check_voting_mode(mode: Optional[str]) -> None:
    if mode is not None and mode not in VOTING_MODES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"voting_mode must be one of {', '.join(VOTING_MODES)}",
        )


def _to_ui_event(event) -> dict:
    """Map backend Event → frontend EventT fields."""
    status_map = {"live": "open", "closed": "published"}
    raw_status = event.status.value if hasattr(event.status, "value") else str(event.status)
    desc = event.description or ""
    # Prefer explicit tagline line if description has a blank-line split
    parts = desc.split("\n\n", 1)
    tagline = parts[0] if parts else ""
    body = parts[1] if len(parts) > 1 else desc
    return {
        "id": event.id,
        "name": event.name,
        "slug": event.slug,
        "organizer_id": event.organizer_id,
        "tagline": tagline,
        "description": body,
        "status": status_map.get(raw_status, raw_status),
        "starts_at": event.start_date.isoformat() if event.start_date else None,
        "start_date": event.start_date.isoformat() if event.start_date else None,
        "deadline_at": event.submission_deadline.isoformat() if event.submission_deadline else None,
        "submission_deadline": event.submission_deadline.isoformat() if event.submission_deadline else None,
        "team_formation_start": event.team_formation_start.isoformat() if event.team_formation_start else None,
        "team_formation_end": event.team_formation_end.isoformat() if event.team_formation_end else None,
        "voting_opens_at": event.voting_opens_at.isoformat() if event.voting_opens_at else None,
        "voting_closes_at": event.voting_closes_at.isoformat() if event.voting_closes_at else None,
        "voting_mode": event.voting_mode or "auth",
        "votes_per_voter": event.votes_per_voter,
        "vote_credits": event.vote_credits,
        "team_size_max": 4,
        "prizes": [],
        "custom_questions": [],
        "submission_count": 0,
        "team_count": 0,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


_STATUS_TO_API = {"open": "live", "published": "closed", "archived": "closed"}


@router.post("/events", response_model=EventOut, status_code=status.HTTP_201_CREATED)
async def create_new_event(
    event_data: EventCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_global(["organizer", "admin"])),
):
    """Create a new event (organizer/admin only). Accepts UI field aliases."""
    _check_voting_mode(event_data.voting_mode)
    try:
        slug = event_data.slug or f"{event_data.name.lower().replace(' ', '-')}-{int(__import__('time').time())}"
        deadline = event_data.submission_deadline or event_data.deadline_at
        start = event_data.start_date or event_data.starts_at
        tagline = event_data.tagline
        description = event_data.description or ""
        if tagline:
            description = f"{tagline}\n\n{description}" if description else tagline
        event = await create_event(
            db=db,
            organizer_id=current_user.id,
            name=event_data.name,
            slug=slug,
            description=description,
            start_date=start,
            end_date=event_data.end_date,
            submission_deadline=deadline,
            team_formation_start=event_data.team_formation_start,
            team_formation_end=event_data.team_formation_end,
            judging_opens_at=event_data.judging_opens_at,
            judging_closes_at=event_data.judging_closes_at,
            voting_opens_at=event_data.voting_opens_at,
            voting_closes_at=event_data.voting_closes_at,
            voting_mode=event_data.voting_mode or "auth",
            votes_per_voter=event_data.votes_per_voter or 1,
            vote_credits=event_data.vote_credits or 25,
        )
        await create_audit_log(
            db, "event.create", "event", event.id, actor_id=current_user.id, event_id=event.id,
            extra_data={"role": "organizer", "name": event.name, "detail": f"created event '{event.name}'"},
        )
        return _to_ui_event(event)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/events", response_model=list[EventOut])
async def list_all_events(
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1, le=100_000),
    limit: int = Query(100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """List all events (public, filterable by status). Status filter accepts UI names.
    
    Draft events are hidden from non-organizer/non-admin users.
    """
    # Map UI status → backend enum value for the query
    if status_filter:
        status_filter = _STATUS_TO_API.get(status_filter, status_filter)
    user_id = current_user.id if current_user else None
    events, total = await list_events(db, status=status_filter, page=page, limit=limit, user_id=user_id, public_view=True)
    return [_to_ui_event(e) for e in events]


@router.get("/events/{event_id}", response_model=EventOut)
async def get_event_detail(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Get event details (public).
    
    Draft events are hidden from non-organizer/non-admin users.
    """
    user_id = current_user.id if current_user else None
    event = await get_event(db, event_id, user_id=user_id, public_view=True)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )
    return _to_ui_event(event)


@router.patch("/events/{event_id}", response_model=EventOut)
async def update_event_detail(
    event_id: UUID,
    event_data: EventUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(["organizer", "admin"])),
):
    """Update event (organizer/admin only). Maps UI field/status names to backend."""
    from app.models.event import EventStatus

    _check_voting_mode(event_data.voting_mode)
    raw = event_data.model_dump(exclude_unset=True)
    before = await get_event(db, event_id)
    old_status = before.status.value if before else None
    # Status map: UI → backend enum
    status_map = {"open": "live", "published": "closed", "archived": "closed"}
    st = raw.pop("status", None)
    if st is not None:
        raw["status"] = EventStatus(status_map.get(st, st))
    # Date aliases
    if "starts_at" in raw:
        raw["start_date"] = raw.pop("starts_at")
    if "deadline_at" in raw:
        raw["submission_deadline"] = raw.pop("deadline_at")
    # tagline is stored as the first paragraph of description ("tagline<blank line>body")
    if "tagline" in raw or "description" in raw:
        current = await get_event(db, event_id)
        if current:
            parts = (current.description or "").split("\n\n", 1)
            cur_tag = parts[0]
            cur_body = parts[1] if len(parts) > 1 else ""
            tag = raw["tagline"] if raw.get("tagline") is not None else cur_tag
            body = raw["description"] if raw.get("description") is not None else cur_body
            raw["description"] = f"{tag}\n\n{body}" if body else tag
    # Drop UI-only fields the Event model does not have
    for k in ("tagline", "team_size_max", "prizes", "custom_questions"):
        raw.pop(k, None)
    # If only aliases were provided, map them
    if event_data.starts_at is not None and "start_date" not in raw:
        raw["start_date"] = event_data.starts_at
    if event_data.deadline_at is not None and "submission_deadline" not in raw:
        raw["submission_deadline"] = event_data.deadline_at

    event = await update_event(db, event_id, **{k: v for k, v in raw.items() if v is not None or k == "status"})
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )
    changed = sorted(k for k in event_data.model_dump(exclude_unset=True))
    await create_audit_log(
        db, "event.status_change" if event.status.value != old_status else "event.update", "event", event.id,
        actor_id=current_user.id, event_id=event.id,
        extra_data={
            "role": "organizer", "fields": changed,
            "detail": f"status {old_status} -> {event.status.value}" if event.status.value != old_status
            else "updated " + ", ".join(changed),
        },
    )
    if event.status.value != old_status:
        ui = {"live": "open", "closed": "published"}
        new_status = ui.get(event.status.value, event.status.value)
        await emit_webhook(db, event.id, "event.status_changed", {"from": ui.get(old_status, old_status), "to": new_status})
        if new_status == "published":
            await emit_webhook(db, event.id, "results.published", {"event_name": event.name})
    return _to_ui_event(event)


@router.post("/events/{event_id}/tracks", response_model=TrackResponse, status_code=status.HTTP_201_CREATED)
async def create_event_track(
    event_id: UUID,
    track_data: TrackCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(["organizer", "admin"])),
):
    """Create a track for an event (organizer only)."""
    track = await create_track(
        db=db,
        event_id=event_id,
        name=track_data.name,
        description=track_data.description,
    )
    return TrackResponse.model_validate(track)


@router.get("/events/{event_id}/tracks", response_model=list[TrackResponse])
async def list_event_tracks(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """List tracks for an event (public; 404 while the event is a draft, except for its organizers)."""
    await hide_draft_event(db, event_id, current_user)
    tracks = await list_tracks(db, event_id)
    return [TrackResponse.model_validate(t) for t in tracks]


@router.post("/events/{event_id}/roles", response_model=EventRoleResponse, status_code=status.HTTP_201_CREATED)
async def assign_event_role(
    event_id: UUID,
    role_data: EventRoleCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(["organizer", "admin"])),
):
    """Assign a role to a user by user_id or email (organizer/admin only). Only an admin can grant `admin`."""
    from sqlalchemy import select as sa_select

    # `admin` is accepted by every permission check on every event, so letting an organizer mint it would turn
    # "organizer of one event" into "site admin"
    if role_data.role == EventRoleType.ADMIN and not await is_global_admin(db, current_user.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only an admin can grant the admin role")
    from app.models.user import User as UserModel

    user_id = role_data.user_id
    if not user_id and role_data.email:
        result = await db.execute(
            sa_select(UserModel).where(UserModel.email == role_data.email)
        )
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No user with that email",
            )
        user_id = user.id
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="user_id or email required",
        )

    try:
        event_role = await assign_role(
            db=db,
            event_id=event_id,
            user_id=user_id,
            role=role_data.role,
        )
        await create_audit_log(
            db, "role.grant", "event_role", event_role.id, actor_id=current_user.id, event_id=event_id,
            extra_data={"role": "organizer", "ip": client_ip(request), "granted_role": role_data.role.value,
                        "user_id": str(user_id), "detail": f"granted {role_data.role.value} to {user_id}"},
        )
        # Enrich with user fields for the UI
        result = await db.execute(sa_select(UserModel).where(UserModel.id == str(user_id)))
        user = result.scalar_one_or_none()
        resp = EventRoleResponse.model_validate(event_role)
        if user:
            resp.user_name = user.name
            resp.user_email = user.email
        return resp
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/events/{event_id}/roles", response_model=list[EventRoleResponse])
async def list_event_roles_detail(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(["organizer", "admin"])),
):
    """List all roles for an event (organizer/admin only)."""
    from sqlalchemy import select as sa_select
    from app.models.user import User as UserModel

    roles = await list_event_roles(db, event_id)
    out: list[EventRoleResponse] = []
    for r in roles:
        resp = EventRoleResponse.model_validate(r)
        result = await db.execute(sa_select(UserModel).where(UserModel.id == str(r.user_id)))
        user = result.scalar_one_or_none()
        if user:
            resp.user_name = user.name
            resp.user_email = user.email
        out.append(resp)
    return out


@router.delete("/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_event_endpoint(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(["organizer", "admin"])),
):
    """Delete an event (organizer who created it or admin only)."""
    from app.models.event import Event
    
    event = await get_event(db, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )
    
    # Check if user is the organizer who created the event or admin
    if event.organizer_id != str(current_user.id):
        # Check if user has admin role in this event
        from app.models.event import EventRole, EventRoleType
        from sqlalchemy import select
        admin_check = await db.execute(
            select(EventRole).where(
                EventRole.user_id == current_user.id,
                EventRole.event_id == str(event_id),
                EventRole.role == EventRoleType.ADMIN,
            )
        )
        if not admin_check.first():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the event organizer or admin can delete this event",
            )
    
    ev_name, actor_id = event.name, current_user.id  # delete_event expires ORM state
    deleted = await delete_event(db, event_id)
    if deleted:
        await create_audit_log(
            db, "event.delete", "event", event_id, actor_id=actor_id, event_id=event_id,
            extra_data={"role": "organizer", "detail": f"deleted event '{ev_name}'"},
        )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found",
        )
