"""Regression tests for bugs found in the deep live sweep."""

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.event import Event
from app.models.judging import JudgeAssignment, RubricCriterion, Score
from tests.conftest import get_auth_header


@pytest.mark.asyncio
async def test_user_cannot_create_or_join_a_second_team(client: AsyncClient, test_event, test_user, test_team, db_session):
    r = await client.post(f"/events/{test_event.id}/teams", json={"name": "Second"}, headers=get_auth_header(test_user))
    assert r.status_code == 400 and "already in a team" in r.json()["detail"]


@pytest.mark.asyncio
async def test_event_patch_persists_tagline(client: AsyncClient, test_event, test_organizer):
    h = get_auth_header(test_organizer)
    r = await client.patch(f"/events/{test_event.id}", json={"tagline": "Build fast"}, headers=h)
    assert r.status_code == 200 and r.json()["tagline"] == "Build fast"
    # description edit keeps the tagline
    r = await client.patch(f"/events/{test_event.id}", json={"description": "Details"}, headers=h)
    assert r.json()["tagline"] == "Build fast" and r.json()["description"] == "Details"


async def _criterion(db, event_id, lo=1.0, hi=5.0):
    c = RubricCriterion(event_id=event_id, name="Innov", weight=1.0, scale_min=lo, scale_max=hi)
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


@pytest.mark.asyncio
async def test_score_must_be_within_criterion_scale(client: AsyncClient, test_event, test_submission, test_judge, db_session):
    crit = await _criterion(db_session, test_event.id)
    db_session.add(JudgeAssignment(judge_id=test_judge.id, submission_id=test_submission.id))
    await db_session.commit()
    h = get_auth_header(test_judge)
    url = f"/submissions/{test_submission.id}/scores"
    assert (await client.post(url, json={"criterion_id": crit.id, "value": 99}, headers=h)).status_code == 400
    assert (await client.post(url, json={"criterion_id": crit.id, "value": 0}, headers=h)).status_code == 400
    assert (await client.post(url, json={"criterion_id": "00000000-0000-0000-0000-000000000000", "value": 3}, headers=h)).status_code == 400
    assert (await client.post(url, json={"criterion_id": crit.id, "value": 5}, headers=h)).status_code == 200
    assert (await db_session.execute(select(Score))).scalars().all()[0].raw_value == 5


@pytest.mark.asyncio
async def test_empty_comment_rejected(client: AsyncClient, test_submission, test_user):
    r = await client.post(f"/submissions/{test_submission.id}/comments", json={"body": ""}, headers=get_auth_header(test_user))
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_non_leader_cannot_remove_member(client: AsyncClient, test_team, test_user, test_judge):
    r = await client.delete(f"/teams/{test_team.id}/members/{test_user.id}", headers=get_auth_header(test_judge))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_delete_event_with_full_graph(client: AsyncClient, test_event, test_submission, test_judge, test_organizer, db_session):
    crit = await _criterion(db_session, test_event.id)
    db_session.add(JudgeAssignment(judge_id=test_judge.id, submission_id=test_submission.id))
    await db_session.commit()
    h = get_auth_header(test_judge)
    await client.post(f"/submissions/{test_submission.id}/scores", json={"criterion_id": crit.id, "value": 4}, headers=h)
    org = get_auth_header(test_organizer)
    assert (await client.post(f"/events/{test_event.id}/judging/normalize", headers=org)).status_code == 200
    assert (await client.delete(f"/events/{test_event.id}", headers=org)).status_code == 204
    assert (await client.get(f"/events/{test_event.id}")).status_code == 404
    assert (await db_session.execute(select(Event).where(Event.id == test_event.id))).scalar_one_or_none() is None
