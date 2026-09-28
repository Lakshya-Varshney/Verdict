"""T4: certificates + signed judge participation records, on the official 40-project data."""

import base64
import hashlib
import importlib.util
import json
import os
import random
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.certificate import Certificate
from app.models.event import EventStatus
from app.models.judging import Score
from app.models.submission import Submission
from app.models.team import TeamMembership
from app.models.user import User
from app.services import signing
from app.services.stable_ids import user_id_for_email
from tests.test_real_fixtures import real  # noqa: F401  (fixture)
from tests.test_role_isolation import _bearer

ORG = "organizer@dogfoodhack.com"

_spec = importlib.util.spec_from_file_location("verify_certificate", Path(__file__).resolve().parents[1] / "scripts" / "verify_certificate.py")
offline = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(offline)


async def _close(db, eid):
    from app.models.event import Event

    ev = await db.get(Event, eid)
    ev.status = EventStatus.CLOSED
    await db.commit()


async def _team_emails(db, sub_name):
    rows = (await db.execute(
        select(User.email).join(TeamMembership, TeamMembership.user_id == User.id)
        .join(Submission, Submission.team_id == TeamMembership.team_id).where(Submission.name == sub_name))).all()
    return [r[0] for r in rows]


async def _winner_and_loser(client, db, eid):
    res = (await client.get(f"/events/{eid}/judging/results", headers=_bearer(ORG))).json()["rows"]
    by_rank = sorted(res, key=lambda r: r["norm_rank"])
    return (await _team_emails(db, by_rank[0]["name"]))[0], (await _team_emails(db, by_rank[-1]["name"]))[0], by_rank


async def _get(client, eid, email, who=None, **params):
    return await client.get(f"/events/{eid}/certificates/{user_id_for_email(email)}", params=params, headers=_bearer(who or email))


# ---------------------------------------------------------------- rules

@pytest.mark.asyncio
async def test_certificates_are_only_issued_once_the_event_is_closed(client, db_session, real):
    data, summary = real
    email = data["teams"][0]["members"][0]
    r = await _get(client, summary["event_id"], email)
    assert r.status_code == 403 and "closed" in r.json()["detail"]
    await _close(db_session, summary["event_id"])
    assert (await _get(client, summary["event_id"], email)).status_code == 200


@pytest.mark.asyncio
async def test_participant_certificate_is_signed_stable_private_and_audited(client, db_session, real):
    data, summary = real
    eid = summary["event_id"]
    await _close(db_session, eid)
    _, loser, _ = await _winner_and_loser(client, db_session, eid)
    first = await _get(client, eid, loser)
    assert first.status_code == 200, first.text
    c = first.json()
    assert c["kind"] == "participant" and c["algorithm"] == "Ed25519" and c["event_id"] == eid
    assert c["user_id"] == user_id_for_email(loser) and c["detail"].startswith("Built and submitted")
    # cryptographically valid, and the public code is the hash of exactly what was signed
    assert signing.verify(c["payload"], c["signature"]) and c["verify_hash"] == signing.payload_hash(c["payload"])
    assert c["key_id"] == signing.key_id() and c["verify_url"].endswith(f"/verify/{c['verify_hash']}")
    # privacy: no email, no scores in the signed document
    blob = json.dumps(c["payload"])
    assert "@" not in blob and "raw_value" not in blob and set(c["payload"]) == {"v", "issuer", "kind", "event", "recipient", "detail", "issued_at"}
    # stable: same document every time, issued exactly once, audit-logged once
    again = (await _get(client, eid, loser)).json()
    assert again["signature"] == c["signature"] and again["issued_at"] == c["issued_at"] and again["verify_hash"] == c["verify_hash"]
    n = (await db_session.execute(select(Certificate).where(Certificate.user_id == user_id_for_email(loser)))).scalars().all()
    assert len(n) == 1
    logs = (await db_session.execute(select(AuditLog).where(AuditLog.action == "certificate.issue", AuditLog.event_id == eid))).scalars().all()
    assert len(logs) == 1 and logs[0].extra_data["verify_hash"] == c["verify_hash"]


@pytest.mark.asyncio
async def test_judge_participation_record_has_counts_and_period_but_never_scores(client, db_session, real):
    data, summary = real
    eid = summary["event_id"]
    await _close(db_session, eid)
    judge = next(j for j in data["judges"] if j["name"] == "Iva Petrova")
    r = await _get(client, eid, judge["email"])
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["kind"] == "judge"
    uid = user_id_for_email(judge["email"])
    scores = (await db_session.execute(select(Score).join(Submission).where(Submission.event_id == eid, Score.judge_id == uid))).scalars().all()
    rec = c["payload"]["record"]
    assert rec["criterion_scores"] == len(scores) and rec["projects_reviewed"] == len({s.submission_id for s in scores})
    assert rec["first_review"] <= rec["last_review"] and str(rec["projects_reviewed"]) in c["detail"]
    assert not any(k in json.dumps(c["payload"]) for k in ("raw_value", "criterion_id", "comment", "functionality"))
    assert signing.verify(c["payload"], c["signature"])


