# VERDICT Architecture

How the platform is put together, why, and how to operate it. Companion documents: `README.md` (run it), `DATA-MODEL.md` (tables,
formats), `JUDGING.md` (scoring math, voting rules), `THREAT-MODEL.md` (security analysis).

## 1. Overview

```
                       ┌────────────────────── docker compose ──────────────────────┐
 Browser ──/api/*──▶   │  web  Next.js :3000 ──rewrite──▶ api  FastAPI :8000 ──┬──▶ db     PostgreSQL 15
 (or any HTTP client)  │  (UI + /api proxy)                (REST + OpenAPI)     ├──▶ redis  rate-limit counters
                       │                                   worker loop (same    └──▶ webhook receivers  (outbound)
 DOGFOOD checker ──────┼── direct HTTP ──────────────────▶ process: webhooks)
 (run.py)              └────────────────────────────────────────────────────────────┘
 Third-party sites ── <script src=".../embed.js"> ─▶ /embed*, /verify*   (public, read-only)
```

`docker compose up` starts four services (`db`, `redis`, `api`, `web`). The API entrypoint runs, in order: **Alembic migrations → demo seed →
`fixtures.json` import → checker-identity printout → uvicorn**. There is no manual step. The **runtime makes no third-party network calls**: fonts are
bundled into the app (`@fontsource`), Swagger UI is vendored, no CDN or telemetry (verified by loading 28 pages in a real browser with every non-local request logged: zero).
Building the images needs the network once (pip/npm); running them does not.

A `test` compose profile adds an isolated throwaway Postgres (`test-db`, on tmpfs, sharing nothing with the dev database) and a `pytest` service, so
tests can never touch dev data.

## 2. Design principles

1. **The API is the product.** Every UI action is an API call; the OpenAPI document is generated from the running code and *enforced* (a test fails if a
   route is undocumented or a response has a field the schema omits; a script checks every endpoint the frontend calls exists).
2. **Security decisions live in one place each**: roles in `app/api/deps.py`, input limits in `app/schemas/limits.py`, request hostility in
   `app/middleware.py`, outbound safety in `app/services/webhook_service.py`, signing in `app/services/signing.py`.
3. **Deadlines, windows and visibility are enforced server-side**, never by the UI.
4. **Judgment data is append-only and audited**: scores, votes and audit rows are never deleted by the application; every write is logged in the
   same transaction.
5. **Correctness is measured on the official data**, not a toy: the 40-project `fixtures.json`, with results cross-checked by independent
   recomputation.
6. **Nothing is trusted from storage that can be recomputed**: normalized results are always derived from raw scores.

## 3. Backend (FastAPI)

FastAPI gives the OpenAPI contract for free from route signatures and Pydantic models; SQLAlchemy 2.0 (async, asyncpg) + Alembic give typed models
and real migrations. One process, one event loop; the webhook worker runs as a task in the same process (safe to scale out, see §5).

| Layer | Path | Responsibility |
|-------|------|----------------|
| Request guard | `app/middleware.py` | Pure-ASGI: NUL bytes (raw, JSON-escaped, `%00`) → 422; body caps (2 MB, 50 MB for imports) → 413; security headers on every response. (`app/main.py` adds the `/embed*` CORS-for-any-origin middleware and the docs page) |
| Routers | `app/api/*.py` | `auth`, `events`, `teams`, `submissions`, `judging`, `voting`, `admin`, `embed`, `dump`, `certificates`, `webhooks`: HTTP shapes and wiring only |
| Permissions | `app/api/deps.py` | **The one place roles are decided** (§4) |
| Schemas | `app/schemas/*.py` | Wire models; `limits.py` bounds every free-text field; `api.py` holds the typed *response* models that make the spec complete |
| Services | `app/services/*.py` | Domain logic: submissions/deadlines, teams, voting, audit, fixtures, export/import, certificates, signing, webhooks |
| Judging engine | `app/services/judging_engine.py` | Pure functions: assignment, weighted score, z-score normalization (see `JUDGING.md`) |
| Models | `app/models/*.py` | Persistence; **every relationship is `lazy="raise"`** (§8) |
| Utils | `app/utils/*.py` | JWT + bcrypt, sliding-window rate limiter (Redis or memory), voter fingerprints / signed session cookie |
| OpenAPI metadata | `app/openapi_meta.py` | One table documenting every operation (summary, auth level, error codes); tests fail if it drifts from the routes |

### Request lifecycle

```
request → RequestGuard (NUL, size, headers) → CORS → route
        → [rate limit: votes, comments, login failures, sign-up, verify]
        → authentication (JWT, `sub` → user row)
        → authorization (roles read from the DB for THIS event)
        → validation (Pydantic: types, bounds, http(s)-only links)
        → service (business rules: deadline, window, budget, dedup) — one DB transaction
        → audit row + webhook outbox row written in that same transaction
        → typed response model
```

