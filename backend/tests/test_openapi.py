"""The OpenAPI document is a deliverable: it must be valid, complete and match real responses."""

import pytest
from openapi_spec_validator import validate

from app.main import app
from app.models.event import EventStatus
from app.openapi_meta import OPS
from app.schemas import api as S
from tests.conftest import get_auth_header
from tests.test_role_isolation import _bearer, _real_fixtures  # noqa: F401
from tests.test_real_fixtures import real  # noqa: F401  (fixture)

SPEC = app.openapi()
OPERATIONS = [(m.upper(), p, o) for p, ms in SPEC["paths"].items() for m, o in ms.items()]


def test_spec_is_valid_openapi_3():
    validate(SPEC)
    assert SPEC["openapi"].startswith("3.")


def test_every_route_is_documented_and_every_entry_is_real():
    routes = {(m, p) for m, p, _ in OPERATIONS}
    assert routes == set(OPS), (sorted(routes - set(OPS)), sorted(set(OPS) - routes))


def test_operation_ids_are_unique_and_readable():
    ids = [o["operationId"] for *_, o in OPERATIONS]
    assert len(ids) == len(set(ids))
    assert not any("_post" in i or "_get" in i for i in ids)


def test_info_servers_security_and_tags():
    info = SPEC["info"]
    assert info["license"]["name"] == "MIT" and info["contact"] and "Authentication" in info["description"]
    assert SPEC["servers"] and "BearerAuth" in SPEC["components"]["securitySchemes"]
    declared = {t["name"] for t in SPEC["tags"]}
    assert all(set(o["tags"]) <= declared for *_, o in OPERATIONS)


@pytest.mark.parametrize("method,path,op", OPERATIONS, ids=[f"{m} {p}" for m, p, _ in OPERATIONS])
def test_operation_is_fully_documented(method, path, op):
    assert op["summary"] and op["description"]
    meta = OPS[(method, path)]
    # documented errors are exactly the declared ones (+422 when there is input to validate)
    for code in meta["errors"]:
        assert str(code) in op["responses"], f"{code} missing"
        assert "ErrorOut" in str(op["responses"][str(code)])
    if meta["auth"] == "role":
        assert {401, 403} <= set(meta["errors"]), "role-protected operations must document 401 and 403"
        assert op["security"] == [{"BearerAuth": []}]
    if meta["auth"] == "none":
        assert "security" not in op
    if meta["auth"] == "optional":
        assert {} in op["security"]
    for prm in op.get("parameters", []):
        assert prm.get("description"), f"parameter {prm['name']} undocumented"
    ok = next(c for c in op["responses"] if c.startswith("2"))
    for ctype, body in op["responses"][ok].get("content", {}).items():
        if ctype == "application/json":
            sch = body["schema"]
            item = sch.get("items", sch) if sch.get("type") == "array" else sch
            assert "$ref" in item or item.get("properties"), f"untyped JSON response: {sch}"


def _body_ref(schema):
    if "$ref" in schema:
        return schema["$ref"].split("/")[-1]
    for alt in schema.get("anyOf", []):
        if "$ref" in alt:
            return alt["$ref"].split("/")[-1]
    return ""


def test_request_bodies_have_examples():
    for method, path, op in OPERATIONS:
        rb = op.get("requestBody")
        if not rb:
            continue
        ref = _body_ref(rb["content"]["application/json"]["schema"])
        assert ref and "example" in SPEC["components"]["schemas"][ref], f"{method} {path}: {ref or 'body'} has no example"


# ---------------------------------------------------------------- the spec matches reality

def _undeclared(model, obj, where):
    fields = set(model.model_fields)
    extra = set(obj) - fields
    assert not extra, f"{where}: response has fields missing from the documented schema {model.__name__}: {sorted(extra)}"