@pytest.mark.asyncio
async def test_winner_priority_kinds_and_not_earned(client, db_session, real):
    data, summary = real
    eid = summary["event_id"]
    await _close(db_session, eid)
    winner, loser, ranked = await _winner_and_loser(client, db_session, eid)
    w = (await _get(client, eid, winner)).json()
    assert w["kind"] == "winner" and "1st" in w["detail"] and ranked[0]["name"] in w["detail"]
    assert (await _get(client, eid, winner, kind="participant")).json()["kind"] == "participant"  # can still ask for the other one
    assert (await _get(client, eid, loser, kind="winner")).status_code == 404  # not earned
    assert (await _get(client, eid, loser, kind="judge")).status_code == 404
    assert (await _get(client, eid, loser, kind="emperor")).status_code == 422
    assert w["payload"]["record"] == {"place": 1, "projects_ranked": 40}


@pytest.mark.asyncio
async def test_access_control(client, db_session, real):
    data, summary = real
    eid = summary["event_id"]
    await _close(db_session, eid)
    a, b = data["teams"][0]["members"][0], data["teams"][1]["members"][0]
    uid = user_id_for_email(a)
    assert (await client.get(f"/events/{eid}/certificates/{uid}")).status_code == 401
    assert (await _get(client, eid, a, who=b)).status_code == 403  # another participant
    assert (await _get(client, eid, a, who=ORG)).status_code == 200  # an organizer may fetch anyone's
    assert (await client.get(f"/events/{eid}/certificates/{user_id_for_email('ghost@example.org')}", headers=_bearer(ORG))).status_code == 404
    assert (await client.get(f"/events/00000000-0000-0000-0000-000000000000/certificates/{uid}", headers=_bearer(a))).status_code == 404


# ---------------------------------------------------------------- formats

@pytest.mark.asyncio
async def test_pdf_is_a_real_deterministic_pdf_with_the_verification_code(client, db_session, real):
    data, summary = real
    eid = summary["event_id"]
    await _close(db_session, eid)
    email = data["teams"][2]["members"][0]
    r = await _get(client, eid, email, format="pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF-") and b"%%EOF" in r.content[-32:]
    code = (await _get(client, eid, email)).json()["verify_hash"]
    assert code.encode() in r.content and b"/verify/" in r.content and b"Ed25519" in r.content
    assert (await _get(client, eid, email, format="pdf")).content == r.content  # byte-identical


@pytest.mark.asyncio
async def test_html_is_escaped_and_carries_a_document_the_offline_verifier_accepts(client, db_session, real):
    data, summary = real
    eid = summary["event_id"]
    await _close(db_session, eid)
    email = data["teams"][3]["members"][0]
    u = (await db_session.execute(select(User).where(User.email == email))).scalar_one()
    u.name = '</script><img src=x onerror=alert(1)> Ada'
    await db_session.commit()
    r = await _get(client, eid, email, format="html")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    page = r.text
    assert "<img src=x" not in page and "</script><img" not in page
    assert "&lt;/script&gt;&lt;img src=x onerror=alert(1)&gt; Ada" in page
    # the embedded signed document round-trips through the stdlib-only verifier
    doc = offline.load_text(page) if hasattr(offline, "load_text") else json.loads(
        page.split('id="dogfood-certificate">', 1)[1].split("</script>", 1)[0])
    assert doc["payload"]["recipient"]["name"].startswith("</script>")  # data intact inside JSON
    ok, notes = offline.verify_document(doc, signing.public_key_b64())
    assert ok, notes


# ---------------------------------------------------------------- public verification

@pytest.mark.asyncio
async def test_public_verification_by_code_and_by_document(client, db_session, real):
    data, summary = real
    eid = summary["event_id"]
    await _close(db_session, eid)
    email = data["teams"][4]["members"][0]
    c = (await _get(client, eid, email)).json()
    v = await client.get(f"/verify/{c['verify_hash']}")  # no auth
    assert v.status_code == 200 and v.json()["valid"] is True and v.json()["certificate"] == c["payload"]
    assert (await client.get(f"/verify/{c['verify_hash'].upper()}")).json()["valid"] is True
    assert (await client.get("/verify/" + "0" * 64)).status_code == 404

    good = await client.post("/verify", json={"payload": c["payload"], "signature": c["signature"]})
    assert good.json()["valid"] is True and good.json()["issued_by_this_server"] is True
    forged = json.loads(json.dumps(c["payload"]))
    forged["recipient"]["name"] = "Someone Else"
    bad = (await client.post("/verify", json={"payload": forged, "signature": c["signature"]})).json()
    assert bad["valid"] is False and bad["certificate"] is None
    for junk in ("", "AAAA", "!!!not-base64!!!", c["signature"][:-4] + "AAAA"):
        r = await client.post("/verify", json={"payload": c["payload"], "signature": junk})
        assert r.status_code == 200 and r.json()["valid"] is False  # never a 500
    # a validly signed document that this server never issued is valid but flagged
    other = {**c["payload"], "detail": "hand-made"}
    sig = signing.sign(other)
    r = (await client.post("/verify", json={"payload": other, "signature": sig})).json()
    assert r["valid"] is True and r["issued_by_this_server"] is False