## 4. Authentication and roles

Clients send `Authorization: Bearer <JWT>` (HS256, `sub` = user id, 24 h). Passwords are bcrypt-hashed (≥ 8 characters). Roles live in `event_roles` and are
**per event**; a user may hold several in one event (judge + participant). Identity comes from the token, **roles from the database on every request**
(no role claim is trusted).

`app/api/deps.py` exposes the enforcement points:

- `require_role([...])`: routes keyed by `event_id`;
- `require_submission_role([...])`: routes keyed by `submission_id`; checked against the event that **owns the submission**, so being an organizer/judge of
  event A grants nothing on event B;
- `require_role_global([...])`: routes with no event in the path (`/admin/audit`, team/submission creation, webhooks): any event role of that type;
- `hide_draft_event(...)`: draft events (and their tracks, rubric, gallery) are `404` to everyone but their organizers;
- a **site admin** = the `admin` role in any event, accepted everywhere; **only an admin can grant it** (an organizer minting admins would be a
  privilege escalation, found and fixed, see `THREAT-MODEL.md`).

Deadlines and windows are enforced in the services: submissions after `submission_deadline` → `403`; scores outside the judging window or after
publication → `403`; votes only while `status == voting` and inside the dates.

### Checker identities and long-lived tokens

The DOGFOOD checker (`run.py`) never logs in: it attaches a raw header value per role from `.dogfood.toml`. So besides the normal demo accounts, boot
creates four **checker identities** (`organizer`, `judge_a`, `judge_b`, `participant`) and mints a token for each with `create_checker_token`: the same JWT
scheme with a fixed 2100-01-01 expiry and no `iat`, so a token is byte-identical on every boot and clone (user ids are deterministic uuid5 values). The
seed prints the header values between `=== DOGFOOD CHECKER IDENTITIES ===` markers (`docker compose logs api`); `.dogfood.toml` holds the same values.
`judge_a`/`judge_b` are two different real judges from the fixtures, and `participant` is a dedicated user with no judge role. **These tokens are only as
secret as `JWT_SECRET_KEY`**, which is published in this repository for local grading: the API logs a warning at boot while it is unchanged; set your own
before exposing anything.

## 5. Key flows

### Public voting (`voting_service.py`, `api/voting.py`)
`POST /submissions/{id}/vote` → resolve the voter identity for the event's `voting_mode` (signed session cookie / canonical email / user id) → rate limit
(per IP+identity, plus a per-IP ceiling) → **lock the event row** → check window, budget or credits (approval: `votes_per_voter`; quadratic: Σ n² ≤ credits)
→ insert or re-allocate (DB unique `(submission, voter)` is the backstop) → audit row + webhook outbox row → response with the remaining budget. Tallies are
never in any public payload while the event is in `voting`. `GET /events/{id}/ballot` returns the projects in a per-voter seeded shuffle.

### Webhooks: transactional outbox (`webhook_service.py`)
Emitting is an `INSERT` into `webhook_deliveries` inside the same transaction as the action (a rolled-back action never fires; a crash never loses one). A worker
loop (a task in the API process) **leases** due rows (`FOR UPDATE SKIP LOCKED`, lease = `next_attempt_at`), re-validates the target (SSRF guard), POSTs the exact
stored body with an HMAC-SHA256 signature over `timestamp.body`, and records the result: success, retry with backoff (5 s, 30 s, 2 min, 10 min, 1 h), or dead
after 6 attempts. Ten dead deliveries in a row, or a `410`, switch the endpoint off. Several API processes can run: leases prevent double sends.

### Certificates (`certificate_service.py`, `signing.py`)
Entitlements are computed from live data (team + submitted project; judge role + scores; top-3 normalized rank) once the event is closed, then **frozen and signed**:
Ed25519 over the canonical JSON payload (no emails, no scores; a judge record holds counts and a period). Verification is public and needs no secret:
`GET /verify/{code}` (re-checks the stored record), `POST /verify` (checks a document you were handed), the published key at
`/.well-known/dogfood-signing-key`, and `backend/scripts/verify_certificate.py` (pure-Python RFC 8032, standard library only).

### Embed widget (`api/embed.py`)
Public and read-only: CORS-open JSON, a self-contained HTML page (escaped, CSP, frameable by design), and a one-line `<script>` that inserts an auto-resizing
iframe. It exposes only what the public gallery shows; never drafts, scores, tallies or `custom_answers`.

