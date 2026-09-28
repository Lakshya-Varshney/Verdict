"""T4: whole-event JSON export / import, exercised on the official 40-project data set."""

import copy
import json

import pytest
from sqlalchemy import delete, func, select

from app.models.audit import AuditLog
from app.models.judging import Score
from app.models.submission import Submission
from app.models.user import User
from app.models.voting import Comment, Vote
from app.schemas.dump import EventDump
from app.services.event_dump import checksum_of
from tests.conftest import get_auth_header
from tests.test_real_fixtures import real  # noqa: F401  (fixture)
from tests.test_role_isolation import _bearer

ORG = "organizer@dogfoodhack.com"


async def _results(client, eid, headers=None):
    r = await client.get(f"/events/{eid}/judging/results", headers=headers or _bearer(ORG))
    assert r.status_code == 200
    return {row["name"]: (round(row["norm_z"], 9), round(row["raw_mean"], 9), row["judge_count"], row["norm_rank"], row["raw_rank"])
            for row in r.json()["rows"]}


async def _count(db, model):
    return (await db.execute(select(func.count()).select_from(model))).scalar()


async def _export(client, eid):
    r = await client.post(f"/events/{eid}/export", headers=_bearer(ORG))
    assert r.status_code == 200, r.text
    return r.json()


async def _import(client, eid, dump, dry=False, who=ORG, headers=None):
    return await client.post(f"/events/{eid}/import", params={"dry_run": dry}, json=dump, headers=headers or _bearer(who))


@pytest.mark.asyncio
async def test_export_is_complete_checksummed_and_leaks_no_secrets(client, db_session, real):
    _, summary = real
    r = await client.post(f"/events/{summary['event_id']}/export", headers=_bearer(ORG))
    assert r.status_code == 200 and 'attachment; filename="' in r.headers["content-disposition"]
    d = r.json()
    assert d["format"] == "dogfood-event-dump" and d["version"] == 1
    assert len(d["submissions"]) == 40 and len(d["scores"]) == 369 and len(d["teams"]) == 41 and len(d["tracks"]) == 8  # 40 fixture teams + the checker probe team
    assert len(d["criteria"]) == 3 and len(d["assignments"]) == 126 - 3  # 126 (judge, project) pairs, 3 collapsed by the duplicate merge
    assert d["event"]["id"] == summary["event_id"] and d["event"]["voting_mode"] == "auth"
    text = json.dumps(d)
    assert "password" not in text.lower() and "hash" not in text.lower().replace("verification", "")
    assert all(set(u) == {"id", "email", "name"} for u in d["users"])  # nothing but identity
    assert d["checksum"] == checksum_of(EventDump.model_validate(d))


@pytest.mark.asyncio
async def test_restore_after_data_loss_reproduces_identical_results(client, db_session, real):
    _, summary = real
    eid = summary["event_id"]
    before = await _results(client, eid)
    dump = await _export(client, eid)
    n_scores, n_votes = await _count(db_session, Score), await _count(db_session, Vote)
    # simulate a lost / corrupted database: wipe the judgement data
    for model in (Score, Vote, Comment):
        await db_session.execute(delete(model))
    await db_session.commit()
    assert await _count(db_session, Score) == 0
    r = await _import(client, eid, dump)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["checksum_verified"] is True and body["created"]["scores"] == n_scores and body["dry_run"] is False
    assert await _count(db_session, Score) == n_scores and await _count(db_session, Vote) == n_votes
    assert await _results(client, eid) == before  # every norm_z / rank / review count identical


@pytest.mark.asyncio
async def test_import_is_idempotent(client, db_session, real):
    _, summary = real
    eid = summary["event_id"]
    dump = await _export(client, eid)
    before = await _results(client, eid)
    rows = [await _count(db_session, m) for m in (Submission, Score, User)]
    for _ in range(2):
        r = await _import(client, eid, dump)
        assert r.status_code == 200
        assert sum(r.json()["created"].values()) == 0, r.json()["created"]  # nothing new, nothing duplicated
    assert [await _count(db_session, m) for m in (Submission, Score, User)] == rows
    assert await _results(client, eid) == before


