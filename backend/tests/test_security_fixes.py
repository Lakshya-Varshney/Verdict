"""Regressions for vulnerabilities found while threat-modelling (each was exploitable before its fix)."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models.event import Event, EventRole, EventRoleType, EventStatus
from app.models.judging import JudgeAssignment, RubricCriterion, Score
from app.models.user import User
from app.utils.security import get_password_hash
from tests.conftest import get_auth_header


async def _user(db, email, name="U"):
    u = User(email=email, name=name, password_hash=get_password_hash("x"))
    db.add(u)
    await db.commit()
    return u


async def _organizer_of_new_event(db, tag):
    u = await _user(db, f"{tag}@example.com", tag)
    ev = Event(organizer_id=u.id, name=f"Event {tag}", slug=f"event-{tag}", status=EventStatus.LIVE)
    db.add(ev)
    await db.commit()
    db.add(EventRole(user_id=u.id, event_id=ev.id, role=EventRoleType.ORGANIZER))
    await db.commit()
    return get_auth_header(u), u, ev


async def _admin(db):
    u = await _user(db, "site.admin@example.com", "Admin")
    ev = Event(organizer_id=u.id, name="Admin Event", slug="admin-event", status=EventStatus.LIVE)
    db.add(ev)
    await db.commit()
    db.add(EventRole(user_id=u.id, event_id=ev.id, role=EventRoleType.ADMIN))
    await db.commit()
    return get_auth_header(u), u


# ---------------------------------------------------------------- audit log is per-organizer

@pytest.mark.asyncio
async def test_an_organizer_only_sees_the_audit_trail_of_their_own_events(client, db_session, test_organizer, test_event):
    a = get_auth_header(test_organizer)
    b, _, b_event = await _organizer_of_new_event(db_session, "orgb")
    await client.patch(f"/events/{test_event.id}", json={"tagline": "A's secret plans"}, headers=a)
    await client.patch(f"/events/{b_event.id}", json={"tagline": "B's plans"}, headers=b)

    mine = (await client.get("/admin/audit", headers=b, params={"limit": 100})).json()["items"]
    assert mine and {i["event_id"] for i in mine} == {b_event.id}
    assert "A's secret plans" not in str(mine)
    # asking for another event's trail by id is refused outright
    r = await client.get("/admin/audit", headers=b, params={"event_id": test_event.id})
    assert r.status_code == 403
    # ... while their own is fine, and organizer A still sees A's
    assert (await client.get("/admin/audit", headers=b, params={"event_id": b_event.id})).status_code == 200
    assert {i["event_id"] for i in (await client.get("/admin/audit", headers=a, params={"limit": 100})).json()["items"]} == {test_event.id}


@pytest.mark.asyncio
async def test_a_site_admin_sees_everything(client, db_session, test_organizer, test_event):
    await client.patch(f"/events/{test_event.id}", json={"tagline": "x"}, headers=get_auth_header(test_organizer))
    admin, _ = await _admin(db_session)
    seen = {i["event_id"] for i in (await client.get("/admin/audit", headers=admin, params={"limit": 100})).json()["items"]}
    assert test_event.id in seen
    assert (await client.get("/admin/audit", headers=admin, params={"event_id": test_event.id})).status_code == 200


# ---------------------------------------------------------------- the admin role cannot be minted by an organizer

@pytest.mark.asyncio
async def test_an_organizer_cannot_make_themselves_or_anyone_admin(client, db_session, test_organizer, test_event, test_user):
    a = get_auth_header(test_organizer)
    for target in (test_organizer, test_user):
        r = await client.post(f"/events/{test_event.id}/roles", json={"user_id": target.id, "role": "admin"}, headers=a)
        assert r.status_code == 403 and "admin" in r.json()["detail"].lower()
    assert (await client.get("/admin/audit", headers=get_auth_header(test_user))).status_code == 403  # still nobody
    # ordinary roles still work
    assert (await client.post(f"/events/{test_event.id}/roles", json={"email": "orgx@example.com", "role": "judge"}, headers=a)).status_code in (201, 404)


@pytest.mark.asyncio
async def test_an_existing_admin_may_grant_admin(client, db_session, test_event, test_user):
    admin, _ = await _admin(db_session)
    r = await client.post(f"/events/{test_event.id}/roles", json={"user_id": test_user.id, "role": "admin"}, headers=admin)
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_importing_a_dump_cannot_mint_admins_either(client, db_session, test_organizer, test_event):
    crafted = {
        "format": "dogfood-event-dump", "version": 1,
        "event": {"id": test_event.id, "name": "Test Hackathon"},
        "users": [{"id": "u-evil", "email": "evil@example.com", "name": "Evil"}],
        "roles": [{"user_id": "u-evil", "role": "admin"}, {"user_id": "u-evil", "role": "participant"}],
    }
    r = await client.post(f"/events/{test_event.id}/import", json=crafted, headers=get_auth_header(test_organizer))
    assert r.status_code == 200 and any("admin role" in w for w in r.json()["warnings"])
    evil = (await db_session.execute(select(User).where(User.email == "evil@example.com"))).scalar_one()
    roles = {x.role for (x,) in (await db_session.execute(select(EventRole).where(EventRole.user_id == evil.id))).all()}
    assert roles == {EventRoleType.PARTICIPANT}  # the participant role came through, the admin role did not


# ---------------------------------------------------------------- the judging window

async def _scoring_setup(db, event, judge, submission, **event_fields):
    for k, v in event_fields.items():
        setattr(event, k, v)
    crit = RubricCriterion(event_id=event.id, name="Q", weight=1.0, scale_min=1.0, scale_max=5.0)
    db.add(crit)
    db.add(JudgeAssignment(judge_id=judge.id, submission_id=submission.id))
    await db.commit()
    return crit


@pytest.mark.asyncio
async def test_scores_cannot_change_after_results_are_published(client, db_session, test_event, test_judge, test_submission):
    crit = await _scoring_setup(db_session, test_event, test_judge, test_submission)
    h, url = get_auth_header(test_judge), f"/submissions/{test_submission.id}/scores"
    assert (await client.post(url, json={"criterion_id": crit.id, "value": 3}, headers=h)).status_code == 200
    test_event.status = EventStatus.CLOSED
    await db_session.commit()
    r = await client.post(url, json={"criterion_id": crit.id, "value": 5}, headers=h)
    assert r.status_code == 403 and "closed" in r.json()["detail"].lower()
    stored = (await db_session.execute(select(Score.raw_value))).scalar_one()
    assert stored == 3  # the published result is what it was


@pytest.mark.asyncio
async def test_judging_window_dates_are_enforced_by_the_api(client, db_session, test_event, test_judge, test_submission):
    now = datetime.now(timezone.utc)
    crit = await _scoring_setup(db_session, test_event, test_judge, test_submission, judging_opens_at=now + timedelta(hours=1))
    h, url = get_auth_header(test_judge), f"/submissions/{test_submission.id}/scores"
    body = {"criterion_id": crit.id, "value": 4}
    r = await client.post(url, json=body, headers=h)
    assert r.status_code == 403 and "not opened" in r.json()["detail"]
    test_event.judging_opens_at, test_event.judging_closes_at = now - timedelta(hours=2), now - timedelta(hours=1)
    await db_session.commit()
    r = await client.post(url, json=body, headers=h)
    assert r.status_code == 403 and "has closed" in r.json()["detail"]
    test_event.judging_closes_at = now + timedelta(hours=1)  # inside the window
    await db_session.commit()
    assert (await client.post(url, json=body, headers=h)).status_code == 200


@pytest.mark.asyncio
async def test_a_criterion_with_scores_cannot_be_deleted(client, db_session, test_event, test_judge, test_submission, test_organizer):
    crit = await _scoring_setup(db_session, test_event, test_judge, test_submission)
    unused = RubricCriterion(event_id=test_event.id, name="Unused", weight=1.0, scale_min=1.0, scale_max=5.0)
    db_session.add(unused)
    await db_session.commit()
    await client.post(f"/submissions/{test_submission.id}/scores", json={"criterion_id": crit.id, "value": 4}, headers=get_auth_header(test_judge))
    org = get_auth_header(test_organizer)
    r = await client.delete(f"/events/{test_event.id}/rubric/criteria/{crit.id}", headers=org)
    assert r.status_code == 409 and "never deleted" in r.json()["detail"]  # was a 500
    assert (await client.delete(f"/events/{test_event.id}/rubric/criteria/{unused.id}", headers=org)).status_code == 204


# ---------------------------------------------------------------- links must be http(s)

BAD_URLS = ["javascript:alert(1)", "JaVaScRiPt:alert(1)", "data:text/html,<script>1</script>", "ftp://files.example.org/x",
            "//evil.example.org/x", "http://", "vbscript:msgbox(1)", "file:///etc/passwd", "not a url"]


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["repo_url", "live_url", "demo_video_url", "thumbnail_url"])
async def test_project_links_must_be_http_or_https(client, test_user, test_submission, field):
    h, url = get_auth_header(test_user), f"/submissions/{test_submission.id}"
    for bad in BAD_URLS:
        r = await client.patch(url, json={field: bad}, headers=h)
        assert r.status_code == 422 and "http" in r.text, (field, bad, r.status_code)
    for good in ("https://example.org/repo", "http://localhost:3000/demo", "", "  https://example.org/padded  "):
        assert (await client.patch(url, json={field: good}, headers=h)).status_code == 200, good
    stored = (await client.get(url, headers=h)).json()[field]
    assert stored in ("https://example.org/padded", "")


@pytest.mark.asyncio
async def test_gallery_images_and_creation_use_the_same_rule(client, test_user, test_team, test_submission):
    h = get_auth_header(test_user)
    r = await client.patch(f"/submissions/{test_submission.id}", json={"gallery_image_urls": ["https://ok.example/1.png", "javascript:alert(1)"]}, headers=h)
    assert r.status_code == 422
    r = await client.post(f"/teams/{test_team.id}/submissions", json={"name": "New", "repo_url": "javascript:alert(1)"}, headers=h)
    assert r.status_code == 422
    r = await client.post(f"/teams/{test_team.id}/submissions", json={"name": "New", "repo_url": "https://ok.example/r"}, headers=h)
    assert r.status_code == 201


@pytest.mark.asyncio
async def test_dumps_cannot_smuggle_script_urls_in(client, test_organizer, test_event):
    dump = {"format": "dogfood-event-dump", "version": 1, "event": {"id": test_event.id, "name": "x"},
            "teams": [{"id": "t1", "name": "T", "invite_code": "abc"}],
            "submissions": [{"id": "s1", "team_id": "t1", "name": "P", "repo_url": "javascript:alert(1)", "status": "submitted"}]}
    r = await client.post(f"/events/{test_event.id}/import", json=dump, headers=get_auth_header(test_organizer))
    assert r.status_code == 422 and "http" in r.json()["detail"]


# ---------------------------------------------------------------- headers

@pytest.mark.asyncio
async def test_every_api_response_carries_basic_security_headers(client, test_event):
    for path in ("/health", f"/events/{test_event.id}", "/openapi.json", "/no-such-route"):
        r = await client.get(path)
        assert r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "no-referrer", path
    r = await client.post("/auth/login", content=b"x" * (3 * 1024 * 1024), headers={"content-type": "application/json"})
    assert r.status_code == 413 and r.headers["x-content-type-options"] == "nosniff"  # even guard rejections


# ---------------------------------------------------------------- draft events are not public

async def _draft(db, owner_user, tag="hidden"):
    ev = Event(organizer_id=owner_user.id, name=f"Draft {tag}", slug=f"draft-{tag}", status=EventStatus.DRAFT)
    db.add(ev)
    await db.commit()
    db.add(EventRole(user_id=owner_user.id, event_id=ev.id, role=EventRoleType.ORGANIZER))
    await db.commit()
    return ev


@pytest.mark.asyncio
async def test_draft_events_are_invisible_to_anonymous_visitors(client, db_session, test_organizer, test_event):
    """Regression: the draft filter used to be skipped when nobody was signed in, exposing every unpublished event."""
    draft = await _draft(db_session, test_organizer)
    names = [e["name"] for e in (await client.get("/events")).json()]
    assert "Draft hidden" not in names and "Test Hackathon" in names
    assert (await client.get(f"/events/{draft.id}")).status_code == 404
    for path in ("tracks", "rubric/criteria", "submissions"):
        assert (await client.get(f"/events/{draft.id}/{path}")).status_code == 404, path
    assert (await client.get(f"/events/{draft.id}/ballot")).status_code == 404
    assert (await client.get(f"/embed/{draft.id}/gallery")).status_code == 404


@pytest.mark.asyncio
async def test_draft_events_are_invisible_to_signed_in_strangers_but_visible_to_their_organizer(client, db_session, test_organizer, test_user, test_event):
    draft = await _draft(db_session, test_organizer)
    stranger, owner = get_auth_header(test_user), get_auth_header(test_organizer)
    assert "Draft hidden" not in [e["name"] for e in (await client.get("/events", headers=stranger)).json()]
    assert (await client.get(f"/events/{draft.id}", headers=stranger)).status_code == 404
    assert (await client.get(f"/events/{draft.id}/tracks", headers=stranger)).status_code == 404
    # its organizer sees and uses it
    assert "Draft hidden" in [e["name"] for e in (await client.get("/events", headers=owner)).json()]
    assert (await client.get(f"/events/{draft.id}", headers=owner)).status_code == 200
    for path in ("tracks", "rubric/criteria", "submissions"):
        assert (await client.get(f"/events/{draft.id}/{path}", headers=owner)).status_code == 200, path
    admin, _ = await _admin(db_session)
    assert (await client.get(f"/events/{draft.id}", headers=admin)).status_code == 200


@pytest.mark.asyncio
async def test_publishing_a_draft_makes_it_public(client, db_session, test_organizer, test_event):
    draft = await _draft(db_session, test_organizer)
    assert (await client.get(f"/events/{draft.id}")).status_code == 404
    r = await client.patch(f"/events/{draft.id}", json={"status": "open"}, headers=get_auth_header(test_organizer))
    assert r.status_code == 200
    assert (await client.get(f"/events/{draft.id}")).status_code == 200
    assert "Draft hidden" in [e["name"] for e in (await client.get("/events")).json()]