### Export / import (`event_dump.py`)
A versioned, checksummed JSON snapshot of a whole event; import is validated first (all problems reported), transactional, idempotent, additive, matches users
by email, never mints admins, and refuses ids that belong to another event. Details: `DATA-MODEL.md`.

### Fixture import (`fixture_import.py`)
At boot the official `fixtures.json` becomes real rows with deterministic ids (`stable_ids.py`, uuid5), so `.dogfood.toml` can hard-code routes; duplicate projects
merge on team+title, last write wins. Details and the real awkward cases: `DATA-MODEL.md`.

## 6. Configuration

Environment variables (`backend/app/config.py`; in Compose they are set in `docker-compose.yml`):

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | local Postgres | asyncpg URL |
| `REDIS_URL` | unset | shared rate limits; unset = in-memory per process |
| `JWT_SECRET_KEY` | published demo value | **change in production** (warned at boot); also the fallback certificate-key secret |
| `CERT_SIGNING_KEY` | unset (uses the JWT secret) | Ed25519 signing key seed; changing it changes the key id |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | 1440 | token lifetime |
| `CORS_ORIGINS` | `localhost:3000,5173` | credentialed CORS origins |
| `SEED_ON_STARTUP`, `FIXTURES_PATH` | true, `/data/fixtures.json` | demo seed + fixture import at boot |
| `RATE_LIMIT_ENABLED`, `RATE_LIMIT_VOTES_PER_MINUTE`, `RATE_LIMIT_COMMENTS_PER_MINUTE` | true, 10, 10 | vote/comment throttles (plus a per-IP ceiling of 6×) |
| `VOTES_PER_IP_MULTIPLIER` | 10 | max votes from one network per event = multiplier × budget |
| `LOGIN_MAX_FAILURES`, `LOGIN_MAX_FAILURES_PER_IP`, `RATE_LIMIT_SIGNUPS_PER_MINUTE` | 10, 50, 100 | brute-force / flood protection (failures only) |
| `TRUST_PROXY_HEADERS` | true | take the client IP from `X-Forwarded-For` (behind the web proxy); **set false if `:8000` is exposed** |
| `WEBHOOK_WORKER_ENABLED`, `WEBHOOK_TIMEOUT_SECONDS`, `WEBHOOK_MAX_ATTEMPTS`, `WEBHOOK_BACKOFF_SECONDS`, `WEBHOOK_DISABLE_AFTER_DEAD`, `WEBHOOK_MAX_PER_OWNER` | true, 5, 6, `5,30,120,600,3600`, 10, 20 | delivery engine |
| `WEBHOOK_ALLOW_PRIVATE_TARGETS` | false (**true in the demo compose**) | allow loopback/private receivers; link-local/metadata are always refused |
| `PUBLIC_WEB_URL`, `PUBLIC_API_URL` | localhost | links inside embed pages, snippets and certificate verify URLs |

Frontend (build-time, baked into the image): `NEXT_PUBLIC_MOCK`, `NEXT_PUBLIC_API_URL=/api`, `API_INTERNAL_URL=http://api:8000`.

## 7. Operations

| Concern | How |
|---------|-----|
| **Start / stop** | `docker compose up -d --build` / `down` (`down -v` also wipes the database volume) |
| **Health** | `GET /health`; containers have health checks; `docker compose ps` |
| **Logs** | `docker compose logs -f api` (structured uvicorn logs; the audit log is in the database, `GET /admin/audit?format=text`) |
| **Migrations** | Alembic, run automatically at boot; `alembic check` verifies the committed migrations match the models (run by the test pipeline `backend/scripts/test-pipeline.sh`) |
| **Backups** | PostgreSQL dumps **and** portable per-event JSON exports (`POST /events/{id}/export`) that restore into a fresh instance |
| **Upgrades** | Rebuild the images; migrations apply at boot; the schema only ever adds/changes via migration files |
| **Scaling** | The API is stateless except the rate-limit fallback (use Redis); the webhook worker is lease-based, so extra API replicas are safe |
| **Secrets** | `JWT_SECRET_KEY`, `CERT_SIGNING_KEY`: set them; rotating invalidates all tokens (and changes the certificate key id) |
| **Offline** | Runtime needs no internet; `/docs` is self-hosted; see §1 |
| **Time** | Deadlines, windows, token expiry and the webhook replay window use the server clock |

## 8. Performance: no eager relationship loading

Every ORM relationship is `lazy="raise"`. It used to be `lazy="selectin"`, which made loading one `User` or `Event` pull in the whole transitive object
graph (scores, votes, comments, teams, ...): harmless with 10 projects, but with the official 40-project data set `/events/{id}/roles` took 18 s and the
public gallery 13 s (past the checker's 10 s timeout). Code now selects the columns and rows it needs explicitly (the gallery uses one `COUNT` plus batched
name lookups), and `raise` turns any accidental implicit load into a loud error in tests instead of a silent N+1. Measured against the real data, every
read endpoint answers in under 100 ms (worst: `POST /judging/normalize`, ~90 ms; guarded by `test_real_scale_endpoints_stay_fast`).