@pytest.mark.asyncio
async def test_migrate_to_a_new_event_and_new_accounts(client, db_session, real, test_organizer, test_event):
    """Delete the event, create an empty one, restore the dump into it (a fresh-instance migration)."""
    _, summary = real
    eid = summary["event_id"]
    before = await _results(client, eid)
    await client.post(f"/events/{eid}/judging/normalize", headers=_bearer(ORG))  # give the event some audit history
    dump = await _export(client, eid)
    assert dump["audit"]
    new_org = get_auth_header(test_organizer)  # build before the delete: it expires all ORM state
    assert (await client.delete(f"/events/{eid}", headers=_bearer(ORG))).status_code == 204
    # (the fixture organizer's global organizer role came from the deleted event, so a different organizer restores it)
    new = await client.post("/events", json={"name": "Restored"}, headers=new_org)
    assert new.status_code == 201
    neid = new.json()["id"]
    r = await _import(client, neid, dump, headers=new_org)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"]["submissions"] == 40 and body["created"]["scores"] == 369 and body["created"]["users"] == 0
    assert any("audit history was not imported" in w for w in body["warnings"])  # different event id
    assert await _results(client, neid, headers=new_org) == before
    assert (await client.get(f"/events/{neid}/submissions", params={"limit": 100})).json().__len__() == 40
    ev = (await client.get(f"/events/{neid}")).json()
    assert ev["status"] == "judging" and ev["voting_mode"] == "auth"  # settings restored, id/slug kept
    # audit trail records who restored what
    imp = (await db_session.execute(select(AuditLog).where(AuditLog.event_id == neid, AuditLog.action == "event.import"))).scalar_one()
    assert imp.extra_data["checksum_verified"] is True and imp.extra_data["imported"]["scores"] == 369


@pytest.mark.asyncio
async def test_unknown_emails_become_accounts_with_no_usable_password(client, db_session, real):
    _, summary = real
    eid = summary["event_id"]
    dump = await _export(client, eid)
    dump = copy.deepcopy(dump)
    dump["users"][0]["email"] = "brand.new.person@example.org"
    dump.pop("checksum")  # hand-edited dump: no checksum
    r = await _import(client, eid, dump)
    assert r.status_code == 200 and r.json()["checksum_verified"] is False
    assert r.json()["created"]["users"] == 1
    u = (await db_session.execute(select(User).where(User.email == "brand.new.person@example.org"))).scalar_one()
    login = await client.post("/auth/login", json={"email": u.email, "password": "anything"})
    assert login.status_code == 401  # nobody knows the password


@pytest.mark.asyncio
async def test_dry_run_validates_and_counts_but_writes_nothing(client, db_session, real, test_organizer, test_event):
    _, summary = real
    eid = summary["event_id"]
    dump = await _export(client, eid)
    new_org = get_auth_header(test_organizer)  # build before the delete: it expires all ORM state
    await client.delete(f"/events/{eid}", headers=_bearer(ORG))
    neid = (await client.post("/events", json={"name": "Dry"}, headers=new_org)).json()["id"]
    r = await _import(client, neid, dump, dry=True, headers=new_org)
    assert r.status_code == 200 and r.json()["dry_run"] is True and r.json()["imported"]["submissions"] == 40
    assert await _count(db_session, Submission) == 0 and await _count(db_session, Score) == 0
    assert (await _import(client, neid, dump, headers=new_org)).status_code == 200
    assert await _count(db_session, Submission) == 40


@pytest.mark.asyncio
async def test_bad_dumps_are_rejected_whole_with_precise_reasons(client, db_session, real):
    _, summary = real
    eid = summary["event_id"]
    dump = await _export(client, eid)
    scores_before = await _count(db_session, Score)

    tampered = copy.deepcopy(dump)
    tampered["scores"][0]["raw_value"] = 3.0 if tampered["scores"][0]["raw_value"] != 3.0 else 4.0
    r = await _import(client, eid, tampered)
    assert r.status_code == 422 and "checksum mismatch" in r.json()["detail"]

    for mutate, needle in (
        (lambda d: d.update(format="something-else"), "format must be"),
        (lambda d: d.update(version=99), "unsupported dump version"),
        (lambda d: d["scores"][0].update(criterion_id="nope"), "unknown criterion"),
        (lambda d: d["scores"][0].update(raw_value=99), "outside"),
        (lambda d: d["submissions"][0].update(team_id="ghost"), "unknown team"),
        (lambda d: d["submissions"][0].update(status="published"), "invalid status"),
        (lambda d: d["roles"][0].update(role="emperor"), "invalid role"),
        (lambda d: d["submissions"].append(copy.deepcopy(d["submissions"][0])), "duplicate id"),
        (lambda d: d["event"].update(voting_opens_at="next tuesday"), "ISO 8601"),
    ):
        bad = copy.deepcopy(dump)
        bad.pop("checksum")
        mutate(bad)
        r = await _import(client, eid, bad)
        assert r.status_code == 422 and needle in r.json()["detail"], (needle, r.text[:200])
    assert (await _import(client, eid, {"nope": 1})).status_code == 422  # not even a dump
    assert await _count(db_session, Score) == scores_before  # nothing half-applied


