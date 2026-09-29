"""OpenAPI contract metadata: the single place that documents every operation.

`build_openapi(app)` takes FastAPI's generated schema and completes it with what code introspection
cannot know: human summaries, the auth level of each operation, the exact error statuses it can
return, parameter descriptions, request/response examples and the API-wide guide.

`tests/test_openapi.py` fails if a route exists without an entry in ``OPS`` (or vice-versa), so the
spec cannot silently rot when endpoints are added.
"""

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from app.config import settings
from app.schemas.api import ErrorOut

API_DESCRIPTION = """
REST API for the **DOGFOOD** hackathon submission and judging platform. Every action available in the
web UI is available here: the UI is a client of this same API.

## Authentication
`POST /auth/login` (or `/auth/signup`) returns `{"token": "<JWT>"}`. Send it as
`Authorization: Bearer <token>`. Click **Authorize** above to use *Try it out*.
Public routes (gallery, event list, results-after-close counts, open/email voting, comments) need no token.

## Roles
Roles are **scoped per event**: `participant`, `judge`, `organizer`, `admin`. A user can hold several in one
event. `401` = missing/invalid token, `403` = authenticated but not allowed for this event.

## Errors
Every non-2xx response has the body `{"detail": <string | list>}` (`ErrorOut`). `422` carries FastAPI's
validation error list. Deadline / window violations use `403` (submission deadline) or `400` (voting window).

## Judging integrity
Judges only ever see their own scores (`/scores/mine`); `/scores` (all judges) and results are organizer-only.
Ranked results use **per-judge z-score normalization** (`method: per_judge_z_score`); see `JUDGING.md`.
Partial reviews count, a judge with zero variance falls back to the pooled mean/sd and is flagged.

## Public voting
Event `voting_mode` = `open` (signed session cookie), `email`, `auth` or `quadratic` (n votes cost n² credits).
Voting is only accepted while the event status is `voting`. Tallies are hidden from everyone but organizers
during that window. Vote and comment endpoints are rate limited (`429` + `Retry-After`).
Get a per-voter randomized ballot from `GET /events/{event_id}/ballot`.

## Audit
Every score, vote, role grant, assignment and event status change is written to an append-only log,
readable at `GET /admin/audit` (JSON, or `?format=text` for a human-readable listing).
""".strip()

TAGS = [
    {"name": "system", "description": "Liveness."},
    {"name": "auth", "description": "Sign up, sign in, current user."},
    {"name": "events", "description": "Events, tracks and per-event roles."},
    {"name": "teams", "description": "Team formation and membership."},
    {"name": "submissions", "description": "Project submissions and the public gallery (deadline enforced server-side)."},
    {"name": "judging", "description": "Rubric, judge assignment, scoring, normalization, results and CSV export."},
    {"name": "voting", "description": "Public voting, ballots and comments (rate limited, deduplicated, tallies hidden while voting)."},
    {"name": "admin", "description": "Append-only audit log."},
    {"name": "data", "description": "Bulk portability: full-event JSON export and restore."},
    {"name": "certificates", "description": "Signed certificates and judge participation records (Ed25519), with public verification."},
    {"name": "webhooks", "description": "Outbound webhooks: signed, retried, at-least-once event notifications for organizers."},
    {"name": "embed", "description": "Embeddable gallery widget: CORS-open JSON, iframe page, one-line script. Public and read-only."},
]