## 9. Testing strategy

| Layer | What | Where |
|-------|------|-------|
| Unit / pure | judging engine, normalization proof, signatures, email canonicalization, limiter | `tests/test_normalization.py`, `test_judging_assignment.py`, `test_certificates.py`, `test_hardening.py` |
| API + real Postgres | roles matrix, deadlines, voting abuse, exports, webhooks, embeds, the OpenAPI contract | `docker compose --profile test run --rm pytest` (262 tests, isolated `test-db`) |
| Real data | the official 40-project file: counts, awkward cases, results vs independent recomputation, scale | `tests/test_real_fixtures.py` |
| Live stack | full lifecycle, T3 through the real proxy, webhooks against a real receiver | `backend/scripts/live_*.py`, `backend/tests/test_e2e_api.py` |
| Real browser | every page × 5 roles, 13 interactive flows, cross-origin embed | `frontend/e2e-ui*.py`, `frontend/e2e-embed.py` |
| Adversarial | 96 hostile-input probes + 16 authorization exploits | `backend/scripts/probe_abuse.py` |
| Contract | spec is valid, complete, and every UI call exists in it | `tests/test_openapi.py`, `backend/scripts/check_openapi.py` |
| External | the official acceptance checker | `python run.py .dogfood.toml` |

## 10. Decisions and trade-offs

| Decision | Why | Cost |
|----------|-----|------|
| **Ed25519 (not HMAC) for certificates** | Anyone can verify offline with just a public key; no shared secret with verifiers | key custody is a server secret; no revocation list |
| **Transactional outbox for webhooks** | Cannot lose or invent events; no broker to run offline | polling worker (1 s) instead of push |
| **Per-judge z-score normalization** (not min-max or rank averaging) | Corrects both leniency and spread; well-defined with uneven review counts; explainable | needs ≥ 2 reviews per judge, so a documented pooled fallback exists |
| **Roles per event, read from the DB each request** | No stale or forged role claims; cross-event isolation is structural | one small query per request |
| **Deterministic ids for fixtures** | `.dogfood.toml` can hard-code routes and tokens reproducibly | ids are derived, not random, for imported data |
| **`lazy="raise"` everywhere** | Predictable queries; found and prevented a 13 s gallery | every query must be explicit |
| **In-process webhook worker** | Zero extra services for `docker compose up` | delivery pauses if the API is down (rows wait; nothing is lost) |
| **Server-issued signed cookie for `open` voting** | No login needed, tamper-evident | cookie clearing is bounded only by per-IP caps (see threat model R1) |
| **Public gallery shows `custom_answers`** | The UI presents them as part of the project | organizers must not ask for private data |
| **Vendored Swagger UI, `/redoc` removed** | Docs must work with the network off | one static bundle in the repo (Apache-2.0, license included) |
| **Hash-chained audit log, one global advisory lock per write** | A linear, independently-verifiable chain needs writes serialized (else two concurrent transactions could read the same tip hash and fork it) | every action that logs anything takes one Postgres advisory lock; a real cost under heavy concurrent write load, accepted for a verifiable history instead of a merely conventional one |

## 11. Limitations (honest list)

Pairwise/Bradley-Terry judging is not built (the UI's "duel" page returns `501`); email voting is not verified; rate limiting is per IP and identity, not a
global WAF; certificate PDFs fall back to `?` for scripts the vendored Unicode font doesn't cover (CJK; Latin/Cyrillic/Greek/Vietnamese render correctly) and
have no revocation; the audit log's own integrity is hash-chained and independently verifiable (`GET /admin/audit/verify`, `verify_audit_chain.py`), but that
does not extend to data an operator edits directly without going through the application; the app has no CSP of its own. The security-relevant ones are
analysed in `THREAT-MODEL.md` §6 with mitigations.

## 12. Frontend

Next.js 16 / React 19 App Router. The browser only talks to `:3000`; Next rewrites `/api/*` to FastAPI (`next.config.mjs`), so there is no CORS in Compose.
The app has security headers (`nosniff`, referrer policy, `frame-ancestors 'self'` except for `/embed/*`), renders user text only through React (escaped), and
links only `http(s)` URLs (`safeHref`). A built-in mock API exists for demos (`NEXT_PUBLIC_MOCK=true`). See `frontend/README.md` and `frontend/docs/API-GAPS.md`.
