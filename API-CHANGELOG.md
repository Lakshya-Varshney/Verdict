# API changelog

Behaviour that API clients (the web UI, embeds, integrations) depend on, in the order the features were added. The full schema is always at `/openapi.json`; this file records the rules and gotchas the schema cannot express.


## T3 (public voting) contract

- `voting_mode`: `open | email | auth | quadratic` is now **persisted** on events (create/patch/response), plus
  `votes_per_voter` (default **1** = one person, one vote per event) and `vote_credits` (quadratic, default 25).
- `POST /submissions/{id}/vote` body: `{fingerprint?, email?, votes?}`. Response: `{ok, id, votes, votes_left, credits_left, mode}`.
  - `open`: identity = signed `voter_session` cookie (fingerprint hint seeds it for cookie-less clients) + per-IP cap.
  - `email`: `email` required (case-insensitive, one email = one voter). `auth`/`quadratic`: bearer token, else **401**.
  - `quadratic`: `votes` = total votes you want on *this* project (re-POST to change it); cost n² of `vote_credits`.
  - Errors: 400 window closed / duplicate / budget / credits, 401 needs login, 404 draft/unknown, **429 + `Retry-After`** rate limit.
  - Voting only works while event `status == voting` (and inside `voting_opens_at..voting_closes_at` when set).
- `GET /events/{id}/ballot[?email=]` -> `{open, closed_reason, requires_auth, requires_email, voter{my_votes,votes_left,credits_left,...}, items[]}`;
  `items` is **server-shuffled per voter/session**; no tallies. The vote page now uses it.
- `GET /submissions/{id}/votes/count`: while `voting`, non-organizers get `{hidden:true, count:null, vote_count:null}`
  (`vote_count` used to leak the number).
- `POST /submissions/{id}/comments`: 404 for drafts, 429 when rate limited, body trimmed and non-empty.
- `/admin/audit`: `event_id` filter now works for every event-scoped row; `?format=text` gives one readable line per entry.
  New actions: `vote.cast|update|rejected`, `comment.add`, `score.create|update`, `assignment.create`, `role.grant`,
  `event.create|update|status_change|delete`.
- Rate limits: `RATE_LIMIT_VOTES_PER_MINUTE` (10) and `RATE_LIMIT_COMMENTS_PER_MINUTE` (10) per IP+identity, plus a 6x per-IP ceiling.
  Redis-backed when `REDIS_URL` is set (compose does), in-memory otherwise. IP = first `X-Forwarded-For` hop (`TRUST_PROXY_HEADERS`).

## OpenAPI (T4 step 1)

- `/openapi.json` is now complete: every one of the 43 operations has a summary, tag, auth level, typed 2xx response,
  documented error statuses (`ErrorOut`) and described parameters; request bodies carry examples.
- **`operationId`s changed** to the handler names (`cast_vote`, `get_ballot`, ...; they used to be
  `vote_for_submission_submissions__submission_id__vote_post`). If you generate a client (`npm run gen:api`), regenerate it.
- Security scheme is now `BearerAuth` (was `HTTPBearer`). Optional-auth routes list both "no auth" and `BearerAuth`.
- `/docs` is Swagger UI served from vendored files (works offline, also at `/api/docs` via the web proxy). `/redoc` is removed.
- `python backend/scripts/check_openapi.py` validates the served spec **and** checks that every endpoint the frontend
  calls exists in it. It currently lists the still-pending T4 endpoints (webhooks, certificates, embed, export/import).

## Embed widget (T4)

- New public routes: `GET /embed/{event_id}/gallery` (JSON, CORS `*`), `GET /embed/{event_id}` (iframe HTML), `GET /embed.js`.
  `api.data.embed()` now calls the real endpoint (it used to return an empty list in live mode); the organizer *Data* page
  hands out the `<script>` snippet and previews the backend page.
- `/backend-docs` and `/backend-openapi.json` are now **redirects** to `/api/docs` and `/api/openapi.json` (the vendored
  Swagger UI uses relative asset URLs, so an in-place rewrite would 404 its assets).

## Export / import (T4)

- New `POST /events/{id}/export` (returns the dump) and `POST /events/{id}/import?dry_run=` (returns
  `{dry_run, checksum_verified, imported, created, updated, warnings}`). `api.data.export/import` are now live (they were 501).
  The Data page has a "Validate only (dry run)" toggle and shows warnings; choosing the same file twice now works (input reset).
- Errors: `422` with a `detail` string listing every problem, `409` id conflict, `413` too large.
- Also fixed: normalization audit rows now carry `event_id` (they were invisible to the per-event audit filter) and a
  `normalization.run` summary row is written.

## Certificates (T4)

- `GET /events/{id}/certificates/{user_id}[?kind=&format=json|pdf|html]` is live (was 501): 403 until the event is closed/published, 404 if
  nothing earned. New optional fields on `Certificate`: `signature`, `key_id`, `algorithm`, `verify_url`. `verify_hash` is now the
  64-char sha256 of the signed payload (it used to be a short mock hash).
- New public routes: `GET /verify/{code}`, `POST /verify`, `GET /.well-known/dogfood-signing-key`. New web page `/verify/[code]`.
- The certificate page now downloads the signed PDF / verifiable HTML and links to the verify page; the decorative fake QR is gone
  (it looked scannable and was not).

## Webhooks (T4)

- Live endpoints (were 501): `GET /webhooks[?event_id=]`, `POST /webhooks/subscribe`, `DELETE /webhooks/{id}`; new `GET /webhooks/event-types`,
  `GET /webhooks/{id}/deliveries`, `POST /webhooks/{id}/ping`. Subscribe accepts an optional `event_id` (the Webhooks page now scopes to the
  current event) and returns the signing `secret` **once**; the page shows it in a copy-once panel, plus a per-hook delivery log and "Send test".
- Errors: 422 (bad URL / unknown type / refused target), 409 (per-organizer limit), 404 for someone else's webhook.
- Event catalog now also has `comment.added` and `certificate.issued`.