# Auth levels: none = public, optional = works anonymously, personalised when a token is sent,
#              user = any signed-in user, role = signed in AND an event/global role (403 otherwise)
OPS: dict[tuple[str, str], dict[str, Any]] = {
    ("GET", "/health"): dict(summary="Liveness probe", auth="none", errors=[]),
    ("POST", "/auth/signup"): dict(summary="Create an account", auth="none", errors=[400], note="400: email already registered."),
    ("POST", "/auth/login"): dict(summary="Sign in and get a token", auth="none", errors=[401]),
    ("POST", "/auth/logout"): dict(summary="Sign out", auth="user", errors=[401], note="Tokens are stateless; the client should discard it."),
    ("GET", "/auth/me"): dict(summary="Current user and event roles", auth="user", errors=[401]),
    ("POST", "/events"): dict(summary="Create an event", auth="role", errors=[400, 401, 403], note="Organizer/admin only. 400: slug already used."),
    ("GET", "/events"): dict(summary="List events", auth="optional", errors=[], note="Drafts are hidden except from their organizers."),
    ("GET", "/events/{event_id}"): dict(summary="Get an event", auth="optional", errors=[404]),
    ("PATCH", "/events/{event_id}"): dict(summary="Update an event / change its status", auth="role", errors=[401, 403, 404],
                                          note="Organizer/admin. Status changes and config edits are audit-logged. `voting_mode` must be open|email|auth|quadratic (422)."),
    ("DELETE", "/events/{event_id}"): dict(summary="Delete an event and everything under it", auth="role", errors=[401, 403, 404], note="Event organizer or admin."),
    ("POST", "/events/{event_id}/tracks"): dict(summary="Add a track", auth="role", errors=[401, 403], note="Organizer/admin."),
    ("GET", "/events/{event_id}/tracks"): dict(summary="List tracks", auth="none", errors=[]),
    ("POST", "/events/{event_id}/roles"): dict(summary="Grant a role in this event", auth="role", errors=[400, 401, 403, 404],
                                               note="Organizer/admin. Identify the user by `user_id` or `email`. 404: no such user. 400: already has that role. Audit-logged."),
    ("GET", "/events/{event_id}/roles"): dict(summary="List role assignments", auth="role", errors=[401, 403], note="Organizer/admin."),
    ("POST", "/events/{event_id}/teams"): dict(summary="Create a team (caller becomes leader)", auth="role", errors=[400, 401, 403],
                                               note="Participant. 400: formation window closed or you are already in a team for this event."),
    ("POST", "/teams/{team_id}/join"): dict(summary="Join a team with its invite code", auth="role", errors=[400, 401, 403],
                                            note="400: wrong code, window closed, already in a team."),
    ("GET", "/teams/{team_id}"): dict(summary="Team details with members", auth="user", errors=[401, 403, 404], note="Team members only (403 otherwise)."),
    ("GET", "/events/{event_id}/teams/mine"): dict(summary="Teams the caller belongs to in this event", auth="user", errors=[401]),
    ("DELETE", "/teams/{team_id}/members/{user_id}"): dict(summary="Remove a team member", auth="user", errors=[400, 401, 403, 404],
                                                            note="Leader, or the member themselves. 403 for anyone else; the leader cannot be removed (400)."),
    ("POST", "/teams/{team_id}/submissions"): dict(summary="Create a submission for a team", auth="role", errors=[400, 401, 403, 404],
                                                   note="Team leader only. **403 after the submission deadline** (checked server-side). Accepts `title`/`summary` as aliases of `name`/`tagline`."),
    ("GET", "/submissions/{submission_id}"): dict(summary="Get a submission", auth="optional", errors=[404], note="Drafts are visible to team members only (404 otherwise)."),
    ("PATCH", "/submissions/{submission_id}"): dict(summary="Edit a submission", auth="role", errors=[400, 401, 403, 404], note="Team leader; 403 after the deadline."),
    ("POST", "/submissions/{submission_id}/submit"): dict(summary="Publish a draft to the gallery", auth="role", errors=[400, 401, 403, 404], note="Team leader; 403 after the deadline."),
    ("GET", "/events/{event_id}/submissions"): dict(summary="Public gallery (submitted projects)", auth="none", errors=[],
                                                    note="Paginated (`page`, `limit` <= 200) and filterable. Drafts never appear."),
    ("POST", "/events/{event_id}/rubric/criteria"): dict(summary="Add a rubric criterion", auth="role", errors=[401, 403], note="Organizer/admin."),
    ("GET", "/events/{event_id}/rubric/criteria"): dict(summary="List rubric criteria", auth="none", errors=[]),
    ("DELETE", "/events/{event_id}/rubric/criteria/{criterion_id}"): dict(summary="Delete a rubric criterion", auth="role", errors=[401, 403, 404], note="Organizer/admin."),
    ("POST", "/events/{event_id}/judging/assign"): dict(summary="Assign judges to submissions", auth="role", errors=[400, 401, 403],
                                                        note="Organizer/admin. Balanced round-robin; a judge is never assigned their own team's project. 400: no judges or submissions. Each assignment is audit-logged."),
    ("GET", "/events/{event_id}/judging/assignments/mine"): dict(summary="My review queue", auth="role", errors=[401, 403], note="Judge."),
    ("GET", "/events/{event_id}/judging/assignments"): dict(summary="All assignments", auth="role", errors=[401, 403], note="Organizer/admin."),
    ("GET", "/events/{event_id}/judging/progress"): dict(summary="Judging progress per judge", auth="role", errors=[401, 403], note="Organizer/admin."),
    ("POST", "/submissions/{submission_id}/scores"): dict(summary="Submit or update scores", auth="role", errors=[400, 401, 403], note="Assigned judge only. Send one score (`criterion_id`, `value`) or a batch (`scores`). 400: value outside the criterion's scale, unknown criterion. Upserts; every write is audit-logged with old and new value."),
    ("GET", "/submissions/{submission_id}/scores"): dict(summary="All judges' scores for a submission", auth="role", errors=[401, 403], note="Organizer/admin of the submission's event only. Judges get **403** (they may only read their own scores)."),
    ("GET", "/submissions/{submission_id}/scores/mine"): dict(summary="My scores for a submission", auth="role", errors=[401, 403], note="Judge only; returns the caller's rows and nobody else's. Participants get 403."),
    ("POST", "/events/{event_id}/judging/normalize"): dict(summary="Recompute normalized scores", auth="role", errors=[401, 403], note="Organizer/admin. Zero-variance judges are audit-logged."),
    ("GET", "/events/{event_id}/judging/export.csv"): dict(summary="Export ranked results as CSV", auth="role", errors=[401, 403], note="Organizer/admin. One row per scored project, partial reviews included.", csv=True),
    ("GET", "/events/{event_id}/judging/results"): dict(summary="Ranked results (raw and normalized)", auth="role", errors=[401, 403], note="Organizer/admin at every stage; never visible to judges, participants or the public through this route."),
    ("POST", "/submissions/{submission_id}/vote"): dict(summary="Cast a public vote", auth="optional", errors=[400, 401, 404, 429],
                                                        note="Access depends on the event's `voting_mode` (401 if a token is required). 400: window closed, duplicate, budget/credits exhausted. 404: unknown or draft project. 429: rate limited (`Retry-After`)."),
    ("GET", "/submissions/{submission_id}/votes/count"): dict(summary="Vote tally", auth="optional", errors=[], note="While the event is in `voting`, non-organizers get `hidden: true` and null counts."),
    ("GET", "/events/{event_id}/ballot"): dict(summary="Randomized ballot and my remaining budget", auth="optional", errors=[404],
                                               note="Order is seeded by the voter (user id or signed session cookie): stable per voter, different across voters."),
    ("POST", "/submissions/{submission_id}/comments"): dict(summary="Comment on a project", auth="optional", errors=[404, 429], note="Anonymous allowed (`author_name`). 404 for drafts. Rate limited."),
    ("GET", "/submissions/{submission_id}/comments"): dict(summary="List comments", auth="none", errors=[]),
    ("POST", "/events/{event_id}/export"): dict(summary="Export the whole event as JSON", auth="role", errors=[401, 403, 404],
                                                note="Organizer/admin. Versioned (`dogfood-event-dump` v1) and checksummed. Contains users' names and emails; **never** password hashes, tokens or raw IPs. Audit-logged."),
    ("POST", "/events/{event_id}/import"): dict(summary="Restore an event from a JSON dump", auth="role", errors=[401, 403, 404, 409, 413],
                                                note="Organizer/admin. **Validated first, applied in one transaction, idempotent, never deletes.** Users are matched by email (unknown emails get an account with no usable password); rows are upserted by id/natural key. `?dry_run=true` validates and counts without writing. 422: invalid dump / checksum mismatch (all problems listed). 409: an id already belongs to a different event. Audit history is only restored into the event it came from and is tagged `imported`."),
    ("GET", "/events/{event_id}/certificates/{user_id}"): dict(summary="Get a signed certificate (JSON, PDF or verifiable HTML)", auth="role", errors=[401, 403, 404],
                                                                extra_media=["application/pdf", "text/html"],
                                                                note="Yourself, or an organizer/admin for anyone (403 otherwise). Issued on first request once the event is **closed** (403 before), then stable. Kinds: `participant`, `judge` (a participation record with review counts and period, **never the scores**), `winner` (top 3 by normalized rank). 404 if nothing earned. Signed with Ed25519; the signed `payload` is returned so it can be verified offline."),
    ("GET", "/verify/{code}"): dict(summary="Verify a certificate by its code", auth="none", errors=[404, 429],
                                    note="Public. Re-checks the stored document's hash and signature. `valid: false` means the record does not match its signature."),
    ("POST", "/verify"): dict(summary="Verify a certificate document you were handed", auth="none", errors=[429],
                              note="Public. Checks the Ed25519 signature over `payload` without consulting the database (`issued_by_this_server` says whether it is also on record)."),
    ("GET", "/.well-known/dogfood-signing-key"): dict(summary="Public signing key", auth="none", errors=[],
                                                      note="The Ed25519 public key for offline verification. Its `key_id` appears in every certificate."),
    ("GET", "/webhooks/event-types"): dict(summary="Webhook event catalog", auth="none", errors=[]),
    ("POST", "/webhooks/subscribe"): dict(summary="Register a webhook endpoint", auth="role", errors=[401, 403, 404, 409, 422],
                                          note="Organizer/admin. Returns the signing `secret` **once**. 422: bad URL, unknown event type, or a target that is refused (link-local/metadata always; private-network unless allowed). 409: per-organizer limit. Requests are signed `X-Dogfood-Signature: sha256=HMAC(secret, \"<X-Dogfood-Timestamp>.<body>\")`; delivery is at-least-once with exponential backoff (dedupe on `X-Dogfood-Delivery`)."),
    ("GET", "/webhooks"): dict(summary="List my webhooks", auth="role", errors=[401, 403], note="Your endpoints only. Secrets are never returned again."),
    ("DELETE", "/webhooks/{webhook_id}"): dict(summary="Delete a webhook", auth="role", errors=[401, 403, 404], note="Yours only (404 otherwise). Also removes its delivery log."),
    ("GET", "/webhooks/{webhook_id}/deliveries"): dict(summary="Delivery log of a webhook", auth="role", errors=[401, 403, 404], note="Newest first; shows status, attempts, HTTP status and last error."),
    ("POST", "/webhooks/{webhook_id}/ping"): dict(summary="Send a test delivery", auth="role", errors=[401, 403, 404], note="Queues a `webhook.ping`; check the delivery log for the result."),
    ("GET", "/embed/{event_id}/gallery"): dict(summary="Embeddable gallery (JSON)", auth="none", errors=[404],
                                              note="CORS-open (`Access-Control-Allow-Origin: *`), cacheable 30 s, read-only. Submitted projects only; no drafts, custom answers, scores or vote tallies. Also returns ready-made `iframe_url` and `snippet`."),
    ("GET", "/embed/{event_id}"): dict(summary="Embeddable gallery page (iframe)", auth="none", errors=[404], media="text/html",
                                       note="Self-contained HTML, safe to frame from any site (`frame-ancestors *`), no external assets. `theme=light|dark`, `limit`, `track_id`."),
    ("GET", "/embed.js"): dict(summary="One-line widget script", auth="none", errors=[], media="application/javascript",
                               note='Usage: `<script src="http://localhost:8000/embed.js" data-event="EVENT_ID" data-limit="12" data-theme="dark"></script>`. Inserts an auto-resizing iframe.'),
    ("GET", "/admin/audit"): dict(summary="Audit log", auth="role", errors=[401, 403],
                                  note="Organizer/admin. Append-only. Filter by `event_id`, `actor_id`, `action`; `format=text` returns one readable line per entry.", text=True),
    ("GET", "/admin/audit/verify"): dict(summary="Verify the audit log's hash chain", auth="role", errors=[401, 403],
                                  note="Organizer/admin (any organizer, not just admins: verifying doesn't expose another event's content). Recomputes every row's hash from its own stored fields; `{valid, checked, head_seq, head_hash}` or, on tampering, `{valid: false, broken: {seq, id, reason}}` naming only the first bad row, never its content."),
}

