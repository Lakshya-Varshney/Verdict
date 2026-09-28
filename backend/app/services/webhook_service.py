"""Webhooks (T4): subscriptions, transactional outbox, signed delivery with retries.

Guarantees
  * **At-least-once, never lost**: a delivery row is inserted in the *same transaction* as the change that caused
    it (transactional outbox), so a crash cannot drop an event and a rolled-back change never fires a hook.
  * **Authentic**: every request carries `X-Dogfood-Signature: sha256=HMAC(secret, "<timestamp>.<body>")` and
    `X-Dogfood-Timestamp`, so receivers can check origin and reject replays. Each delivery has a stable id
    (`X-Dogfood-Delivery`) receivers can use to de-duplicate retries.
  * **Bounded**: timeout, exponential backoff, dead-lettering, and an endpoint that keeps failing is switched off.
  * **Not an SSRF gadget**: http(s) only, no credentials in URLs, no redirects, the host is resolved and every
    address checked both when subscribing and again right before each send; link-local / cloud-metadata
    addresses are always refused and private-network ones unless WEBHOOK_ALLOW_PRIVATE_TARGETS is on.
  * **No leaks**: payloads carry ids and public facts only: never vote tallies, scores or emails.
"""

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import random
import secrets
import socket
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.event import EventRole, EventRoleType
from app.models.webhook import Webhook, WebhookDelivery

log = logging.getLogger(__name__)

EVENT_TYPES: dict[str, str] = {
    "submission.submitted": "A team published its project to the gallery",
    "team.created": "A team was created",
    "vote.cast": "A public vote was cast or re-allocated (no tallies are ever sent)",
    "comment.added": "A comment was posted on a project",
    "judging.normalized": "Scores were (re)normalized",
    "event.status_changed": "The event moved to another status (draft, open, judging, voting, published)",
    "results.published": "The event was published: final results are now public",
    "certificate.issued": "A certificate or judge participation record was issued",
    "webhook.ping": "Sent by POST /webhooks/{id}/ping to test an endpoint",
}
LEASE_SECONDS = 60


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ------------------------------------------------------------------ URL safety

async def resolve_host(host: str) -> list[str]:
    """Every address the host resolves to (patched in tests)."""
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({i[4][0] for i in infos})


def parse_url(url: str):
    p = urlparse(url.strip())
    if p.scheme not in ("http", "https"):
        raise ValueError("Webhook URL must start with http:// or https://")
    if not p.hostname:
        raise ValueError("Webhook URL has no host")
    if p.username or p.password:
        raise ValueError("Credentials in the URL are not allowed")
    if len(url) > 2000:
        raise ValueError("Webhook URL is too long")
    try:
        p.port  # noqa: B018  (raises for an out-of-range port)
    except ValueError:
        raise ValueError("Webhook URL has an invalid port")
    return p


def _judge_ip(ip_text: str) -> Optional[str]:
    """None if the address is fine, otherwise the reason it is refused."""
    ip = ipaddress.ip_address(ip_text.split("%")[0])
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
        return f"address {ip} is never allowed (link-local / metadata / multicast / reserved)"
    if (ip.is_private or ip.is_loopback) and not settings.WEBHOOK_ALLOW_PRIVATE_TARGETS:
        return f"address {ip} is on a private network; refused (set WEBHOOK_ALLOW_PRIVATE_TARGETS to allow)"
    return None


async def check_target(url: str) -> None:
    """Raise ValueError unless every address this URL currently resolves to may be contacted."""
    p = parse_url(url)
    host = p.hostname
    try:
        addrs = [str(ipaddress.ip_address(host))]
    except ValueError:
        try:
            addrs = await resolve_host(host)
        except OSError:
            raise ValueError(f"Host '{host}' does not resolve")
    if not addrs:
        raise ValueError(f"Host '{host}' does not resolve")
    for a in addrs:
        reason = _judge_ip(a)
        if reason:
            raise ValueError(reason)


# ------------------------------------------------------------------ signing

def sign(secret: str, timestamp: int, body: str) -> str:
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body.encode(), hashlib.sha256).hexdigest()
    return f"sha256={mac}"


def verify_signature(secret: str, timestamp: int, body: str, header: str, tolerance: int = 300, now: Optional[float] = None) -> bool:
    """Receiver-side reference: constant-time compare + replay window. (Documented in the README.)"""
    if abs((now or time.time()) - timestamp) > tolerance:
        return False
    return hmac.compare_digest(sign(secret, timestamp, body), header)


# ------------------------------------------------------------------ subscriptions

def new_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def validate_types(types: list[str]) -> list[str]:
    if not types:
        raise ValueError("Pick at least one event type")
    unknown = [t for t in types if t != "*" and t not in EVENT_TYPES]
    if unknown:
        raise ValueError(f"Unknown event type(s): {', '.join(unknown)}. Valid: * or {', '.join(EVENT_TYPES)}")
    return sorted(set(types))


# ------------------------------------------------------------------ outbox

