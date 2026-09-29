# Verdict

A platform for running a hackathon end to end: events, teams, submissions with server-enforced deadlines, rubric judging with **per-judge z-score
normalization**, **public voting** (approval or quadratic) with abuse protection, an audit log, **certificates with signed judge participation records**,
**signed webhooks**, an **embeddable gallery**, and whole-event **JSON export/import**. Everything the UI does is in a complete, checked **OpenAPI** contract.
It comes up with one command, seeded with the official DOGFOOD data, and **needs no internet at runtime**.

| Layer | Stack |
|-------|-------|
| **API** | FastAPI · Python 3.11 · SQLAlchemy 2.0 (async) · Pydantic v2 · Alembic · JWT · Redis (rate limits) |
| **DB** | PostgreSQL 15 |
| **Frontend** | Next.js 16 · React 19 · TypeScript · Tailwind 4 · TanStack Query |
| **Infra** | Docker Compose (`api` · `web` · `db` · `redis`, plus `test-db` / `pytest` under the `test` profile) |

**Documents:** [ARCHITECTURE.md](ARCHITECTURE.md) (how it works, config, operations) · [DATA-MODEL.md](DATA-MODEL.md) (tables, fixtures, export format) ·
[JUDGING.md](JUDGING.md) (scoring math, normalization proof, voting rules) · [THREAT-MODEL.md](THREAT-MODEL.md) (security analysis and findings) ·
live API docs at `/docs`.

---

## What is built, by tier

| Tier | Delivered | Verified by |
|------|-----------|-------------|
| **T1 Core** | Accounts, per-event roles, events/tracks, teams (invite codes), submissions with server-side deadline (`403`), public gallery | official checker + `test_submissions.py`, `test_role_isolation.py`, `live_lifecycle.py` |
| **T2 Judging** | Balanced assignment (never your own team), weighted rubric, role isolation (judges see only their own scores), progress view, **per-judge z-score normalization** (zero-variance / single-review fallbacks), CSV export | official checker + `test_normalization.py`, `test_real_fixtures.py` (recomputed independently on the 40-project data) |
| **T3 Public** | Voting: open / email / signed-in / **quadratic**, one vote per person per event by default; comments; results hidden while voting (server-side); **randomized ballot order** per voter; rate limiting, duplicate detection, human-readable **audit log** (`/admin/audit`) | `test_voting_abuse.py`, `live_t3.py`, UI flows |
| **T4 Stretch** | Complete OpenAPI + self-hosted `/docs`; **signed webhooks** (outbox, retries, SSRF guard); **certificates + Ed25519-signed judge records** (PDF/HTML, public verification, offline verifier); **embeddable gallery** (script tag / iframe / CORS JSON); **JSON export/import** of a whole event | `test_openapi.py`, `test_webhooks.py`, `test_certificates.py`, `test_embed.py`, `test_dump.py`, `live_webhooks.py`, `e2e-embed.py` |
| Bonus | Normalization proof on real data (JUDGING.md), threat model (THREAT-MODEL.md), API-first (OpenAPI enforced by tests), **hash-chained audit log** (not just append-only by convention: `GET /admin/audit/verify` and the offline `verify_audit_chain.py` both detect a database operator editing history) | those documents + `probe_abuse.py`, `test_audit_chain.py` |

