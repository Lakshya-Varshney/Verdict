"""Submission CRUD and deadline enforcement tests."""

import pytest
from datetime import datetime, timedelta, timezone
from httpx import AsyncClient

from tests.conftest import get_auth_header
from app.models.submission import SubmissionStatus
from app.models.event import Event, EventStatus
from app.models.team import Team, TeamMembership, TeamRoleType
from app.utils.security import get_password_hash


@pytest.mark.asyncio
async def test_create_submission(client: AsyncClient, test_team, test_event, test_user):
    response = await client.post(
        f"/teams/{test_team.id}/submissions",
        json={"name": "New Submission"},
        headers=get_auth_header(test_user),
    )
    assert response.status_code == 201
    assert response.json()["name"] == "New Submission"


@pytest.mark.asyncio
async def test_get_submission(client: AsyncClient, test_submission):
    response = await client.get(f"/submissions/{test_submission.id}")
    assert response.status_code == 200
    assert response.json()["name"] == "Test Submission"


@pytest.mark.asyncio
async def test_update_submission(client: AsyncClient, test_submission, test_user):
    response = await client.patch(
        f"/submissions/{test_submission.id}",
        json={"name": "Updated Name"},
        headers=get_auth_header(test_user),
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Updated Name"


@pytest.mark.asyncio
async def test_submit_submission(client: AsyncClient, test_team, test_event, test_user, db_session):
    from app.models.submission import Submission
    draft = Submission(
        team_id=test_team.id,
        event_id=test_event.id,
        name="Draft Submission",
        status=SubmissionStatus.DRAFT,
    )
    db_session.add(draft)
    await db_session.commit()
    await db_session.refresh(draft)

    response = await client.post(
        f"/submissions/{draft.id}/submit",
        headers=get_auth_header(test_user),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "submitted"


@pytest.mark.asyncio
async def test_list_event_submissions(client: AsyncClient, test_event):
    response = await client.get(f"/events/{test_event.id}/submissions")
    assert response.status_code == 200
    assert isinstance(response.json(), list)
