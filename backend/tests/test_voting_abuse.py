"""T3: public voting, ballot randomisation, anti-abuse, results hiding, audit trail."""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.config import settings
from app.main import app
from app.models.audit import AuditLog
from app.models.event import Event, EventStatus
from app.models.submission import Submission, SubmissionStatus
from app.models.team import Team
from tests.conftest import get_auth_header


async def _set_event(db, event, **fields):
    for k, v in fields.items():
        setattr(event, k, v)
    await db.commit()


async def _make_submissions(db, event, n, status=SubmissionStatus.SUBMITTED):
    subs = []
    for i in range(n):
        team = Team(event_id=event.id, name=f"Team {i}", invite_code=f"code{i}{event.id[:6]}")
        db.add(team)
        await db.flush()
        sub = Submission(team_id=team.id, event_id=event.id, name=f"Project {i}", status=status)
        db.add(sub)
        subs.append(sub)
    await db.commit()
    return subs


def _fresh_client(db_session):
    """A second anonymous browser: its own cookie jar (=> its own voter session)."""
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def voting_event(db_session, test_event):
    await _set_event(db_session, test_event, status=EventStatus.VOTING, voting_mode="open")
    return test_event


# ---------------------------------------------------------------- basics / duplicates

@pytest.mark.asyncio
async def test_duplicate_vote_rejected(client, test_submission, voting_event):
    r1 = await client.post(f"/submissions/{test_submission.id}/vote", json={"fingerprint": "abc"})
    assert r1.status_code == 201
    r2 = await client.post(f"/submissions/{test_submission.id}/vote", json={"fingerprint": "abc"})
    assert r2.status_code == 400


@pytest.mark.asyncio
async def test_one_vote_per_person_per_event(client, db_session, voting_event, test_submission):
    other = (await _make_submissions(db_session, voting_event, 1))[0]
    assert (await client.post(f"/submissions/{test_submission.id}/vote")).status_code == 201
    r = await client.post(f"/submissions/{other.id}/vote")
    assert r.status_code == 400 and "limit" in r.json()["detail"].lower()
    # a different person (fresh cookie jar) can still vote
    async with _fresh_client(db_session) as c2:
        assert (await c2.post(f"/submissions/{other.id}/vote")).status_code == 201


@pytest.mark.asyncio
async def test_votes_per_voter_is_configurable(client, db_session, voting_event, test_submission):
    await _set_event(db_session, voting_event, votes_per_voter=2)
    other = (await _make_submissions(db_session, voting_event, 2))
    codes = [(await client.post(f"/submissions/{s.id}/vote")).status_code for s in (test_submission, *other)]
    assert codes == [201, 201, 400]


@pytest.mark.asyncio
async def test_db_unique_constraint_backs_up_dedup(db_session, voting_event, test_submission):
    from sqlalchemy.exc import IntegrityError
    from app.models.voting import Vote

    kw = dict(submission_id=test_submission.id, event_id=voting_event.id, voter_fingerprint="same")
    db_session.add(Vote(**kw))
    await db_session.commit()
    db_session.add(Vote(**kw))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_cannot_vote_for_a_draft(client, db_session, voting_event):
    draft = (await _make_submissions(db_session, voting_event, 1, status=SubmissionStatus.DRAFT))[0]
    assert (await client.post(f"/submissions/{draft.id}/vote")).status_code == 404


# ---------------------------------------------------------------- window

@pytest.mark.asyncio
@pytest.mark.parametrize("status,needle", [(EventStatus.LIVE, "not started"), (EventStatus.JUDGING, "not started"),
                                           (EventStatus.CLOSED, "ended")])
async def test_voting_blocked_outside_voting_status(client, db_session, voting_event, test_submission, status, needle):
    await _set_event(db_session, voting_event, status=status)
    r = await client.post(f"/submissions/{test_submission.id}/vote")
    assert r.status_code == 400 and needle in r.json()["detail"]


@pytest.mark.asyncio
async def test_voting_respects_dates(client, db_session, voting_event, test_submission):
    now = datetime.now(timezone.utc)
    await _set_event(db_session, voting_event, voting_closes_at=now - timedelta(minutes=1))
    assert "ended" in (await client.post(f"/submissions/{test_submission.id}/vote")).json()["detail"]
    await _set_event(db_session, voting_event, voting_closes_at=None, voting_opens_at=now + timedelta(hours=1))
    assert "not started" in (await client.post(f"/submissions/{test_submission.id}/vote")).json()["detail"]


