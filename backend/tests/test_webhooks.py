"""T4: webhooks: subscriptions, outbox, signed delivery, retries, SSRF guards, isolation."""

import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from app.config import settings
from app.models.audit import AuditLog
from app.models.event import Event, EventRole, EventRoleType, EventStatus
from app.models.user import User
from app.models.webhook import Webhook, WebhookDelivery
from app.services import webhook_service as ws
from app.utils.security import get_password_hash
from tests.conftest import TestSessionLocal, get_auth_header

PUBLIC_IP = "93.184.216.34"
URL = "https://hooks.example.test/dogfood"


@pytest.fixture(autouse=True)
def public_dns(monkeypatch):
    """Hostnames resolve to a public address; nothing in this module touches the real network."""
    async def fake(host):
        return [PUBLIC_IP]

    monkeypatch.setattr(ws, "resolve_host", fake)


class Receiver:
    """A fake webhook endpoint: records requests, answers with a scripted status sequence."""

    def __init__(self, *statuses):
        self.requests: list[httpx.Request] = []
        self.statuses = list(statuses) or [200]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        code = self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        if code == "timeout":
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(code, headers={"location": "http://evil.internal/"} if 300 <= code < 400 else {})

    def client(self):
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def bodies(self):
        return [json.loads(r.content) for r in self.requests]


async def _subscribe(client, headers, types=("submission.submitted",), url=URL, event_id=None):
    body = {"url": url, "event_types": list(types)}
    if event_id:
        body["event_id"] = event_id
    return await client.post("/webhooks/subscribe", json=body, headers=headers)


async def _deliver(db, receiver, now=None, limit=50):
    await db.commit()  # the worker reads with its own session: only committed rows are visible
    async with receiver.client() as c:
        return await ws.deliver_due(session_factory=TestSessionLocal, client=c, now=now or datetime.now(timezone.utc), limit=limit)


async def _submit_project(client, db, team, user, event, name="Proj"):
    r = await client.post(f"/teams/{team.id}/submissions", json={"name": name}, headers=get_auth_header(user))
    assert r.status_code == 201, r.text
    s = await client.post(f"/submissions/{r.json()['id']}/submit", headers=get_auth_header(user))
    assert s.status_code == 200, s.text
    return r.json()["id"]


async def _rows(db, model):
    return (await db.execute(select(model))).scalars().all()


# ---------------------------------------------------------------- subscriptions

@pytest.mark.asyncio
async def test_secret_is_returned_once_and_never_listed(client, test_organizer, test_event):
    h = get_auth_header(test_organizer)
    r = await _subscribe(client, h)
    assert r.status_code == 201, r.text
    hook = r.json()
    assert hook["secret"].startswith("whsec_") and len(hook["secret"]) > 40 and hook["active"] is True
    listed = (await client.get("/webhooks", headers=h)).json()
    assert [x["id"] for x in listed] == [hook["id"]] and "secret" not in listed[0]
    assert set(listed[0]) >= {"id", "url", "event_types", "active", "created_at"}  # the shape the UI uses


@pytest.mark.asyncio
async def test_event_type_catalog_is_public(client):
    r = await client.get("/webhooks/event-types")
    names = {t["name"] for t in r.json()}
    assert r.status_code == 200 and {"submission.submitted", "results.published", "team.created", "vote.cast",
                                     "judging.normalized", "event.status_changed"} <= names


@pytest.mark.asyncio
@pytest.mark.parametrize("url,needle", [
    ("ftp://hooks.example.test/x", "http"),
    ("hooks.example.test/x", "http"),
    ("https://user:pw@hooks.example.test/x", "Credentials"),
    ("https:///nohost", "no host"),
    ("https://hooks.example.test:99999/x", "port"),
    ("http://169.254.169.254/latest/meta-data", "never allowed"),
    ("http://[fe80::1]/x", "never allowed"),
    ("http://0.0.0.0/x", "never allowed"),
    ("http://127.0.0.1:9000/x", "private network"),
    ("http://10.0.0.5/x", "private network"),
    ("http://192.168.1.10/x", "private network"),
])
async def test_dangerous_or_malformed_urls_are_refused(client, test_organizer, test_event, url, needle):
    r = await _subscribe(client, get_auth_header(test_organizer), url=url)
    assert r.status_code == 422 and needle in r.json()["detail"], r.text