@pytest.mark.asyncio
async def test_documented_schemas_declare_every_returned_field(client, db_session, real):
    """Contract accuracy: real payloads (official fixtures + votes) have no undeclared top-level fields."""
    from app.models.event import Event
    from app.schemas.submission import SubmissionResponse  # noqa: F401

    data, summary = real
    eid = summary["event_id"]
    org = _bearer("organizer@dogfoodhack.com")
    judge = _bearer("wei.lindqvist@example.org")
    ev = await db_session.get(Event, eid)
    ev.status = EventStatus.VOTING
    ev.voting_mode = "open"
    ev.voting_opens_at = ev.voting_closes_at = None  # the fixture's 2026-03 voting window is long over
    await db_session.commit()

    subs = (await client.get(f"/events/{eid}/submissions", params={"limit": 3})).json()
    sid = subs[0]["id"]
    _undeclared(S.SubmissionView, subs[0], "gallery item")
    _undeclared(S.SubmissionView, (await client.get(f"/submissions/{sid}", headers=org)).json(), "submission")
    _undeclared(S.EventOut, (await client.get(f"/events/{eid}")).json(), "event")
    _undeclared(S.EventOut, (await client.get("/events")).json()[0], "event list item")
    _undeclared(S.CriterionOut, (await client.get(f"/events/{eid}/rubric/criteria")).json()[0], "criterion")
    _undeclared(S.ProgressOut, (await client.get(f"/events/{eid}/judging/progress", headers=org)).json(), "progress")
    aset = (await client.get(f"/events/{eid}/judging/assignments", headers=org)).json()
    _undeclared(S.AssignmentSetOut, aset, "assignment set")
    _undeclared(S.AssignmentRow, aset["assignments"][0], "assignment row")
    mine = (await client.get(f"/events/{eid}/judging/assignments/mine", headers=judge)).json()
    if mine:
        _undeclared(S.AssignmentRow, mine[0], "my assignment")
    res = (await client.get(f"/events/{eid}/judging/results", headers=org)).json()
    _undeclared(S.ResultsOut, res, "results")
    _undeclared(S.ResultRowOut, res["rows"][0], "result row")
    _undeclared(S.JudgeBiasOut, res["judges"][0], "judge bias")
    allscores = (await client.get(f"/submissions/{sid}/scores", headers=org)).json()
    _undeclared(S.JudgeScoresOut, allscores[0], "scores")
    _undeclared(S.ScoreItemOut, allscores[0]["scores"][0], "score item")
    norm = await client.post(f"/events/{eid}/judging/normalize", headers=org)
    _undeclared(S.NormalizeOut, norm.json(), "normalize")

    ballot = (await client.get(f"/events/{eid}/ballot")).json()
    _undeclared(S.BallotOut, ballot, "ballot")
    _undeclared(S.BallotItemOut, ballot["items"][0], "ballot item")
    vote = await client.post(f"/submissions/{sid}/vote")
    assert vote.status_code == 201
    _undeclared(S.VoteOut, vote.json(), "vote")
    _undeclared(S.VoteCountOut, (await client.get(f"/submissions/{sid}/votes/count")).json(), "count")
    _undeclared(S.VoterStateOut, (await client.get(f"/events/{eid}/ballot")).json()["voter"], "voter state")
    c = await client.post(f"/submissions/{sid}/comments", json={"body": "hi"})
    _undeclared(S.CommentOut, c.json(), "comment")
    _undeclared(S.CommentOut, (await client.get(f"/submissions/{sid}/comments")).json()[0], "comment list item")
    audit = (await client.get("/admin/audit", params={"event_id": eid}, headers=org)).json()
    _undeclared(S.AuditPageOut, audit, "audit page")
    _undeclared(S.AuditEntryOut, audit["items"][0], "audit entry")


@pytest.mark.asyncio
async def test_team_and_criteria_responses_match_schema(client, test_team, test_user, test_organizer, test_event):
    h = get_auth_header(test_user)
    mine = (await client.get(f"/events/{test_event.id}/teams/mine", headers=h)).json()
    _undeclared(S.TeamDetailOut, mine[0], "team")
    _undeclared(S.TeamMemberOut, mine[0]["members"][0], "team member")
    made = await client.post(f"/events/{test_event.id}/rubric/criteria", json={"name": "Q"}, headers=get_auth_header(test_organizer))
    assert made.status_code == 201
    _undeclared(S.CriterionOut, made.json(), "created criterion")


@pytest.mark.asyncio
async def test_docs_page_is_self_hosted_so_it_works_offline(client):
    """`docker compose up` must give a usable /docs with the network off: no CDN references."""
    import re

    page = await client.get("/docs")
    assert page.status_code == 200
    assert not re.findall(r'(?:src|href)="https?://', page.text), "docs page references an external asset"
    for asset in ("swagger-ui-bundle.js", "swagger-ui.css", "favicon.png"):
        r = await client.get(f"/static/swagger/{asset}")
        assert r.status_code == 200 and len(r.content) > 1000, asset
    assert (await client.get("/openapi.json")).status_code == 200
    assert (await client.get("/redoc")).status_code == 404  # needs a CDN + web fonts; deliberately not shipped