# ---------------------------------------------------------------- access modes

@pytest.mark.asyncio
async def test_auth_mode_requires_login(client, db_session, voting_event, test_submission, test_user):
    await _set_event(db_session, voting_event, voting_mode="auth")
    assert (await client.post(f"/submissions/{test_submission.id}/vote")).status_code == 401
    r = await client.post(f"/submissions/{test_submission.id}/vote", headers=get_auth_header(test_user))
    assert r.status_code == 201
    # same user again (same identity even from a fresh browser) is a duplicate
    async with _fresh_client(db_session) as c2:
        r = await c2.post(f"/submissions/{test_submission.id}/vote", headers=get_auth_header(test_user))
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_email_mode(client, db_session, voting_event, test_submission):
    await _set_event(db_session, voting_event, voting_mode="email")
    url = f"/submissions/{test_submission.id}/vote"
    assert (await client.post(url)).status_code == 400
    assert (await client.post(url, json={"email": "not-an-email"})).status_code == 400
    assert (await client.post(url, json={"email": "Ada@Example.org"})).status_code == 201
    # the same email in another browser, differently cased, is the same voter
    async with _fresh_client(db_session) as c2:
        assert (await c2.post(url, json={"email": "ada@example.ORG"})).status_code == 400
        assert (await c2.post(url, json={"email": "bob@example.org"})).status_code == 201


@pytest.mark.asyncio
async def test_quadratic_voting(client, db_session, voting_event, test_submission, test_user, test_organizer):
    await _set_event(db_session, voting_event, voting_mode="quadratic", vote_credits=25)
    a = test_submission
    b, c = await _make_submissions(db_session, voting_event, 2)
    h = get_auth_header(test_user)
    assert (await client.post(f"/submissions/{a.id}/vote", json={"votes": 3})).status_code == 401  # needs login
    r = await client.post(f"/submissions/{a.id}/vote", json={"votes": 3}, headers=h)
    assert r.status_code == 201 and r.json()["credits_left"] == 16 and r.json()["votes"] == 3
    r = await client.post(f"/submissions/{b.id}/vote", json={"votes": 4}, headers=h)
    assert r.status_code == 201 and r.json()["credits_left"] == 0
    # over budget: 9 + 16 spent, 1 vote on c costs 1
    r = await client.post(f"/submissions/{c.id}/vote", json={"votes": 1}, headers=h)
    assert r.status_code == 400 and "credits" in r.json()["detail"]
    # re-allocate: lower A to 1 (cost 1) frees 8 credits, then C for 2 (cost 4) fits
    assert (await client.post(f"/submissions/{a.id}/vote", json={"votes": 1}, headers=h)).status_code == 201
    r = await client.post(f"/submissions/{c.id}/vote", json={"votes": 2}, headers=h)
    assert r.status_code == 201 and r.json()["credits_left"] == 4
    # tally = sum of weights (organizer view)
    org = get_auth_header(test_organizer)
    counts = {s.id: (await client.get(f"/submissions/{s.id}/votes/count", headers=org)).json()["count"] for s in (a, b, c)}
    assert counts == {a.id: 1, b.id: 4, c.id: 2}


# ---------------------------------------------------------------- rate limiting