@pytest.mark.asyncio
async def test_database_tampering_is_detected_by_the_public_endpoint(client, db_session, real):
    data, summary = real
    eid = summary["event_id"]
    await _close(db_session, eid)
    email = data["teams"][5]["members"][0]
    c = (await _get(client, eid, email)).json()
    row = (await db_session.execute(select(Certificate).where(Certificate.verification_hash == c["verify_hash"]))).scalar_one()
    row.payload = {**row.payload, "detail": "Placed 1st of 40"}  # someone edits the stored record
    await db_session.commit()
    v = (await client.get(f"/verify/{c['verify_hash']}")).json()
    assert v["valid"] is False


@pytest.mark.asyncio
async def test_public_key_endpoint_matches_the_signatures(client, db_session, real):
    data, summary = real
    eid = summary["event_id"]
    await _close(db_session, eid)
    k = (await client.get("/.well-known/dogfood-signing-key")).json()
    assert k["algorithm"] == "Ed25519" and len(signing.b64u_decode(k["public_key"])) == 32
    c = (await _get(client, eid, data["teams"][6]["members"][0])).json()
    assert c["key_id"] == k["key_id"] == hashlib.sha256(signing.b64u_decode(k["public_key"])).hexdigest()[:16]


# ---------------------------------------------------------------- the offline verifier

def test_stdlib_ed25519_agrees_with_cryptography_on_valid_and_forged_signatures():
    rnd = random.Random(7)
    for _ in range(12):
        key = Ed25519PrivateKey.from_private_bytes(rnd.randbytes(32))
        pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        msg = rnd.randbytes(rnd.randint(0, 200))
        sig = key.sign(msg)
        assert offline.ed25519_verify(sig, msg, pub) is True
        assert offline.ed25519_verify(sig, msg + b"x", pub) is False
        bad = bytearray(sig)
        bad[rnd.randrange(64)] ^= 1 << rnd.randrange(8)
        assert offline.ed25519_verify(bytes(bad), msg, pub) is False
    assert offline.ed25519_verify(b"\x00" * 64, b"m", pub) is False and offline.ed25519_verify(b"short", b"m", pub) is False


@pytest.mark.asyncio
async def test_offline_verifier_accepts_real_certificates_and_rejects_tampering_and_wrong_keys(client, db_session, real):
    data, summary = real
    eid = summary["event_id"]
    await _close(db_session, eid)
    c = (await _get(client, eid, data["teams"][7]["members"][0])).json()
    key = signing.public_key_b64()
    assert offline.verify_document(c, key)[0] is True
    tampered = json.loads(json.dumps(c))
    tampered["payload"]["kind"] = "winner"
    ok, notes = offline.verify_document(tampered, key)
    assert ok is False and any("does NOT match" in n for n in notes)
    other = Ed25519PrivateKey.from_private_bytes(os.urandom(32)).public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    ok, notes = offline.verify_document(c, base64.urlsafe_b64encode(other).rstrip(b"=").decode())
    assert ok is False and any("signed by key" in n for n in notes)
    assert offline.verify_document({"payload": 1}, key)[0] is False


def test_signing_key_is_deterministic_and_rotates_with_the_secret(monkeypatch):
    from app.config import settings

    first = signing.key_id()
    assert signing.key_id() == first
    monkeypatch.setattr(settings, "CERT_SIGNING_KEY", "a-different-secret")
    signing._private_key.cache_clear()
    try:
        assert signing.key_id() != first
    finally:
        monkeypatch.undo()
        signing._private_key.cache_clear()
    assert signing.key_id() == first


def test_pdf_handles_typographic_quotes_and_very_long_names():
    from app.services.certificate_render import _fit, _latin1, render_pdf

    assert _latin1("Placed 1st with “Iron Switch” — wow…") == 'Placed 1st with "Iron Switch" - wow...'
    assert _latin1("Zoë 中文") == "Zoë ??"  # Latin-1 survives, other scripts degrade instead of crashing
    payload = {"v": 1, "issuer": "DOGFOOD", "kind": "winner", "event": {"id": "e", "name": "E" * 200},
               "recipient": {"id": "u", "name": "Bartholomew " * 12}, "detail": "Placed 1st with “X”", "issued_at": "2027-01-01T00:00:00Z"}
    pdf = render_pdf(payload, "s" * 86, "a" * 64, "k" * 16)
    assert pdf.startswith(b"%PDF-") and b'Placed 1st with "X"' in pdf
    assert _fit("W" * 400, "Times-Italic", 46, 700) < 46  # shrinks to fit instead of overflowing the page
