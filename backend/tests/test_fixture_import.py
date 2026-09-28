"""Fixture import + DOGFOOD checker compliance tests (raw API calls, no UI)."""

import copy

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.models.judging import RubricCriterion, Score
from app.models.submission import Submission
from app.services.fixture_import import checker_plan, import_fixtures, resolve_projects
from app.services.stable_ids import stable_id, user_id_for_email
from app.utils.security import create_checker_token
from tests.conftest import get_auth_header

FIXTURES = {
    "event": {"id": "evt_t", "name": "Test Hack", "submissions_close": "2026-03-01T18:00:00Z"},
    "tracks": [{"id": "trk_1", "name": "Tools"}],
    "judges": [
        {"id": "j1", "name": "Lenient", "email": "j1@example.org", "tracks": ["trk_1"]},
        {"id": "j2", "name": "Harsh", "email": "j2@example.org", "tracks": ["trk_1"]},
        {"id": "j3", "name": "Flat", "email": "j3@example.org", "tracks": []},
    ],
    # j1 is also a member of team A: one user holding judge + participant roles
    "teams": [
        {"id": "tmA", "name": "A", "members": ["j1@example.org", "p1@example.org"]},
        {"id": "tmB", "name": "B", "members": ["p2@example.org"]},
    ],
    "projects": [
        {"id": "p1", "team": "tmA", "track": "trk_1", "title": "Alpha", "summary": "a",
         "repo_url": "https://example.org/a", "submitted_at": "2026-02-20T10:00:00Z"},
        {"id": "p2", "team": "tmB", "track": "trk_1", "title": "Beta", "summary": "b",
         "repo_url": "https://example.org/b", "submitted_at": "2026-02-21T10:00:00Z"},
        {"id": "p3", "team": "tmB", "track": "trk_1", "title": "Gamma", "summary": "c",
         "repo_url": "https://example.org/c", "submitted_at": "2026-02-22T10:00:00Z"},
        # same id again: last write wins
        {"id": "p3", "team": "tmB", "track": "trk_1", "title": "Gamma", "summary": "c v2",
         "repo_url": "https://example.org/c", "submitted_at": "2026-02-22T10:00:00Z"},
        # new id, same team + title as p1: merged into p1
        {"id": "p9", "team": "tmA", "track": "trk_1", "title": " Alpha ", "summary": "a v2",
         "repo_url": "https://example.org/a", "submitted_at": "2026-02-23T10:00:00Z"},
    ],
    "scores": [
        {"judge": "j1", "project": "p1", "criteria": {"functionality": 5, "quality": 5}, "comment": ""},
        {"judge": "j1", "project": "p2", "criteria": {"functionality": 4, "quality": 4}, "comment": "ok"},
        {"judge": "j1", "project": "p3", "criteria": {"functionality": 3, "quality": 3}, "comment": ""},
        {"judge": "j2", "project": "p1", "criteria": {"functionality": 3, "quality": 3}, "comment": ""},
        {"judge": "j2", "project": "p2", "criteria": {"functionality": 2, "quality": 2}, "comment": ""},
        # j3 gives everything the same; only j3 uses the "originality" criterion
        {"judge": "j3", "project": "p1", "criteria": {"functionality": 3, "quality": 3, "originality": 3}, "comment": ""},
        {"judge": "j3", "project": "p2", "criteria": {"functionality": 3, "quality": 3, "originality": 3}, "comment": ""},
        {"judge": "j3", "project": "p3", "criteria": {"functionality": 3, "quality": 3, "originality": 3}, "comment": ""},
        # duplicate of an earlier (judge, project): last write wins
        {"judge": "j1", "project": "p3", "criteria": {"functionality": 2, "quality": 2}, "comment": "revised"},
        # unknown project: skipped, must not crash
        {"judge": "j1", "project": "nope", "criteria": {"functionality": 1}, "comment": ""},
    ],
}


def bearer(email: str) -> dict:
    return {"Authorization": f"Bearer {create_checker_token(user_id_for_email(email), email)}"}


@pytest_asyncio.fixture
async def imported(db_session):
    data = copy.deepcopy(FIXTURES)
    summary = await import_fixtures(db_session, data)
    return data, summary


@pytest.mark.asyncio
async def test_import_maps_and_tolerates_awkward_data(db_session, imported):
    data, summary = imported
    assert summary["projects"] == 3  # p3 repeated + p9 alias of p1 collapsed
    assert summary["criteria"] == 3  # functionality, quality, originality auto-created
    projects, canon = resolve_projects(data)
    assert canon["p9"] == "p1"
    assert projects["p3"]["summary"] == "c v2"  # last write wins

    subs = (await db_session.execute(select(Submission))).scalars().all()
    assert {s.name for s in subs} == {"Alpha", "Beta", "Gamma"}
    assert {s.id for s in subs} == {stable_id("project", p) for p in ("p1", "p2", "p3")}

    crit = {c.name: c for c in (await db_session.execute(select(RubricCriterion))).scalars().all()}
    assert crit["functionality"].weight == 1.0 and crit["functionality"].scale_max == 5.0

    j1_p3 = (
        await db_session.execute(
            select(Score).where(
                Score.judge_id == user_id_for_email("j1@example.org"),
                Score.submission_id == stable_id("project", "p3"),
                Score.criterion_id == crit["functionality"].id,
            )
        )
    ).scalar_one()
    assert j1_p3.raw_value == 2 and j1_p3.comment == "revised"