async def emit(db: AsyncSession, event_id: Optional[str], event_type: str, data: dict[str, Any]) -> int:
    """Queue `event_type` for every matching endpoint, inside the caller's transaction. Never raises."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown webhook event type {event_type}")
    try:
        async with db.begin_nested():
            eid = str(event_id) if event_id else None
            q = select(Webhook).where(Webhook.active.is_(True))
            hooks = [h for h in (await db.execute(q)).scalars().all()
                     if (h.event_id is None or h.event_id == eid)
                     and ("*" in (h.event_types or []) or event_type in (h.event_types or []))]
            global_hooks = [h for h in hooks if h.event_id is None]
            if global_hooks and eid:
                organizers = {r for (r,) in (await db.execute(
                    select(EventRole.user_id).where(
                        EventRole.event_id == eid,
                        EventRole.role.in_([EventRoleType.ORGANIZER, EventRoleType.ADMIN])))).all()}
                hooks = [h for h in hooks if h.event_id is not None or h.owner_id in organizers]
            created = _now()
            for h in hooks:
                did = str(uuid.uuid4())
                body = json.dumps(
                    {"id": did, "type": event_type, "created_at": created.isoformat(), "event_id": eid, "data": data},
                    sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
                db.add(WebhookDelivery(id=did, webhook_id=h.id, event_id=eid, event_type=event_type, body=body,
                                       status="pending", next_attempt_at=created, created_at=created))
            await db.flush()
            return len(hooks)
    except Exception:  # a broken hook must never break the user's action
        log.exception("webhook emit failed for %s", event_type)
        return 0


# ------------------------------------------------------------------ delivery

def _backoff(attempts: int) -> float:
    steps = [float(x) for x in settings.WEBHOOK_BACKOFF_SECONDS.split(",") if x.strip()] or [30.0]
    base = steps[min(attempts - 1, len(steps) - 1)]
    return base * random.uniform(0.9, 1.1)


async def _attempt(client: httpx.AsyncClient, hook: Webhook, d: WebhookDelivery) -> tuple[bool, Optional[int], Optional[str], bool]:
    """One HTTP attempt -> (ok, http_status, error, gone)."""
    try:
        await check_target(hook.url)
    except ValueError as e:
        return False, None, f"blocked: {e}"[:300], False
    ts = int(time.time())
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "DOGFOOD-Webhooks/1.0",
        "X-Dogfood-Event": d.event_type,
        "X-Dogfood-Delivery": d.id,
        "X-Dogfood-Timestamp": str(ts),
        "X-Dogfood-Attempt": str(d.attempts + 1),
        "X-Dogfood-Signature": sign(hook.secret, ts, d.body),
    }
    try:
        r = await client.post(hook.url, content=d.body.encode("utf-8"), headers=headers,
                              timeout=settings.WEBHOOK_TIMEOUT_SECONDS, follow_redirects=False)
    except httpx.TimeoutException:
        return False, None, "timeout", False
    except httpx.HTTPError as e:
        return False, None, f"{type(e).__name__}: {e}"[:300], False
    if 200 <= r.status_code < 300:
        return True, r.status_code, None, False
    note = f"HTTP {r.status_code}" + (" (redirects are not followed)" if 300 <= r.status_code < 400 else "")
    return False, r.status_code, note, r.status_code == 410


async def deliver_due(
    session_factory: Optional[Callable] = None,
    client: Optional[httpx.AsyncClient] = None,
    now: Optional[datetime] = None,
    limit: int = 25,
) -> int:
    """Send every delivery that is due. Returns how many were attempted."""
    from app.database import async_session_factory

    factory = session_factory or async_session_factory
    now = now or _now()
    own_client = client is None
    client = client or httpx.AsyncClient()
    try:
        # 1) claim (lease) so concurrent workers never send the same delivery twice
        async with factory() as db:
            rows = (await db.execute(
                select(WebhookDelivery)
                .where(WebhookDelivery.status.in_(["pending", "retry", "sending"]), WebhookDelivery.next_attempt_at <= now)
                .order_by(WebhookDelivery.next_attempt_at).limit(limit).with_for_update(skip_locked=True)
            )).scalars().all()
            ids = [r.id for r in rows]
            for r in rows:
                r.status = "sending"
                r.next_attempt_at = now + timedelta(seconds=LEASE_SECONDS)
            await db.commit()
        # 2) send + record
        for did in ids:
            async with factory() as db:
                d = await db.get(WebhookDelivery, did)
                hook = await db.get(Webhook, d.webhook_id) if d else None
                if d is None:
                    continue
                if hook is None or not hook.active:
                    d.status, d.last_error = "dead", "endpoint disabled or deleted"
                    await db.commit()
                    continue
                ok, status_code, error, gone = await _attempt(client, hook, d)
                d.attempts += 1
                d.response_status, d.last_error = status_code, error
                hook.last_delivery_at = now
                if ok:
                    d.status, d.delivered_at = "success", now
                    hook.consecutive_failures, hook.last_status = 0, "success"
                else:
                    hook.last_status = "failing"
                    if gone or d.attempts >= settings.WEBHOOK_MAX_ATTEMPTS:
                        d.status = "dead"
                        hook.consecutive_failures += 1
                        if gone:
                            hook.active, hook.disabled_reason = False, "endpoint answered 410 Gone"
                        elif hook.consecutive_failures >= settings.WEBHOOK_DISABLE_AFTER_DEAD:
                            hook.active = False
                            hook.disabled_reason = f"{hook.consecutive_failures} deliveries in a row failed permanently"
                    else:
                        d.status = "retry"
                        d.next_attempt_at = now + timedelta(seconds=_backoff(d.attempts))
                await db.commit()
        return len(ids)
    finally:
        if own_client:
            await client.aclose()


async def worker_loop(stop: asyncio.Event) -> None:
    """Background delivery loop (started from the app lifespan)."""
    async with httpx.AsyncClient() as client:
        while not stop.is_set():
            try:
                n = await deliver_due(client=client)
            except Exception:
                log.exception("webhook worker iteration failed")
                n = 0
            if n == 0:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=1.0)
                except asyncio.TimeoutError:
                    pass
