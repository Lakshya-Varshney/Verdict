"""T4+: a judge's own signed proof of their actual scores (not the `judge` certificate, which
never includes the scores and waits for the event to close - see certificate_service.py)."""

import pytest
from httpx import AsyncClient

from app.models.judging import JudgeAssignment, RubricCriterion
from app.services import signing
from tests.conftest import get_auth_header


async def _criterion(db, event_id, lo=1.0, hi=5.0):
    c = RubricCriterion(event_id=event_id, name="Innov", weight=1.0, scale_min=lo, scale_max=hi)
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


async def _score(client, submission, judge, crit, db, value=4, comment="solid"):
    db.add(JudgeAssignment(judge_id=judge.id, submission_id=submission.id))
    await db.commit()
    r = await client.post(f"/submissions/{submission.id}/scores", json={"criterion_id": crit.id, "value": value, "comment": comment},
                          headers=get_auth_header(judge))
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_judge_gets_a_valid_signed_attestation_of_their_own_scores(client: AsyncClient, test_event, test_submission, test_judge, db_session):
    crit = await _criterion(db_session, test_event.id)
    await _score(client, test_submission, test_judge, crit, db_session, value=4, comment="solid work")

    r = await client.get(f"/events/{test_event.id}/judging/attestation", headers=get_auth_header(test_judge))
    assert r.status_code == 200, r.text
    doc = r.json()
    p = doc["payload"]
    assert p["kind"] == "judge_score_attestation" and p["recipient"]["id"] == test_judge.id
    assert len(p["record"]["scores"]) == 1
    s = p["record"]["scores"][0]
    assert s["submission_id"] == test_submission.id and s["criterion_id"] == crit.id
    assert s["value"] == 4 and s["comment"] == "solid work"
    # cryptographically valid, and the public hash is the hash of exactly what was signed
    assert signing.verify(p, doc["signature"]) is True
    assert doc["verify_hash"] == signing.payload_hash(p)
    assert doc["key_id"] == signing.key_id()
    # privacy: no email anywhere in the signed document
    assert "@" not in str(p)


@pytest.mark.asyncio
async def test_judge_with_no_scores_gets_404(client: AsyncClient, test_event, test_judge):
    r = await client.get(f"/events/{test_event.id}/judging/attestation", headers=get_auth_header(test_judge))
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_access_control(client: AsyncClient, test_event, test_submission, test_judge, test_user, test_organizer, db_session):
    crit = await _criterion(db_session, test_event.id)
    await _score(client, test_submission, test_judge, crit, db_session)

    assert (await client.get(f"/events/{test_event.id}/judging/attestation")).status_code == 401
    # a different, non-staff user cannot fetch someone else's attestation
    r = await client.get(f"/events/{test_event.id}/judging/attestation", params={"judge_id": test_judge.id}, headers=get_auth_header(test_user))
    assert r.status_code == 403
    # but an organizer of the event can, for a named judge
    r = await client.get(f"/events/{test_event.id}/judging/attestation", params={"judge_id": test_judge.id}, headers=get_auth_header(test_organizer))
    assert r.status_code == 200 and r.json()["payload"]["recipient"]["id"] == test_judge.id


@pytest.mark.asyncio
async def test_available_before_the_event_closes_unlike_the_judge_certificate(client: AsyncClient, test_event, test_submission, test_judge, db_session):
    assert test_event.status.value != "closed"  # test_event defaults to LIVE
    crit = await _criterion(db_session, test_event.id)
    await _score(client, test_submission, test_judge, crit, db_session)
    r = await client.get(f"/events/{test_event.id}/judging/attestation", headers=get_auth_header(test_judge))
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_reattesting_after_a_new_score_reflects_the_new_state_not_a_stale_copy(client: AsyncClient, test_event, test_submission, test_judge, db_session):
    crit = await _criterion(db_session, test_event.id)
    await _score(client, test_submission, test_judge, crit, db_session, value=2)
    first = (await client.get(f"/events/{test_event.id}/judging/attestation", headers=get_auth_header(test_judge))).json()
    assert first["payload"]["record"]["scores"][0]["value"] == 2

    # the judge changes their mind - scores are an upsert
    await client.post(f"/submissions/{test_submission.id}/scores", json={"criterion_id": crit.id, "value": 5},
                      headers=get_auth_header(test_judge))
    second = (await client.get(f"/events/{test_event.id}/judging/attestation", headers=get_auth_header(test_judge))).json()
    assert second["payload"]["record"]["scores"][0]["value"] == 5
    # not the same document as before: a fresh, distinct signature over the new state
    assert second["signature"] != first["signature"] and second["verify_hash"] != first["verify_hash"]


@pytest.mark.asyncio
async def test_post_verify_accepts_the_document_even_though_it_is_never_stored(client: AsyncClient, test_event, test_submission, test_judge, db_session):
    crit = await _criterion(db_session, test_event.id)
    await _score(client, test_submission, test_judge, crit, db_session)
    doc = (await client.get(f"/events/{test_event.id}/judging/attestation", headers=get_auth_header(test_judge))).json()

    r = await client.post("/verify", json={"payload": doc["payload"], "signature": doc["signature"]})
    body = r.json()
    assert r.status_code == 200 and body["valid"] is True
    # the signature is genuinely ours, but we keep no copy of attestations (they can go stale the
    # moment a judge rescinds), so the "do we have a matching record" flag is honestly False -
    # the same semantics `POST /verify` already gives a validly-signed document we never stored
    assert body["issued_by_this_server"] is False

    # the public by-code lookup must never find it either: unlike a certificate, this payload
    # carries the judge's actual scores, so it must not be reachable by anyone who merely guesses
    # or intercepts the hash - only someone holding the full document can verify it
    assert (await client.get(f"/verify/{doc['verify_hash']}")).status_code == 404


@pytest.mark.asyncio
async def test_issuing_an_attestation_is_audit_logged(client: AsyncClient, test_event, test_submission, test_judge, db_session):
    from sqlalchemy import select
    from app.models.audit import AuditLog

    crit = await _criterion(db_session, test_event.id)
    await _score(client, test_submission, test_judge, crit, db_session)
    await client.get(f"/events/{test_event.id}/judging/attestation", headers=get_auth_header(test_judge))

    logs = (await db_session.execute(select(AuditLog).where(AuditLog.action == "judging.attestation_issued"))).scalars().all()
    assert len(logs) == 1 and logs[0].target_id == test_judge.id and logs[0].event_id == test_event.id