@pytest.mark.asyncio
async def test_import_is_idempotent(db_session, imported):
    data, _ = imported
    assert await import_fixtures(db_session, copy.deepcopy(data)) is None


@pytest.mark.asyncio
async def test_gallery_shows_every_fixture_project(client: AsyncClient, imported):
    data, summary = imported
    r = await client.get(f"/events/{summary['event_id']}/submissions")
    assert r.status_code == 200
    assert [x["name"] for x in r.json()] == ["Alpha", "Beta", "Gamma"]  # fixture order


@pytest.mark.asyncio
async def test_results_count_uneven_reviews_and_flag_flat_judge(client: AsyncClient, imported):
    data, summary = imported
    r = await client.get(
        f"/events/{summary['event_id']}/judging/results", headers=bearer("organizer@dogfoodhack.com")
    )
    assert r.status_code == 200
    body = r.json()
    rows = {row["name"]: row for row in body["rows"]}
    # every scored project is ranked even though judges scored different criteria
    assert set(rows) == {"Alpha", "Beta", "Gamma"}
    assert rows["Alpha"]["judge_count"] == 3
    assert rows["Beta"]["judge_count"] == 3
    assert rows["Gamma"]["judge_count"] == 2
    assert body["zero_variance_judges"] == [user_id_for_email("j3@example.org")]
    # z-scale, not raw points: a flat judge must not push anything off the scale
    assert all(abs(row["norm_z"]) < 3 for row in rows.values())
    # lenient and harsh judge agree A > B: normalised order must agree
    assert rows["Alpha"]["norm_rank"] < rows["Beta"]["norm_rank"]


@pytest.mark.asyncio
async def test_csv_export_is_csv_for_organizer_only(client: AsyncClient, imported):
    _, summary = imported
    url = f"/events/{summary['event_id']}/judging/export.csv"
    ok = await client.get(url, headers=bearer("organizer@dogfoodhack.com"))
    assert ok.status_code == 200 and ok.headers["content-type"].startswith("text/csv")
    lines = ok.text.splitlines()
    assert lines[0].startswith("rank,submission,team") and len(lines) == 4
    assert (await client.get(url, headers=bearer("j1@example.org"))).status_code == 403
    assert (await client.get(url)).status_code == 401


@pytest.mark.asyncio
async def test_peer_scores_are_isolated(client: AsyncClient, imported):
    data, _ = imported
    sid = stable_id("project", "p1")
    # judge_b must not reach the all-judges listing that would expose judge_a's scores
    assert (await client.get(f"/submissions/{sid}/scores", headers=bearer("j2@example.org"))).status_code == 403
    # ... and /mine only ever returns the caller's own rows
    mine = await client.get(f"/submissions/{sid}/scores/mine", headers=bearer("j2@example.org"))
    assert mine.status_code == 200
    assert mine.json()["judge_id"] == user_id_for_email("j2@example.org")
    assert len(mine.json()["scores"]) == 2  # functionality + quality, only j2's own rows
    # organizer sees everyone
    assert (await client.get(f"/submissions/{sid}/scores", headers=bearer("organizer@dogfoodhack.com"))).status_code == 200
    # participant blocked on both
    p = bearer("p1@example.org")
    assert (await client.get(f"/submissions/{sid}/scores/mine", headers=p)).status_code == 403
    assert (await client.get(f"/submissions/{sid}/scores", headers=p)).status_code == 403
    assert (await client.get(f"/submissions/{sid}/scores/mine")).status_code == 401


@pytest.mark.asyncio
async def test_roles_are_scoped_to_the_submissions_event(client: AsyncClient, imported, db_session, test_submission, test_organizer):
    # test_organizer organises a *different* event; must not read this event's scores
    other = stable_id("project", "p1")
    r = await client.get(f"/submissions/{other}/scores", headers=get_auth_header(test_organizer))
    assert r.status_code == 403
    # but is fine on their own event's submission
    r = await client.get(f"/submissions/{test_submission.id}/scores", headers=get_auth_header(test_organizer))
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_user_with_two_roles_in_one_event_does_not_500(client: AsyncClient, imported):
    _, summary = imported
    # j1 is judge AND participant (team member) in the event
    r = await client.get(
        f"/events/{summary['event_id']}/judging/assignments/mine", headers=bearer("j1@example.org")
    )
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_closed_event_refuses_checker_style_submit(client: AsyncClient, imported):
    data, _ = imported
    plan = checker_plan(data)
    r = await client.post(
        f"/teams/{plan['probe_team_id']}/submissions",
        json={"title": "dogfood-late-submission-probe", "summary": "probe"},
        headers=bearer(plan["participant_email"]),
    )
    # a real deadline rejection, not a 422 for a differently named field
    assert r.status_code == 403
    assert "deadline" in r.json()["detail"].lower()


def test_checker_identities_are_deterministic_and_distinct():
    data = copy.deepcopy(FIXTURES)
    plan = checker_plan(data)
    assert plan == checker_plan(copy.deepcopy(data))
    assert plan["judge_a_email"] != plan["judge_b_email"]
    assert plan["participant_email"] not in {j["email"] for j in data["judges"]}
    e = plan["judge_a_email"]
    assert create_checker_token(user_id_for_email(e), e) == create_checker_token(user_id_for_email(e), e)


def test_checker_plan_falls_back_when_fewer_than_two_judges():
    data = copy.deepcopy(FIXTURES)
    data["judges"] = data["judges"][:1]
    plan = checker_plan(data)
    assert plan["judge_a_email"] == "j1@example.org"
    assert plan["judge_b_email"] == "judge1@dogfoodhack.com"