@pytest.mark.asyncio
async def test_private_targets_can_be_enabled_but_metadata_never(client, test_organizer, test_event, monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_ALLOW_PRIVATE_TARGETS", True)
    h = get_auth_header(test_organizer)
    assert (await _subscribe(client, h, url="http://127.0.0.1:9000/hook")).status_code == 201
    assert (await _subscribe(client, h, url="http://169.254.169.254/latest")).status_code == 422


@pytest.mark.asyncio
async def test_hostnames_that_resolve_to_internal_addresses_are_refused(client, test_organizer, test_event, monkeypatch):
    async def internal(host):
        return ["93.184.216.34", "10.1.2.3"]  # one public + one private address: still refused

    monkeypatch.setattr(ws, "resolve_host", internal)
    r = await _subscribe(client, get_auth_header(test_organizer), url="https://rebind.example.test/x")
    assert r.status_code == 422 and "private network" in r.json()["detail"]

    async def gone(host):
        raise OSError("nxdomain")

    monkeypatch.setattr(ws, "resolve_host", gone)
    r = await _subscribe(client, get_auth_header(test_organizer), url="https://nope.example.test/x")
    assert r.status_code == 422 and "does not resolve" in r.json()["detail"]


@pytest.mark.asyncio
async def test_event_type_validation(client, test_organizer, test_event):
    h = get_auth_header(test_organizer)
    assert (await _subscribe(client, h, types=[])).status_code == 422
    r = await _subscribe(client, h, types=["submission.submitted", "made.up"])
    assert r.status_code == 422 and "made.up" in r.json()["detail"]
    assert (await _subscribe(client, h, types=["*"])).status_code == 201


@pytest.mark.asyncio
async def test_only_organizers_can_use_webhooks(client, test_user, test_judge, test_organizer, test_event, db_session):
    assert (await client.post("/webhooks/subscribe", json={"url": URL, "event_types": ["*"]})).status_code == 401
    assert (await client.get("/webhooks")).status_code == 401
    for who in (test_user, test_judge):
        h = get_auth_header(who)
        assert (await _subscribe(client, h)).status_code == 403
        assert (await client.get("/webhooks", headers=h)).status_code == 403


async def _second_organizer(db):
    other = User(email="org2@example.com", name="Org Two", password_hash=get_password_hash("x"))
    db.add(other)
    await db.commit()
    ev = Event(organizer_id=other.id, name="Other Event", slug="other-event", status=EventStatus.LIVE)
    db.add(ev)
    await db.commit()
    db.add(EventRole(user_id=other.id, event_id=ev.id, role=EventRoleType.ORGANIZER))
    await db.commit()
    return get_auth_header(other), ev.id


@pytest.mark.asyncio
async def test_webhooks_are_private_to_their_owner(client, db_session, test_organizer, test_event):
    mine = get_auth_header(test_organizer)
    hook = (await _subscribe(client, mine)).json()
    theirs, _ = await _second_organizer(db_session)
    assert (await client.get("/webhooks", headers=theirs)).json() == []
    for method, path in (("GET", f"/webhooks/{hook['id']}/deliveries"), ("POST", f"/webhooks/{hook['id']}/ping"), ("DELETE", f"/webhooks/{hook['id']}")):
        assert (await client.request(method, path, headers=theirs)).status_code == 404  # not yours == not found
    assert (await client.get("/webhooks", headers=mine)).json()[0]["id"] == hook["id"]


@pytest.mark.asyncio
async def test_event_scoping_requires_being_that_events_organizer(client, db_session, test_organizer, test_event):
    mine = get_auth_header(test_organizer)
    _, other_event = await _second_organizer(db_session)
    assert (await _subscribe(client, mine, event_id=other_event)).status_code == 403
    assert (await _subscribe(client, mine, event_id="00000000-0000-0000-0000-000000000000")).status_code == 404
    ok = await _subscribe(client, mine, event_id=test_event.id)
    assert ok.status_code == 201 and ok.json()["event_id"] == test_event.id
    listed = (await client.get("/webhooks", params={"event_id": test_event.id}, headers=mine)).json()
    assert len(listed) == 1
    assert (await client.get("/webhooks", params={"event_id": other_event}, headers=mine)).json() == []


@pytest.mark.asyncio
async def test_per_organizer_limit(client, test_organizer, test_event, monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_MAX_PER_OWNER", 2)
    h = get_auth_header(test_organizer)
    assert [(await _subscribe(client, h)).status_code for _ in range(3)] == [201, 201, 409]


# ---------------------------------------------------------------- signed delivery

@pytest.mark.asyncio
async def test_delivery_is_signed_and_carries_the_documented_envelope(client, db_session, test_organizer, test_event, test_team, test_user):
    hook = (await _subscribe(client, get_auth_header(test_organizer), types=["submission.submitted"])).json()
    sid = await _submit_project(client, db_session, test_team, test_user, test_event, name="Glass Signal")
    rx = Receiver(200)
    assert await _deliver(db_session, rx) == 1
    assert len(rx.requests) == 1
    req = rx.requests[0]
    body = req.content.decode()
    ts = int(req.headers["x-dogfood-timestamp"])
    assert req.headers["x-dogfood-event"] == "submission.submitted" and req.headers["content-type"] == "application/json"
    assert ws.verify_signature(hook["secret"], ts, body, req.headers["x-dogfood-signature"])
    assert not ws.verify_signature("whsec_wrong", ts, body, req.headers["x-dogfood-signature"])
    doc = json.loads(body)
    assert doc["type"] == "submission.submitted" and doc["event_id"] == test_event.id and doc["id"] == req.headers["x-dogfood-delivery"]
    assert doc["data"] == {"submission_id": sid, "name": "Glass Signal", "team_id": test_team.id}
    d = (await _rows(db_session, WebhookDelivery))[0]
    assert d.status == "success" and d.attempts == 1 and d.response_status == 200 and d.delivered_at
    assert (await db_session.get(Webhook, hook["id"])).last_status == "success"


def test_signature_helpers_reject_tampering_replays_and_wrong_keys():
    now = 1_800_000_000
    sig = ws.sign("s3cret", now, '{"a":1}')
    assert ws.verify_signature("s3cret", now, '{"a":1}', sig, now=now + 10)
    assert not ws.verify_signature("s3cret", now, '{"a":2}', sig, now=now + 10)  # body tampered
    assert not ws.verify_signature("other", now, '{"a":1}', sig, now=now + 10)  # wrong secret
    assert not ws.verify_signature("s3cret", now + 1, '{"a":1}', sig, now=now + 10)  # timestamp swapped
    assert not ws.verify_signature("s3cret", now, '{"a":1}', sig, now=now + 3600)  # replay outside the window
    assert sig.startswith("sha256=") and len(sig) == 7 + 64


@pytest.mark.asyncio
async def test_only_subscribed_event_types_and_scopes_are_delivered(client, db_session, test_organizer, test_event, test_team, test_user):
    h = get_auth_header(test_organizer)
    await _subscribe(client, h, types=["vote.cast"])  # not what we are about to do
    star = (await _subscribe(client, h, types=["*"])).json()
    scoped_elsewhere = (await _subscribe(client, h, types=["*"], event_id=test_event.id)).json()
    other_h, other_event = await _second_organizer(db_session)
    await _subscribe(client, other_h, types=["*"])  # another organizer's hook must never hear about our event
    await _submit_project(client, db_session, test_team, test_user, test_event)
    await db_session.commit()
    delivered = {(d.webhook_id, d.event_type) for d in await _rows(db_session, WebhookDelivery)}
    assert delivered == {(star["id"], "submission.submitted"), (scoped_elsewhere["id"], "submission.submitted")}


@pytest.mark.asyncio
async def test_status_change_and_publish_emit_two_events_and_teams_and_normalize(client, db_session, test_organizer, test_event, test_user, test_judge):
    h = get_auth_header(test_organizer)
    await _subscribe(client, h, types=["*"])
    r = await client.patch(f"/events/{test_event.id}", json={"status": "published"}, headers=h)
    assert r.status_code == 200
    n = await client.post(f"/events/{test_event.id}/judging/normalize", headers=h)
    assert n.status_code == 200
    await db_session.commit()
    types = sorted(d.event_type for d in await _rows(db_session, WebhookDelivery))
    assert types == ["event.status_changed", "judging.normalized", "results.published"]
    sc = next(json.loads(d.body) for d in await _rows(db_session, WebhookDelivery) if d.event_type == "event.status_changed")
    assert sc["data"] == {"from": "open", "to": "published"}


@pytest.mark.asyncio
async def test_vote_events_never_carry_tallies(client, db_session, test_organizer, test_event, test_submission):
    test_event.status = EventStatus.VOTING
    test_event.voting_mode = "open"
    await db_session.commit()
    await _subscribe(client, get_auth_header(test_organizer), types=["vote.cast", "comment.added"])
    assert (await client.post(f"/submissions/{test_submission.id}/vote")).status_code == 201
    assert (await client.post(f"/submissions/{test_submission.id}/comments", json={"body": "nice"})).status_code == 201
    await db_session.commit()
    rx = Receiver(200)
    await _deliver(db_session, rx)
    by_type = {b["type"]: b["data"] for b in rx.bodies()}
    assert by_type["vote.cast"] == {"submission_id": test_submission.id, "weight": 1, "mode": "open", "updated": False}
    text = json.dumps(rx.bodies())
    assert "count" not in by_type["vote.cast"] and "tally" not in text and "fingerprint" not in text and "@" not in text


# ---------------------------------------------------------------- reliability

@pytest.mark.asyncio
async def test_failures_are_retried_with_backoff_then_succeed(client, db_session, test_organizer, test_event, monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_BACKOFF_SECONDS", "10,60")
    h = get_auth_header(test_organizer)
    hook = (await _subscribe(client, h, types=["event.status_changed"])).json()
    await client.patch(f"/events/{test_event.id}", json={"status": "judging"}, headers=h)
    rx = Receiver(500, 503, 200)
    t0 = datetime.now(timezone.utc)
    assert await _deliver(db_session, rx, now=t0) == 1
    d = (await _rows(db_session, WebhookDelivery))[0]
    assert d.status == "retry" and d.attempts == 1 and d.response_status == 500 and d.last_error == "HTTP 500"
    assert 8 <= (d.next_attempt_at.replace(tzinfo=timezone.utc) - t0).total_seconds() <= 12  # ~10s +/-10%
    assert await _deliver(db_session, rx, now=t0 + timedelta(seconds=5)) == 0  # not due yet: nothing sent
    assert len(rx.requests) == 1
    assert await _deliver(db_session, rx, now=t0 + timedelta(seconds=15)) == 1
    await db_session.refresh(d)
    assert d.status == "retry" and d.attempts == 2 and 50 <= (d.next_attempt_at.replace(tzinfo=timezone.utc) - (t0 + timedelta(seconds=15))).total_seconds() <= 70
    assert await _deliver(db_session, rx, now=t0 + timedelta(seconds=100)) == 1
    await db_session.refresh(d)
    assert d.status == "success" and d.attempts == 3
    # same delivery id and body on every attempt: receivers can de-duplicate
    assert len({r.headers["x-dogfood-delivery"] for r in rx.requests}) == 1 and len({r.content for r in rx.requests}) == 1
    assert [r.headers["x-dogfood-attempt"] for r in rx.requests] == ["1", "2", "3"]
    assert (await db_session.get(Webhook, hook["id"])).consecutive_failures == 0


@pytest.mark.asyncio
async def test_exhausted_deliveries_die_and_a_failing_endpoint_is_switched_off(client, db_session, test_organizer, test_event, monkeypatch):
    monkeypatch.setattr(settings, "WEBHOOK_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(settings, "WEBHOOK_DISABLE_AFTER_DEAD", 2)
    monkeypatch.setattr(settings, "WEBHOOK_BACKOFF_SECONDS", "1")
    h = get_auth_header(test_organizer)
    hook = (await _subscribe(client, h, types=["event.status_changed"])).json()
    for status_ in ("judging", "voting"):
        await client.patch(f"/events/{test_event.id}", json={"status": status_}, headers=h)
    rx = Receiver(500)
    t = datetime.now(timezone.utc)
    for step in range(4):
        await _deliver(db_session, rx, now=t + timedelta(seconds=10 * step))
    dead = [d for d in await _rows(db_session, WebhookDelivery) if d.status == "dead"]
    assert len(dead) == 2 and all(d.attempts == 2 for d in dead)
    wh = await db_session.get(Webhook, hook["id"])
    await db_session.refresh(wh)
    assert wh.active is False and "in a row failed" in wh.disabled_reason
    # a disabled endpoint gets nothing new
    before = len(await _rows(db_session, WebhookDelivery))
    await client.patch(f"/events/{test_event.id}", json={"status": "published"}, headers=h)
    await db_session.commit()
    assert len(await _rows(db_session, WebhookDelivery)) == before
    listed = (await client.get("/webhooks", headers=h)).json()[0]
    assert listed["active"] is False and listed["disabled_reason"]


@pytest.mark.asyncio
async def test_410_gone_disables_immediately(client, db_session, test_organizer, test_event):
    h = get_auth_header(test_organizer)
    hook = (await _subscribe(client, h, types=["event.status_changed"])).json()
    await client.patch(f"/events/{test_event.id}", json={"status": "judging"}, headers=h)
    await _deliver(db_session, Receiver(410))
    wh = await db_session.get(Webhook, hook["id"])
    await db_session.refresh(wh)
    assert wh.active is False and "410" in wh.disabled_reason
    assert (await _rows(db_session, WebhookDelivery))[0].status == "dead"


@pytest.mark.asyncio
async def test_timeouts_and_redirects_are_failures_not_followed(client, db_session, test_organizer, test_event):
    h = get_auth_header(test_organizer)
    await _subscribe(client, h, types=["event.status_changed"])
    await client.patch(f"/events/{test_event.id}", json={"status": "judging"}, headers=h)
    rx = Receiver("timeout")
    await _deliver(db_session, rx)
    d = (await _rows(db_session, WebhookDelivery))[0]
    assert d.status == "retry" and d.last_error == "timeout" and d.response_status is None
    rx2 = Receiver(302)
    await _deliver(db_session, rx2, now=datetime.now(timezone.utc) + timedelta(hours=2))
    await db_session.refresh(d)
    assert "redirects are not followed" in d.last_error and len(rx2.requests) == 1  # never chased the Location header


@pytest.mark.asyncio
async def test_targets_are_rechecked_right_before_sending(client, db_session, test_organizer, test_event, monkeypatch):
    """DNS rebinding: a host that was public at subscribe time but resolves internally at send time is not contacted."""
    h = get_auth_header(test_organizer)
    await _subscribe(client, h, types=["event.status_changed"])
    await client.patch(f"/events/{test_event.id}", json={"status": "judging"}, headers=h)

    async def rebound(host):
        return ["169.254.169.254"]

    monkeypatch.setattr(ws, "resolve_host", rebound)
    rx = Receiver(200)
    await _deliver(db_session, rx)
    d = (await _rows(db_session, WebhookDelivery))[0]
    assert rx.requests == [] and d.status == "retry" and d.last_error.startswith("blocked:")


@pytest.mark.asyncio
async def test_a_deleted_endpoint_never_receives_pending_events(client, db_session, test_organizer, test_event):
    h = get_auth_header(test_organizer)
    hook = (await _subscribe(client, h, types=["event.status_changed"])).json()
    await client.patch(f"/events/{test_event.id}", json={"status": "judging"}, headers=h)
    assert (await client.delete(f"/webhooks/{hook['id']}", headers=h)).json() == {"ok": True}
    rx = Receiver(200)
    await _deliver(db_session, rx)
    assert rx.requests == [] and await _rows(db_session, Webhook) == [] and await _rows(db_session, WebhookDelivery) == []
    actions = {a for (a,) in (await db_session.execute(select(AuditLog.action).where(AuditLog.action.like("webhook.%")))).all()}
    assert actions == {"webhook.subscribe", "webhook.delete"}


@pytest.mark.asyncio
async def test_outbox_is_atomic_with_the_change_that_caused_it(db_session, test_organizer, test_event):
    hook = Webhook(owner_id=test_organizer.id, event_id=None, url=URL, event_types=["*"], secret="s")
    db_session.add(hook)
    await db_session.commit()
    async with db_session.begin_nested() as sp:
        assert await ws.emit(db_session, test_event.id, "event.status_changed", {"to": "voting"}) == 1
        await sp.rollback()  # the change that triggered it failed
    assert await _rows(db_session, WebhookDelivery) == []
    assert await ws.emit(db_session, test_event.id, "event.status_changed", {"to": "voting"}) == 1  # and a real one is kept
    assert len(await _rows(db_session, WebhookDelivery)) == 1


@pytest.mark.asyncio
async def test_a_broken_webhook_layer_never_breaks_the_users_action(db_session):
    class Broken:
        def begin_nested(self):
            raise RuntimeError("database exploded")

    assert await ws.emit(Broken(), "e", "vote.cast", {}) == 0  # swallowed and logged
    with pytest.raises(ValueError):
        await ws.emit(db_session, "e", "not.a.real.type", {})  # a typo in our own code still fails loudly


@pytest.mark.asyncio
async def test_ping_and_delivery_log(client, db_session, test_organizer, test_event):
    h = get_auth_header(test_organizer)
    hook = (await _subscribe(client, h, types=["team.created"])).json()
    p = await client.post(f"/webhooks/{hook['id']}/ping", headers=h)
    assert p.status_code == 202 and p.json()["status"] == "pending" and p.json()["event_type"] == "webhook.ping"
    rx = Receiver(200)
    await _deliver(db_session, rx)
    assert rx.bodies()[0]["type"] == "webhook.ping" and rx.bodies()[0]["data"]["webhook_id"] == hook["id"]
    log = (await client.get(f"/webhooks/{hook['id']}/deliveries", headers=h)).json()
    assert len(log) == 1 and log[0]["status"] == "success" and log[0]["response_status"] == 200 and log[0]["attempts"] == 1
    assert (await client.get(f"/webhooks/{hook['id']}/deliveries", params={"status": "dead"}, headers=h)).json() == []
    assert (await client.get(f"/webhooks/{hook['id']}/deliveries", params={"limit": 0}, headers=h)).status_code == 422


@pytest.mark.asyncio
async def test_worker_loop_delivers_in_the_background_and_stops_promptly(monkeypatch):
    calls = []

    async def fake_deliver(**kw):
        calls.append(1)
        return 0

    monkeypatch.setattr(ws, "deliver_due", fake_deliver)
    stop = asyncio.Event()
    task = asyncio.create_task(ws.worker_loop(stop))
    await asyncio.sleep(0.15)
    stop.set()
    t0 = time.time()
    await asyncio.wait_for(task, timeout=3)
    assert calls and time.time() - t0 < 2.0


@pytest.mark.asyncio
async def test_concurrent_workers_do_not_double_send(client, db_session, test_organizer, test_event):
    """Claiming leases a delivery: while one worker holds it, another finds nothing due."""
    h = get_auth_header(test_organizer)
    await _subscribe(client, h, types=["event.status_changed"])
    await client.patch(f"/events/{test_event.id}", json={"status": "judging"}, headers=h)
    await db_session.commit()
    gate, entered = asyncio.Event(), asyncio.Event()
    hits = []

    async def slow(request):
        hits.append(1)
        entered.set()
        await gate.wait()
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(slow)) as slow_client, Receiver(200).client() as fast_client:
        first = asyncio.create_task(ws.deliver_due(session_factory=TestSessionLocal, client=slow_client))
        await asyncio.wait_for(entered.wait(), timeout=5)
        second = await ws.deliver_due(session_factory=TestSessionLocal, client=fast_client)  # same instant, lease is held
        gate.set()
        await first
    assert second == 0 and hits == [1]