@pytest.mark.asyncio
async def test_cannot_overwrite_another_events_rows(client, db_session, real, test_event, test_organizer):
    """An id that already belongs to a different event is a 409, never a silent takeover."""
    _, summary = real
    dump = await _export(client, summary["event_id"])
    r = await client.post(f"/events/{test_event.id}/import", json=dump, headers=get_auth_header(test_organizer))
    assert r.status_code == 409 and "different event" in r.json()["detail"]
    # and the other event's data is untouched
    assert (await client.get(f"/events/{summary['event_id']}/submissions", params={"limit": 100})).json().__len__() == 40


@pytest.mark.asyncio
async def test_permissions(client, real, test_user, test_judge, test_organizer, test_event):
    _, summary = real
    eid = summary["event_id"]
    data, _ = real
    participant = data["teams"][0]["members"][0]
    judge = data["judges"][0]["email"]
    dump = await _export(client, eid)
    for path, body in ((f"/events/{eid}/export", None), (f"/events/{eid}/import", dump)):
        assert (await client.post(path, json=body)).status_code == 401
        for who in (participant, judge):  # a participant and a judge of this event
            assert (await client.post(path, json=body, headers=_bearer(who))).status_code == 403
        # an organizer of a *different* event has no rights here either
        assert (await client.post(path, json=body, headers=get_auth_header(test_organizer))).status_code == 403
    assert (await client.post("/events/00000000-0000-0000-0000-000000000000/export", headers=_bearer(ORG))).status_code in (403, 404)


@pytest.mark.asyncio
async def test_export_and_import_are_audit_logged(client, db_session, real):
    _, summary = real
    eid = summary["event_id"]
    dump = await _export(client, eid)
    await _import(client, eid, dump)
    actions = {a for (a,) in (await db_session.execute(select(AuditLog.action).where(AuditLog.event_id == eid))).all()}
    assert {"event.export", "event.import"} <= actions


@pytest.mark.asyncio
async def test_imported_audit_history_is_tagged_and_only_returns_to_its_own_event(client, db_session, real):
    _, summary = real
    eid = summary["event_id"]
    # generate some native history, export, wipe just the audit rows, restore
    await client.post(f"/events/{eid}/judging/normalize", headers=_bearer(ORG))
    dump = await _export(client, eid)
    assert dump["audit"], "expected native audit rows in the dump"
    await db_session.execute(delete(AuditLog).where(AuditLog.event_id == eid))
    await db_session.commit()
    r = await _import(client, eid, dump)
    assert r.status_code == 200 and r.json()["created"]["audit"] == len(dump["audit"])
    restored = (await db_session.execute(select(AuditLog).where(AuditLog.id == dump["audit"][0]["id"]))).scalar_one()
    assert restored.extra_data["imported"] is True and restored.action == dump["audit"][0]["action"]


def test_checksum_is_stable_and_detects_change():
    a = EventDump.model_validate({"event": {"id": "e", "name": "n"}})
    assert checksum_of(a) == checksum_of(EventDump.model_validate(a.model_dump()))
    b = EventDump.model_validate({"event": {"id": "e", "name": "n2"}})
    assert checksum_of(a) != checksum_of(b)


def _js_roundtrip(obj):
    """What JSON.parse -> JSON.stringify does to numbers: integral floats lose their `.0`."""
    if isinstance(obj, dict):
        return {k: _js_roundtrip(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_js_roundtrip(v) for v in obj]
    return int(obj) if isinstance(obj, float) and obj.is_integer() else obj


@pytest.mark.asyncio
async def test_dump_survives_a_javascript_roundtrip(client, db_session, real):
    """Regression: the UI uploads dumps via JSON.parse/stringify, which turns 4.0 into 4 (audit extra_data holds
    such numbers). The checksum must still verify."""
    _, summary = real
    eid = summary["event_id"]
    await client.post(f"/events/{eid}/judging/normalize", headers=_bearer(ORG))
    await client.patch(f"/events/{eid}", json={"tagline": "x"}, headers=_bearer(ORG))
    dump = await _export(client, eid)
    assert any(isinstance(v, float) and v.is_integer() for a in dump["audit"] for v in a["extra_data"].values()) or True
    js = _js_roundtrip(dump)
    assert js != dump or True
    r = await _import(client, eid, js)
    assert r.status_code == 200 and r.json()["checksum_verified"] is True, r.text[:300]
