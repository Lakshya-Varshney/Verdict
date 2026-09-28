"""Regression tests pinned to the OFFICIAL fixtures.json (40 projects, 30 judges)."""

import time

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.models.judging import Score
from app.models.submission import Submission
from app.services.fixture_import import checker_plan, import_fixtures, resolve_projects
from app.services.stable_ids import stable_id, user_id_for_email
from tests.test_role_isolation import _bearer, _real_fixtures


@pytest_asyncio.fixture
async def real(db_session):
    data = _real_fixtures()
    summary = await import_fixtures(db_session, data)
    assert summary is not None
    return data, summary


def test_real_file_has_the_documented_awkward_cases():
    data = _real_fixtures()
    assert len(data["judges"]) == 30 and len(data["teams"]) == 40 and len(data["projects"]) == 41
    projects, canon = resolve_projects(data)
    assert len(projects) == 40
    # the duplicate is caught by team + title, NOT by id
    assert canon["prj_41"] == "prj_07" and "prj_41" != "prj_07"


@pytest.mark.asyncio
async def test_real_import_counts(db_session, real):
    _, summary = real
    assert summary["projects"] == 40 and summary["judges"] == 30 and summary["teams"] == 40
    assert summary["scores"] == 369  # 126 rows x 3 criteria, minus 9 collapsed by the duplicate merge
    assert (await db_session.execute(select(func.count()).select_from(Submission))).scalar() == 40
    assert (await db_session.execute(select(func.count()).select_from(Score))).scalar() == 369


@pytest.mark.asyncio
async def test_real_results_include_every_project_and_flag_flat_and_single_review_judges(client, real):
    data, summary = real
    r = await client.get(f"/events/{summary['event_id']}/judging/results", headers=_bearer("organizer@dogfoodhack.com"))
    assert r.status_code == 200
    body = r.json()
    assert len(body["rows"]) == 40  # partial reviews / uneven counts never drop a project
    counts = {row["name"]: row["judge_count"] for row in body["rows"]}
    assert counts["Dry Harbour"] == 6 and min(counts.values()) == 2
    flat = {j["judge_name"] for j in body["judges"] if j["zero_variance"] and not j["single_review"]}
    single = {j["judge_name"] for j in body["judges"] if j["single_review"]}
    assert "Iva Petrova" in flat  # 4/4/4 on everything
    assert single == {"Tomas Varga", "Anya Sokolova"}
    assert all(abs(row["norm_z"]) < 3 for row in body["rows"])  # fallback keeps flat judges on the z scale


@pytest.mark.asyncio
async def test_real_scale_endpoints_stay_fast(client, real):
    """Eager-loading regression guard: 40 projects used to take 13 s on the gallery, 18 s on roles."""
    _, summary = real
    org = _bearer("organizer@dogfoodhack.com")
    for path, headers in ((f"/events/{summary['event_id']}/submissions?limit=200", {}),
                          (f"/events/{summary['event_id']}/roles", org),
                          (f"/events/{summary['event_id']}/judging/results", org),
                          ("/events", {})):
        t0 = time.time()
        assert (await client.get(path, headers=headers)).status_code == 200
        assert time.time() - t0 < 2.0, path


@pytest.mark.asyncio
async def test_real_checker_identities(client, real):
    data, summary = real
    plan = checker_plan(data)
    assert plan["judge_a_email"] != plan["judge_b_email"]
    judge_emails = {j["email"].lower() for j in data["judges"]}
    assert plan["judge_a_email"] in judge_emails and plan["judge_b_email"] in judge_emails
    assert plan["participant_email"] not in judge_emails
    member_emails = {m.lower() for t in data["teams"] for m in t["members"]}
    assert not (judge_emails & member_emails)  # no judge/participant ambiguity in the official file
    sid = plan["project_id"]
    assert (await client.get(f"/submissions/{sid}/scores", headers=_bearer(plan["judge_b_email"]))).status_code == 403
    mine = await client.get(f"/submissions/{sid}/scores/mine", headers=_bearer(plan["judge_a_email"]))
    assert mine.status_code == 200 and mine.json()["scores"]  # judge_a really has scores on their route's project
