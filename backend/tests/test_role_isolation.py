"""Role isolation tests - the full permission matrix."""

import pytest
from httpx import AsyncClient

from tests.conftest import get_auth_header


@pytest.mark.asyncio
async def test_visitor_can_view_gallery(client: AsyncClient, test_submission):
    response = await client.get(f"/events/{test_submission.event_id}/submissions")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_visitor_cannot_create_event(client: AsyncClient):
    response = await client.post("/events", json={
        "name": "Test",
        "slug": "test",
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_participant_cannot_create_event(client: AsyncClient, test_user):
    response = await client.post("/events", json={
        "name": "Test",
        "slug": "test",
    }, headers=get_auth_header(test_user))
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_judge_cannot_create_event(client: AsyncClient, test_judge):
    response = await client.post("/events", json={
        "name": "Test",
        "slug": "test",
    }, headers=get_auth_header(test_judge))
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_organizer_can_create_event(client: AsyncClient, test_organizer, test_event):
    response = await client.post("/events", json={
        "name": "New Event",
        "slug": "new-event",
    }, headers=get_auth_header(test_organizer))
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_participant_cannot_view_judge_assignments(client: AsyncClient, test_user, test_event):
    response = await client.get(
        f"/events/{test_event.id}/judging/assignments/mine",
        headers=get_auth_header(test_user),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_judge_can_view_own_assignments(client: AsyncClient, test_judge, test_event):
    response = await client.get(
        f"/events/{test_event.id}/judging/assignments/mine",
        headers=get_auth_header(test_judge),
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_organizer_can_view_progress(client: AsyncClient, test_organizer, test_event):
    response = await client.get(
        f"/events/{test_event.id}/judging/progress",
        headers=get_auth_header(test_organizer),
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_judge_cannot_view_progress(client: AsyncClient, test_judge, test_event):
    response = await client.get(
        f"/events/{test_event.id}/judging/progress",
        headers=get_auth_header(test_judge),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_participant_cannot_view_audit_log(client: AsyncClient, test_user):
    response = await client.get("/admin/audit", headers=get_auth_header(test_user))
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_organizer_can_view_audit_log(client: AsyncClient, test_organizer, test_event):
    response = await client.get("/admin/audit", headers=get_auth_header(test_organizer))
    assert response.status_code == 200


# --- Mirrors of the external DOGFOOD checker (run.py) T1/T2 checks, against the real fixtures.json ---

import os
from pathlib import Path

import pytest_asyncio

from app.services.fixture_import import checker_plan, import_fixtures, load_fixtures
from app.services.stable_ids import user_id_for_email
from app.utils.security import create_checker_token


def _real_fixtures() -> dict:
    candidates = [
        os.environ.get("FIXTURES_PATH", ""),
        "/data/fixtures.json",
        str(Path(__file__).resolve().parents[2] / "fixtures.json"),
    ]
    for c in candidates:
        if c and Path(c).is_file():
            data = load_fixtures(c)
            assert data is not None
            return data
    raise AssertionError(f"fixtures.json not found in {candidates}")


def _bearer(email: str) -> dict:
    return {"Authorization": f"Bearer {create_checker_token(user_id_for_email(email), email)}"}


@pytest_asyncio.fixture
async def real_event(db_session):
    data = _real_fixtures()
    summary = await import_fixtures(db_session, data)
    assert summary is not None
    return checker_plan(data)


@pytest.mark.asyncio
async def test_checker_judge_cannot_see_peer_scores(client: AsyncClient, real_event):
    """Checker check 5: judge_b hitting the route that returns judge_a's scores is refused."""
    plan = real_event
    url = f"/submissions/{plan['project_id']}/scores"
    r = await client.get(url, headers=_bearer(plan["judge_b_email"]))
    assert r.status_code in (401, 403)
    # and the judge's own route only ever yields the caller's rows
    mine_a = await client.get(url + "/mine", headers=_bearer(plan["judge_a_email"]))
    mine_b = await client.get(url + "/mine", headers=_bearer(plan["judge_b_email"]))
    assert mine_a.status_code == 200 and mine_b.status_code == 200
    assert mine_a.json()["judge_id"] == user_id_for_email(plan["judge_a_email"])
    assert mine_b.json()["judge_id"] == user_id_for_email(plan["judge_b_email"])


@pytest.mark.asyncio
async def test_checker_participant_blocked_from_judge_scores(client: AsyncClient, real_event):
    """Checker check 6: a participant hitting the judge-scores route is refused."""
    plan = real_event
    url = f"/submissions/{plan['project_id']}/scores/mine"
    r = await client.get(url, headers=_bearer(plan["participant_email"]))
    assert r.status_code in (401, 403)
    assert (await client.get(url)).status_code == 401


@pytest.mark.asyncio
async def test_fixture_event_deadline_rejects_participant_submit(client: AsyncClient, real_event):
    """Checker check 3: submit to the fixture event (submissions_close in the past) => 403."""
    plan = real_event
    r = await client.post(
        f"/teams/{plan['probe_team_id']}/submissions",
        json={"title": "dogfood-late-submission-probe", "summary": "probe"},
        headers=_bearer(plan["participant_email"]),
    )
    assert r.status_code == 403
    assert "deadline" in r.json()["detail"].lower()