Not built: pairwise / Bradley-Terry judging (the UI's "duel" page degrades to a `501` message).

---

## Quick start

```bash
docker compose up -d --build        # first build needs the network; after that it runs fully offline
```

| Service | URL |
|---------|-----|
| Frontend | http://localhost:3000 |
| API (the portal `run.py` checks) | http://localhost:8000 |
| API docs (Swagger UI, self-hosted) | http://localhost:8000/docs (also http://localhost:3000/api/docs) · spec: `/openapi.json` |
| Health | http://localhost:8000/health |

The API entrypoint runs **Alembic migrations → demo seed → `fixtures.json` import → uvicorn** automatically; there are no manual steps.
Stop with `docker compose down` (`down -v` also wipes the database).

### Demo accounts

Seeded at boot. Passwords apply to the real backend (the frontend's mock mode uses `mira@demo.dev` etc., password `verdict`).

| Role | Email | Password |
|------|-------|----------|
| Admin | `admin@dogfoodhack.com` | `admin123` |
| Organizer | `organizer@dogfoodhack.com` | `organizer123` |
| Judge | `judge1@dogfoodhack.com` … `judge3@…` | `judge123` |
| Participant | `participant1@dogfoodhack.com` … `participant6@…` | `participant123` |

The official fixture event ("Sample Hack 2026": 40 projects, 30 judges, 126 reviews) is imported too; its judges/members are real users but have no passwords
(they exist for the checker and the results).

### A five-minute tour

1. Sign in as **organizer**, open the demo event → *Rubric*, *Assign*, *Settings* (voting mode, dates).
2. As a **participant**, join/create a team, fill *Submit* (deadline enforced by the API), publish.
3. As a **judge**, open *Judge*, score (the API rejects out-of-range values and scores outside the judging window).
4. As **organizer**: *Results* (raw vs normalized, judge bias chart, CSV), *Audit*, *Data* (export/import + embed snippet), *Webhooks* (register, send test).
5. Set the event to `voting`, open the ballot in two browsers (different order each), vote; the tally stays hidden until you publish.
6. Publish: participants and judges get **certificates**; anyone can check one at `/verify/<code>`.

---

## Grading / DOGFOOD checker

`run.py` (the official checker, byte-identical to https://dogfoodhack.com/spec/run.py) reads `.dogfood.toml` and makes seven plain HTTP calls; it never logs in.

```bash
docker compose up -d --build         # wait for `docker compose ps` to show api healthy
python3 run.py .dogfood.toml > acceptance-report.txt
```

| File | What it is |
|------|------------|
| `run.py` | The checker |
| `.dogfood.toml` | Base URL, claimed tiers, the four role headers and five routes. The `[auth]`/`[routes]` values are printed by the API at boot (`docker compose logs api`, between `=== DOGFOOD CHECKER IDENTITIES ===` markers) and are deterministic, so they match on every boot |
| `fixtures.json` | The **official** data file (https://dogfoodhack.com/spec/fixtures.json), imported at boot. Its awkward cases (a flat-scoring judge, single-review judges, a duplicate project detected by team+title, 2-6 reviews per project) and how each is handled are documented in `DATA-MODEL.md` |
| `acceptance-report.txt` | Output of `run.py`; regenerated, never edited |

**Current status:** all 7 checks pass: `claimed T1 T2 T3 T4, verified T1 T2`. The official `run.py` only implements the T1/T2 checks (the spec describes "seven checks"),
so it prints `note: claimed but not verified: T3 T4` by design; T3 and T4 are covered by this repository's own suites (below).

---

## API

The API is the product: the web UI is a client of it. **59 operations**, all documented with a summary, auth level, typed response, error statuses
(`{"detail": …}`) and described parameters; request bodies carry examples; `operationId`s are the handler names (client-generator friendly).

| Area | Endpoints (see `/docs` for all, with schemas) |
|------|------------------------------------------------|
| auth | `POST /auth/signup` · `/auth/login` · `/auth/logout`, `GET /auth/me` |
| events | CRUD `/events`, tracks, roles (`admin` can only be granted by an admin) |
| teams | create / join / get / `mine` / remove member |
| submissions | create / update / submit (deadline `403`), detail, public gallery |
| judging | rubric, assign, my/all assignments, progress, scores (`/mine` vs organizer-only all), normalize, results, `export.csv`, `attestation` (a judge's own signed proof of their scores, any time) |
| voting | `POST /submissions/{id}/vote`, `/votes/count`, `GET /events/{id}/ballot`, comments |
| admin | `GET /admin/audit` (`?format=text`; organizers see their own events only), `GET /admin/audit/verify` (hash-chain integrity check, any organizer) |
| data | `POST /events/{id}/export`, `POST /events/{id}/import[?dry_run=true]` |
| certificates | `GET /events/{id}/certificates/{user}[?format=pdf\|html]`, `GET /verify/{code}`, `POST /verify`, `GET /.well-known/dogfood-signing-key` |
| webhooks | `POST /webhooks/subscribe`, `GET /webhooks`, `DELETE /webhooks/{id}`, `/webhooks/{id}/deliveries`, `/webhooks/{id}/ping`, `GET /webhooks/event-types` |
| embed | `GET /embed/{id}/gallery` (JSON, CORS `*`), `GET /embed/{id}` (iframe page), `GET /embed.js` |

**Guarantees enforced by tests:** the spec is valid OpenAPI 3.1; every route has an entry in `app/openapi_meta.py` (so nothing ships undocumented); real
responses contain no field the schema omits; and `backend/scripts/check_openapi.py` checks that **every endpoint the frontend calls exists in the spec**.

### Public voting (T3)

Set per event: `voting_mode` = `open` (signed session cookie) · `email` (canonical mailbox, not verified) · `auth` (signed in) · `quadratic` (n votes cost n² of
`vote_credits`); `votes_per_voter` (default **1**). Rules and worked examples: `JUDGING.md`. Abuse controls and what remains: `THREAT-MODEL.md`.

### Embeddable gallery (T4)

```html
<script src="http://localhost:8000/embed.js" data-event="EVENT_ID" data-limit="12" data-theme="dark"></script>
```

Inserts an auto-resizing iframe right after the tag (or into `data-target="#selector"`; works from `<head>`). Options: `data-limit`, `data-theme`, `data-track`, `data-height`,
`data-width`; through the web proxy use `http://localhost:3000/api/embed.js`. Public, read-only, no cookies; only what the public gallery already shows (never drafts,
scores, tallies or `custom_answers`). Organizers copy the snippet from *Event → Data*.

### Export / import a whole event (T4)

`POST /events/{id}/export` downloads one versioned, checksummed JSON file (event, users, roles, rubric, teams, submissions, assignments, scores, votes, comments,
audit history; **never** password hashes). `POST /events/{id}/import[?dry_run=true]` restores it: validated first (every problem listed, nothing written on failure),
one transaction, idempotent, additive, users matched by email, `409` if an id belongs to another event, never mints admins. Format and guarantees: `DATA-MODEL.md`.

### Webhooks (T4)

Events (`GET /webhooks/event-types`): `submission.submitted`, `team.created`, `vote.cast`, `comment.added`, `judging.normalized`, `event.status_changed`,
`results.published`, `certificate.issued`, `webhook.ping`. A hook is scoped to one event or to every event you organize.

```
POST https://your.endpoint/hook
X-Dogfood-Event: submission.submitted
X-Dogfood-Delivery: 5b0d…              # stable across retries: de-duplicate on it
X-Dogfood-Timestamp: 1790518931
X-Dogfood-Attempt: 1
X-Dogfood-Signature: sha256=<HMAC-SHA256(secret, "<timestamp>.<raw body>")>

{"id":"5b0d…","type":"submission.submitted","created_at":"…","event_id":"…","data":{"submission_id":"…","name":"…","team_id":"…"}}
```

Verify in the receiver: recompute the HMAC over `f"{timestamp}.{raw_body}"` with the secret shown once at registration, compare with `hmac.compare_digest`, reject timestamps
older than 5 minutes (reference: `verify_signature()` in `backend/app/services/webhook_service.py`). Respond `2xx`; anything else is retried.

| Property | How |
|----------|-----|
| Never lost | **Transactional outbox**: the delivery row is inserted in the same transaction as the change, a worker sends it |
| Retries | Backoff `5s, 30s, 2m, 10m, 1h`, 6 attempts, then *dead*; same id and body every time |
| Bad endpoints | 10 dead deliveries in a row (or a `410`) switch the endpoint off, with a stated reason |
| No double sends | Workers lease a delivery (`FOR UPDATE SKIP LOCKED`) |
| SSRF guard | http(s) only, no redirects, host re-resolved and every address checked when subscribing **and right before each send**; link-local/cloud-metadata always refused; private networks refused unless `WEBHOOK_ALLOW_PRIVATE_TARGETS=true` (**on in this demo compose file, leave off in production**) |
| No leaks | Payloads carry ids and public facts only: no tallies, scores, emails; the secret is shown once |

### Certificates and signed judge participation records (T4)

Once an event is published, participants, judges and winners can open a certificate (`participant`, `judge` = a participation record with review counts and period,
never the scores, `winner` = top 3 by normalized rank), as JSON, PDF or self-contained verifiable HTML. Each is signed with **Ed25519** over its canonical JSON,
issued once, then stable. Anyone can verify, with no account: the public page `/verify/<code>`, `GET /verify/{code}`, `POST /verify`, or **offline** with only the Python
standard library:

```bash
python backend/scripts/verify_certificate.py --server http://localhost:8000 certificate.json     # or certificate.html, or --key <public key>
```

Limits: PDFs render names in a vendored Unicode font (Latin Extended, Cyrillic, Greek, Vietnamese; CJK still prints as `?` - JSON/HTML always keep the exact
name); no revocation list. The signing key derives from `CERT_SIGNING_KEY` (falls back to `JWT_SECRET_KEY`).

**A judge's own score attestation** is a related but separate document: `GET /events/{id}/judging/attestation` signs the judge's **actual current scores**
(not just counts) with the same Ed25519 key, available any time - not gated on the event closing, and not stored, so re-requesting it after changing a score
signs a fresh snapshot rather than returning a stale one. Because it carries real score values, it is deliberately **not** reachable via the public
`GET /verify/{code}` lookup the way a certificate is; only someone holding the document (the judge, or an organizer they showed it to) can check it with
`POST /verify` or the same offline `verify_certificate.py`.

---

## Configuration

Compose sets these inline; for local runs copy `backend/.env.example` to `backend/.env`. Full table (defaults, meaning): **ARCHITECTURE.md §6**. The ones that matter first:

| Variable | Purpose |
|----------|---------|
| `JWT_SECRET_KEY` | **Change it** for anything beyond a local demo (the demo value is public; the API warns at boot). Also seeds the certificate key unless `CERT_SIGNING_KEY` is set |
| `WEBHOOK_ALLOW_PRIVATE_TARGETS` | `true` only for local receivers; the SSRF guard otherwise |
| `TRUST_PROXY_HEADERS` | take the client IP from `X-Forwarded-For`; set `false` if port 8000 is exposed directly |
| `REDIS_URL` | shared rate limits (in-memory per process without it) |
| `PUBLIC_WEB_URL`, `PUBLIC_API_URL` | links in embeds, snippets and certificates |

Before going live read the checklist in **THREAT-MODEL.md §7**.

---

## Project layout

```
dogfood/
├── docker-compose.yml           # the whole stack (+ `test` profile: test-db, pytest)
├── run.py · .dogfood.toml · fixtures.json · acceptance-report.txt      # DOGFOOD checker files
├── README.md · ARCHITECTURE.md · DATA-MODEL.md · JUDGING.md · THREAT-MODEL.md · API-CHANGELOG.md · LICENSE (MIT)
├── backend/
│   ├── app/
│   │   ├── main.py · config.py · database.py · middleware.py · openapi_meta.py
│   │   ├── api/        # routers: auth, events, teams, submissions, judging, voting, admin, embed, dump, certificates, webhooks; deps.py = roles
│   │   ├── models/     # SQLAlchemy models (lazy="raise")
│   │   ├── schemas/    # request models, typed response models (api.py), size limits (limits.py), dump format (dump.py)
│   │   ├── services/   # judging engine, voting, audit, fixtures, export/import, certificates, signing, webhooks
│   │   ├── utils/      # security (JWT, bcrypt), rate limiting, fingerprints
│   │   └── static/     # vendored Swagger UI (offline /docs)
│   ├── alembic/versions/                                # migrations (checked against the models)
│   ├── scripts/        # entrypoint, seed, test-pipeline, live_*.py, probe_abuse.py, check_openapi.py, verify_certificate.py, verify_audit_chain.py
│   └── tests/          # pytest (real Postgres via the test profile)
└── frontend/           # Next.js app, e2e-ui.py / e2e-ui-flows.py / e2e-embed.py (Playwright), docs/API-GAPS.md
```

---

## Testing and verification

```bash
docker compose --profile test run --rm pytest        # 262 tests on a throwaway real Postgres (isolated `test-db`, never the dev DB)
docker compose --profile test run --rm test          # CI-style pipeline: tests, migration check, seed, boot, smoke
python run.py .dogfood.toml                          # the official checker
python backend/scripts/check_openapi.py              # spec valid + complete + covers every frontend call
python backend/scripts/live_lifecycle.py             # 113 checks: whole lifecycle + negative cases, live
python backend/scripts/live_t3.py                    # 37 checks: public voting through the real web proxy
python backend/scripts/live_webhooks.py              # 21 checks: a real receiver, signatures, retries, SSRF
python backend/scripts/verify_audit_chain.py         # recomputes the audit log's hash chain independently: expects "OK"
python backend/scripts/probe_abuse.py                # 96 hostile-input probes + 16 authorization exploits: expects "clean"
python frontend/e2e-ui.py                            # every page × 5 roles in a real browser
python frontend/e2e-ui-flows.py                      # 13 interactive flows (vote, score, export/import, certificates, webhooks, ...)
python frontend/e2e-embed.py                         # the widget from a different origin
```

The browser scripts need `pip install playwright` and Chrome. `acceptance-report.txt` holds the last official checker output.

---

## Frontend

Next.js 16 App Router, 27 routes. The browser only talks to `:3000`; `/api/*` is rewritten to FastAPI (no CORS in Compose). Security headers are set (`nosniff`, referrer
policy, `frame-ancestors 'self'` except for the embeddable pages); user text is rendered only through React; only `http(s)` links are clickable.

| Mode | Data | Use |
|------|------|-----|
| **Live** (`NEXT_PUBLIC_MOCK=false`, default in Compose) | FastAPI via the `/api` proxy | real auth + persistence |
| **Mock** (`NEXT_PUBLIC_MOCK=true`) | built-in in-browser API | design review / demos with no backend |

`NEXT_PUBLIC_*` and `API_INTERNAL_URL` are baked at build time (Compose `build.args`). Local dev: `cd frontend && npm install && npm run dev` (`npm run typecheck`, `npm run build`).

| Audience | Routes |
|----------|--------|
| Public | `/` · `/events` · `/events/[id]` · gallery · `/submissions/[sid]` · `/login` · `/signup` · `/embed/[id]` · `/verify/[code]` |
| Participant | team · `/submit` · `/join/[teamId]` · certificate · `/vote` |
| Judge | `/judge` queue · `/judge/[sid]` scoring · `/judge/duel` (pairwise, not built: `501`) |
| Organizer / admin | `/rubric` · `/assign` · `/progress` · `/results` · `/audit` · `/settings` · `/data` · `/webhooks` · `/events/new` · `/admin/audit` |

---

## Development

| Task | Command |
|------|---------|
| Full stack | `docker compose up -d --build` |
| Backend only | `cd backend && pip install -r requirements.txt && alembic upgrade head && python -m scripts.seed && uvicorn app.main:app --reload --port 8000` |
| Frontend only (mock) | `cd frontend && NEXT_PUBLIC_MOCK=true npm run dev` |
| Logs | `docker compose logs -f api` (or `web`) |
| Rebuild one service | `docker compose up -d --build api` (or `web`) |
| Fresh database | `docker compose down -v && docker compose up -d --build` |

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Port already in use | Stop other dev servers on 3000/8000/5432/6379, or `docker compose down` first |
| Frontend can't reach the API in Compose | `API_INTERNAL_URL` must be `http://api:8000` (the service name), passed as a build arg |
| Stale data or ids not matching `.dogfood.toml` | `docker compose down -v` then `up -d --build` (the seed skips data that already exists) |
| `429 Too many …` while testing | Rate limits are per IP: wait for `Retry-After`, or `docker compose exec redis redis-cli flushdb` |
| Webhook to `localhost` / a LAN address is refused | `WEBHOOK_ALLOW_PRIVATE_TARGETS=true` (on in the demo compose); from the api container the host is `host.docker.internal` |
| Mock still on in the UI | `NEXT_PUBLIC_MOCK=false`, then rebuild `web` |
| Dev API shows a duplicate-table error after adding a model | The hot-reloading dev API can create tables before Alembic runs; `docker compose down -v` and start clean |

## License

MIT (see `LICENSE`). Swagger UI, vendored under `backend/app/static/swagger/`, is Apache-2.0 (its license is included).