@pytest.mark.asyncio
async def test_vote_rate_limit_returns_429(client, db_session, voting_event, test_submission, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_VOTES_PER_MINUTE", 3)
    await _set_event(db_session, voting_event, votes_per_voter=50)
    subs = await _make_submissions(db_session, voting_event, 5)
    codes = []
    for s in subs:
        r = await client.post(f"/submissions/{s.id}/vote")
        codes.append(r.status_code)
    assert codes[:3] == [201, 201, 201] and codes[3] == 429
    assert int(r.headers["retry-after"]) >= 1


@pytest.mark.asyncio
async def test_rotating_cookies_from_one_ip_still_hits_ip_ceiling(client, db_session, voting_event, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_VOTES_PER_MINUTE", 1)  # per-IP ceiling = 6
    subs = await _make_submissions(db_session, voting_event, 9)
    codes = []
    for s in subs:
        async with _fresh_client(db_session) as c:  # new cookie jar every time
            codes.append((await c.post(f"/submissions/{s.id}/vote")).status_code)
    assert codes.count(201) == 6 and codes[6:] == [429, 429, 429]


@pytest.mark.asyncio
async def test_comment_rate_limit(client, test_submission, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_COMMENTS_PER_MINUTE", 2)
    codes = [(await client.post(f"/submissions/{test_submission.id}/comments", json={"body": f"c{i}"})).status_code
             for i in range(3)]
    assert codes == [201, 201, 429]


# ---------------------------------------------------------------- results hiding

@pytest.mark.asyncio
async def test_results_hidden_during_voting_window(client, db_session, voting_event, test_submission,
                                                   test_organizer, test_user, test_judge):
    await client.post(f"/submissions/{test_submission.id}/vote")
    url = f"/submissions/{test_submission.id}/votes/count"
    for headers in ({}, get_auth_header(test_user), get_auth_header(test_judge)):
        body = (await client.get(url, headers=headers)).json()
        assert body["hidden"] is True and body["count"] is None and body["vote_count"] is None
    org = (await client.get(url, headers=get_auth_header(test_organizer))).json()
    assert org["hidden"] is False and org["count"] == 1
    # ranked results / CSV are organizer-only at every stage
    for path in ("judging/results", "judging/export.csv"):
        assert (await client.get(f"/events/{voting_event.id}/{path}")).status_code == 401
        assert (await client.get(f"/events/{voting_event.id}/{path}", headers=get_auth_header(test_user))).status_code == 403
    # once voting closes the tally is public
    await _set_event(db_session, voting_event, status=EventStatus.CLOSED)
    body = (await client.get(url)).json()
    assert body["hidden"] is False and body["count"] == 1


# ---------------------------------------------------------------- ballot randomisation

@pytest.mark.asyncio
async def test_ballot_order_is_per_session_and_stable(client, db_session, voting_event):
    await _make_submissions(db_session, voting_event, 10)

    async def order(c):
        return [i["id"] for i in (await c.get(f"/events/{voting_event.id}/ballot")).json()["items"]]

    mine, mine_again = await order(client), await order(client)
    assert mine == mine_again and len(mine) == 10  # stable within a session
    async with _fresh_client(db_session) as c2, _fresh_client(db_session) as c3:
        other, third = await order(c2), await order(c3)
    assert len({tuple(mine), tuple(other), tuple(third)}) == 3  # differs across voters
    assert sorted(mine) == sorted(other)


@pytest.mark.asyncio
async def test_ballot_has_no_tallies_and_reports_voter_state(client, db_session, voting_event, test_submission):
    await client.post(f"/submissions/{test_submission.id}/vote")
    body = (await client.get(f"/events/{voting_event.id}/ballot")).json()
    assert body["open"] is True and body["voting_mode"] == "open"
    assert body["voter"]["votes_used"] == 1 and body["voter"]["votes_left"] == 0
    assert all(set(i) <= {"id", "name", "tagline", "thumbnail_url", "tech_tags", "team_name", "track_name"} for i in body["items"])


@pytest.mark.asyncio
async def test_ballot_auth_mode_flags_login(client, db_session, voting_event):
    await _set_event(db_session, voting_event, voting_mode="auth")
    body = (await client.get(f"/events/{voting_event.id}/ballot")).json()
    assert body["requires_auth"] is True and body["voter"] is None


# ---------------------------------------------------------------- audit trail

@pytest.mark.asyncio
async def test_votes_and_denials_are_audited(client, db_session, voting_event, test_submission, test_organizer):
    await client.post(f"/submissions/{test_submission.id}/vote")
    await client.post(f"/submissions/{test_submission.id}/vote")  # duplicate -> denied
    rows = (await db_session.execute(select(AuditLog).where(AuditLog.event_id == voting_event.id))).scalars().all()
    assert sorted(r.action for r in rows) == ["vote.cast", "vote.rejected"]
    org = get_auth_header(test_organizer)
    js = (await client.get("/admin/audit", params={"event_id": voting_event.id}, headers=org)).json()
    assert js["total"] == 2 and {i["action"] for i in js["items"]} == {"vote.cast", "vote.rejected"}
    denied = next(i for i in js["items"] if i["action"] == "vote.rejected")
    assert denied["outcome"] == "denied" and "already" in denied["detail"].lower()
    txt = await client.get("/admin/audit", params={"format": "text", "event_id": voting_event.id}, headers=org)
    assert txt.headers["content-type"].startswith("text/plain") and "vote.cast" in txt.text and "denied" in txt.text


@pytest.mark.asyncio
async def test_score_role_and_assignment_writes_are_audited(client, db_session, test_event, test_submission,
                                                            test_organizer, test_judge, test_user):
    from app.models.judging import RubricCriterion

    org, judge = get_auth_header(test_organizer), get_auth_header(test_judge)
    crit = RubricCriterion(event_id=test_event.id, name="Impact", weight=1.0, scale_min=1.0, scale_max=5.0)
    db_session.add(crit)
    await db_session.commit()
    assert (await client.post(f"/events/{test_event.id}/judging/assign", json={"reviews_per_submission": 1}, headers=org)).status_code == 200
    url = f"/submissions/{test_submission.id}/scores"
    assert (await client.post(url, json={"criterion_id": crit.id, "value": 3}, headers=judge)).status_code == 200
    assert (await client.post(url, json={"criterion_id": crit.id, "value": 5}, headers=judge)).status_code == 200
    r = await client.post(f"/events/{test_event.id}/roles", json={"email": "test@example.com", "role": "judge"}, headers=org)
    assert r.status_code == 201
    actions = [a for (a,) in (await db_session.execute(select(AuditLog.action).where(AuditLog.event_id == test_event.id))).all()]
    for expected in ("assignment.create", "score.create", "score.update", "role.grant"):
        assert expected in actions, actions
    upd = (await db_session.execute(select(AuditLog).where(AuditLog.action == "score.update"))).scalar_one()
    assert upd.extra_data["old"] == 3 and upd.extra_data["new"] == 5


@pytest.mark.asyncio
async def test_audit_log_is_organizer_only(client, test_user):
    assert (await client.get("/admin/audit")).status_code == 401
    assert (await client.get("/admin/audit", headers=get_auth_header(test_user))).status_code == 403


# ---------------------------------------------------------------- comments

@pytest.mark.asyncio
async def test_comment_works(client, test_submission):
    r = await client.post(f"/submissions/{test_submission.id}/comments", json={"body": "Great project!"})
    assert r.status_code == 201 and r.json()["author_name"] == "Anonymous"


@pytest.mark.asyncio
async def test_list_comments(client, test_submission):
    for i in (1, 2):
        await client.post(f"/submissions/{test_submission.id}/comments", json={"body": f"Comment {i}"})
    r = await client.get(f"/submissions/{test_submission.id}/comments")
    assert r.status_code == 200 and [c["body"] for c in r.json()] == ["Comment 1", "Comment 2"]


@pytest.mark.asyncio
async def test_no_comments_on_drafts(client, db_session, test_event):
    draft = (await _make_submissions(db_session, test_event, 1, status=SubmissionStatus.DRAFT))[0]
    assert (await client.post(f"/submissions/{draft.id}/comments", json={"body": "hi"})).status_code == 404


@pytest.mark.asyncio
async def test_vote_count_endpoint_shape(client, test_submission):
    r = await client.get(f"/submissions/{test_submission.id}/votes/count")
    assert r.status_code == 200 and "vote_count" in r.json()


@pytest.mark.asyncio
async def test_event_config_roundtrip_and_validation(client, test_organizer, test_event):
    h = get_auth_header(test_organizer)
    r = await client.post("/events", json={"name": "Vote Fest", "slug": "vote-fest", "voting_mode": "quadratic",
                                           "vote_credits": 40, "votes_per_voter": 2}, headers=h)
    assert r.status_code == 201
    body = r.json()
    assert (body["voting_mode"], body["vote_credits"], body["votes_per_voter"]) == ("quadratic", 40, 2)
    assert (await client.patch(f"/events/{body['id']}", json={"voting_mode": "email"}, headers=h)).json()["voting_mode"] == "email"
    assert (await client.patch(f"/events/{body['id']}", json={"voting_mode": "bogus"}, headers=h)).status_code == 422
