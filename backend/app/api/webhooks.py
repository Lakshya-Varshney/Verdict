"""Webhook subscriptions (T4): register, list, delete, inspect deliveries, ping."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role_global
from app.database import get_db
from app.models.event import Event, EventRole, EventRoleType
from app.models.user import User
from app.models.webhook import Webhook, WebhookDelivery
from app.schemas.api import DeliveryOut, EventTypeOut, OkOut, WebhookCreated, WebhookOut
from app.services import webhook_service as ws
from app.services.audit_service import create_audit_log
from app.config import settings

router = APIRouter(tags=["webhooks"])


class WebhookCreate(BaseModel):
    url: str = Field(max_length=2000, description="https endpoint that will receive `POST` requests with a JSON body")
    event_types: list[str] = Field(max_length=20, description="Any of `GET /webhooks/event-types`, or `*` for all")
    event_id: Optional[UUID] = Field(None, description="Only this event. Omit for every event you organize.")


async def _own(db: AsyncSession, hook_id: UUID, user: User) -> Webhook:
    hook = (await db.execute(select(Webhook).where(Webhook.id == str(hook_id), Webhook.owner_id == str(user.id)))).scalar_one_or_none()
    if hook is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Webhook not found")  # not yours == not found
    return hook


@router.get("/webhooks/event-types", response_model=list[EventTypeOut])
async def list_event_types():
    """The events a webhook can subscribe to."""
    return [{"name": n, "description": d} for n, d in ws.EVENT_TYPES.items()]


@router.post("/webhooks/subscribe", response_model=WebhookCreated, status_code=status.HTTP_201_CREATED)
async def subscribe(
    body: WebhookCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_global(["organizer", "admin"])),
):
    """Register an endpoint. The signing `secret` is returned **once**, here."""
    owner_id = current_user.id
    try:
        types = ws.validate_types(body.event_types)
        await ws.check_target(body.url)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    if body.event_id is not None:
        ev = (await db.execute(select(Event).where(Event.id == str(body.event_id)))).scalar_one_or_none()
        if ev is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
        staff = await db.execute(select(EventRole.id).where(
            EventRole.event_id == str(body.event_id), EventRole.user_id == str(owner_id),
            EventRole.role.in_([EventRoleType.ORGANIZER, EventRoleType.ADMIN])))
        if staff.first() is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You are not an organizer of that event")
    count = (await db.execute(select(func.count()).select_from(Webhook).where(Webhook.owner_id == str(owner_id)))).scalar() or 0
    if count >= settings.WEBHOOK_MAX_PER_OWNER:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Webhook limit reached ({settings.WEBHOOK_MAX_PER_OWNER} per organizer)")
    hook = Webhook(owner_id=str(owner_id), event_id=str(body.event_id) if body.event_id else None,
                   url=body.url.strip(), event_types=types, secret=ws.new_secret())
    db.add(hook)
    await db.flush()
    await create_audit_log(
        db, "webhook.subscribe", "webhook", hook.id, actor_id=owner_id, event_id=body.event_id,
        extra_data={"role": "organizer", "url": hook.url, "event_types": types, "detail": f"registered {hook.url}"},
    )
    return {**_out(hook), "secret": hook.secret}


def _out(h: Webhook) -> dict:
    return {
        "id": h.id, "url": h.url, "event_types": h.event_types or [], "active": h.active,
        "created_at": h.created_at.isoformat() if h.created_at else "", "event_id": h.event_id,
        "disabled_reason": h.disabled_reason, "last_status": h.last_status,
        "last_delivery_at": h.last_delivery_at.isoformat() if h.last_delivery_at else None,
        "consecutive_failures": h.consecutive_failures,
    }


@router.get("/webhooks", response_model=list[WebhookOut])
async def list_webhooks(
    event_id: Optional[UUID] = Query(None, description="Only endpoints scoped to this event (plus your all-events ones)"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_global(["organizer", "admin"])),
):
    """Your webhooks. Secrets are never shown again after creation."""
    hooks = (await db.execute(select(Webhook).where(Webhook.owner_id == str(current_user.id)).order_by(Webhook.created_at))).scalars().all()
    if event_id is not None:
        hooks = [h for h in hooks if h.event_id in (None, str(event_id))]
    return [_out(h) for h in hooks]


@router.delete("/webhooks/{webhook_id}", response_model=OkOut)
async def delete_webhook(
    webhook_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_global(["organizer", "admin"])),
):
    """Remove an endpoint and its delivery log."""
    actor = current_user.id
    hook = await _own(db, webhook_id, current_user)
    scope, url = hook.event_id, hook.url
    await db.execute(delete(WebhookDelivery).where(WebhookDelivery.webhook_id == hook.id))
    await db.execute(delete(Webhook).where(Webhook.id == hook.id))
    await create_audit_log(db, "webhook.delete", "webhook", str(webhook_id), actor_id=actor, event_id=scope,
                           extra_data={"role": "organizer", "url": url, "detail": f"removed {url}"})
    return {"ok": True}


@router.get("/webhooks/{webhook_id}/deliveries", response_model=list[DeliveryOut])
async def list_deliveries(
    webhook_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    delivery_status: Optional[str] = Query(None, alias="status", description="pending | retry | success | dead"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_global(["organizer", "admin"])),
):
    """Delivery log (newest first): status, attempts, HTTP status and last error of each send."""
    hook = await _own(db, webhook_id, current_user)
    q = select(WebhookDelivery).where(WebhookDelivery.webhook_id == hook.id)
    if delivery_status:
        q = q.where(WebhookDelivery.status == delivery_status)
    rows = (await db.execute(q.order_by(WebhookDelivery.created_at.desc()).limit(limit))).scalars().all()
    return [_delivery(d) for d in rows]


def _delivery(d: WebhookDelivery) -> dict:
    iso = lambda x: x.isoformat() if x else None  # noqa: E731
    return {"id": d.id, "event_type": d.event_type, "status": d.status, "attempts": d.attempts,
            "response_status": d.response_status, "last_error": d.last_error, "created_at": iso(d.created_at),
            "next_attempt_at": iso(d.next_attempt_at) if d.status in ("pending", "retry", "sending") else None,
            "delivered_at": iso(d.delivered_at)}


@router.post("/webhooks/{webhook_id}/ping", response_model=DeliveryOut, status_code=status.HTTP_202_ACCEPTED)
async def ping_webhook(
    webhook_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_global(["organizer", "admin"])),
):
    """Queue a `webhook.ping` to this endpoint (check the result in the delivery log)."""
    hook = await _own(db, webhook_id, current_user)
    import json
    import uuid
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    did = str(uuid.uuid4())
    body = json.dumps({"id": did, "type": "webhook.ping", "created_at": now.isoformat(), "event_id": hook.event_id,
                       "data": {"webhook_id": hook.id, "message": "This is a test delivery from DOGFOOD"}},
                      sort_keys=True, separators=(",", ":"))
    d = WebhookDelivery(id=did, webhook_id=hook.id, event_id=hook.event_id, event_type="webhook.ping", body=body,
                        status="pending", next_attempt_at=now, created_at=now)
    db.add(d)
    await db.flush()
    return _delivery(d)