ERROR_TEXT = {
    400: "Bad request: a business rule failed (message in `detail`).",
    401: "Missing or invalid bearer token.",
    403: "Authenticated but not allowed (wrong role for this event, or a deadline has passed).",
    404: "Resource not found.",
    409: "Conflict with existing data (e.g. an id that belongs to a different event, or a per-user limit).",
    413: "Request body too large.",
    422: "Validation error (malformed body, query or path parameter).",
    429: "Rate limited; see the `Retry-After` header (seconds).",
}

PARAMS = {
    "event_id": "Event UUID.",
    "submission_id": "Submission (project) UUID.",
    "team_id": "Team UUID.",
    "user_id": "User UUID.",
    "criterion_id": "Rubric criterion UUID.",
    "page": "1-based page number.",
    "limit": "Page size.",
    "track_id": "Only projects in this track.",
    "tag": "Only projects with this tech tag.",
    "search": "Case-insensitive match on name or tagline.",
    "status": "Filter by event status (UI names: draft, open, judging, voting, published).",
    "actor_id": "Only entries performed by this user.",
    "action": "Exact action name, e.g. `vote.cast`.",
    "format": "`json` (default) or `text`.",
    "email": "Voter email (email-gated events).",
}

EXAMPLES: dict[str, Any] = {
    "LoginRequest": {"email": "organizer@dogfoodhack.com", "password": "organizer123"},
    "UserCreate": {"email": "ada@example.org", "name": "Ada Lovelace", "password": "correct-horse"},
    "EventCreate": {"name": "Dogfood 2027", "tagline": "Ship it", "voting_mode": "quadratic", "vote_credits": 25,
                    "submission_deadline": "2027-03-01T18:00:00Z"},
    "RubricCriterionCreate": {"name": "Innovation", "weight": 2.0, "scale_min": 1, "scale_max": 5},
    "JudgeAssignmentCreate": {"strategy": "round_robin", "reviews_per_submission": 3},
    "ScoreBatchCreate": {"scores": [{"criterion_id": "6f1c0c9e-1b0a-4d1e-9a52-0a3f4f7f3e10", "raw_value": 4, "comment": "Solid"}]},
    "SubmissionCreate": {"name": "Glass Signal", "tagline": "One line of what it does",
                         "repo_url": "https://example.org/repo", "tech_tags": ["fastapi", "postgres"]},
    "TeamJoin": {"invite_code": "a1b2c3d4e5f6"},
    "TeamCreate": {"name": "NorthKiln"},
    "TrackCreate": {"name": "Developer tools", "description": "Tools that make other developers faster"},
    "EventRoleCreate": {"email": "judge1@dogfoodhack.com", "role": "judge"},
    "EventUpdate": {"status": "voting", "voting_mode": "quadratic", "vote_credits": 30},
    "SubmissionUpdate": {"tagline": "Now with a live demo", "live_url": "https://demo.example.org"},
    "VoteCreate": {"email": "voter@example.org", "votes": 2},
    "CommentCreate": {"body": "Love the demo!", "author_name": "A visitor"},
    "EventDump": {"format": "dogfood-event-dump", "version": 1, "event": {"id": "0f9e...", "name": "Dogfood 2027", "status": "voting"},
                  "users": [{"id": "u1", "email": "ada@example.org", "name": "Ada"}], "roles": [{"user_id": "u1", "role": "organizer"}],
                  "tracks": [], "criteria": [], "teams": [], "submissions": [], "assignments": [], "scores": [], "votes": [], "comments": [], "audit": []},
    "VerifyRequest": {"payload": {"v": 1, "issuer": "DOGFOOD", "kind": "judge", "event": {"id": "e1", "name": "Dogfood 2027"},
                                  "recipient": {"id": "u1", "name": "Ada Lovelace"}, "detail": "Served on the judging panel and reviewed 5 projects",
                                  "issued_at": "2027-03-10T12:00:00Z"}, "signature": "base64url-ed25519-signature"},
    "WebhookCreate": {"url": "https://hooks.example.dev/dogfood", "event_types": ["submission.submitted", "results.published"], "event_id": None},
    "ErrorOut": {"detail": "Voting has not started yet"},
    "VoteOut": {"ok": True, "id": "5b0d...", "submission_id": "0f9e...", "votes": 1, "votes_left": 0, "credits_left": None, "mode": "open"},
    "VoteCountOut": {"submission_id": "0f9e...", "hidden": True, "count": None, "vote_count": None},
}

SECURITY = "BearerAuth"


def _error_response(code: int) -> dict:
    return {
        "description": ERROR_TEXT[code],
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ErrorOut"}}},
    }


def build_openapi(app: FastAPI) -> dict:
    if app.openapi_schema:
        return app.openapi_schema
    schema = get_openapi(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=API_DESCRIPTION,
        routes=app.routes,
        tags=TAGS,
    )
    schema["info"]["contact"] = {"name": "DOGFOOD team", "url": "https://dogfoodhack.com/"}
    schema["info"]["license"] = {"name": "MIT", "url": "https://opensource.org/licenses/MIT"}
    schema["servers"] = [{"url": "http://localhost:8000", "description": "docker compose (api)"},
                         {"url": "http://localhost:3000/api", "description": "docker compose (through the web proxy)"}]

    comps = schema.setdefault("components", {})
    schemas = comps.setdefault("schemas", {})
    schemas["ErrorOut"] = ErrorOut.model_json_schema()
    # the auto-generated scheme is called HTTPBearer with no docs; replace with a documented one
    comps["securitySchemes"] = {
        SECURITY: {"type": "http", "scheme": "bearer", "bearerFormat": "JWT",
                   "description": "Token from `POST /auth/login` or `/auth/signup`."}
    }
    for name in list(schemas):
        base = name.split("-")[0]  # FastAPI emits `Model-Input` / `Model-Output` for models used both ways
        if base in EXAMPLES:
            schemas[name]["example"] = EXAMPLES[base]

    for path, methods in schema["paths"].items():
        for method, op in methods.items():
            meta = OPS.get((method.upper(), path))
            if meta is None:
                continue
            op["summary"] = meta["summary"]
            note = meta.get("note")
            base = (op.get("description") or "").strip()
            perm = {"none": "**Public.**", "optional": "**Public; personalised when a token is sent.**",
                    "user": "**Requires a signed-in user.**", "role": "**Requires a token and the right role.**"}[meta["auth"]]
            op["description"] = "\n\n".join(x for x in (perm, note, base) if x)

            if meta["auth"] == "none":
                op.pop("security", None)
            elif meta["auth"] == "optional":
                op["security"] = [{}, {SECURITY: []}]
            else:
                op["security"] = [{SECURITY: []}]

            codes = sorted(set(meta["errors"]) | ({422} if op.get("parameters") or op.get("requestBody") else set()))
            for code in codes:
                op["responses"].setdefault(str(code), _error_response(code))
            if 422 in meta["errors"] and "422" in op["responses"]:
                # this route can also refuse input with a plain `{"detail": "<message>"}` (business rules), besides
                # FastAPI's list-style validation errors: document both shapes
                op["responses"]["422"] = {
                    "description": "Validation error (list `detail`) or input refused by a business rule (string `detail`)",
                    "content": {"application/json": {"schema": {"oneOf": [
                        {"$ref": "#/components/schemas/HTTPValidationError"},
                        {"$ref": "#/components/schemas/ErrorOut"}]}}},
                }
            if not op.get("tags"):
                op["tags"] = ["system"]

            if meta.get("media"):
                op["responses"]["200"] = {"description": meta["summary"],
                                          "content": {meta["media"]: {"schema": {"type": "string"}}}}
            for extra in meta.get("extra_media", []):
                media_schema = {"type": "string", "format": "binary"} if extra == "application/pdf" else {"type": "string"}
                op["responses"]["200"].setdefault("content", {})[extra] = {"schema": media_schema}
            if meta.get("csv"):
                op["responses"]["200"] = {"description": "CSV: `rank,submission,team,track,judges,raw_mean,norm_mean,norm_z`",
                                          "content": {"text/csv": {"schema": {"type": "string"}}}}
            if meta.get("text"):
                ok = op["responses"]["200"]["content"]["application/json"]
                op["responses"]["200"]["content"] = {**ok, "text/plain": {"schema": {"type": "string"}}}

            for prm in op.get("parameters", []):
                prm.setdefault("description", PARAMS.get(prm["name"], prm["name"].replace("_", " ").capitalize() + "."))
    app.openapi_schema = schema
    return schema
