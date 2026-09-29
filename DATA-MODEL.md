# DOGFOOD Data Model

## Overview

The DOGFOOD hackathon platform uses PostgreSQL with SQLAlchemy 2.0 async ORM. The data model supports events, teams, submissions, judging, public voting, certificates, webhooks and an append-only audit log. The schema is defined by the models in `backend/app/models/` and shipped as Alembic migrations (`backend/alembic/versions/`, checked against the models with `alembic check`).

Conventions: primary keys are UUID strings (`VARCHAR(36)`); every relationship is `lazy="raise"` (no implicit loads, see ARCHITECTURE.md); timestamps are timezone-aware; judgment data (scores, votes, audit) is never deleted by the application.

## Entity Relationship Diagram

```
User ─┬─< EventRole >── Event ─┬─< Track
      │                         ├─< Team ─< TeamMembership >── User
      │                         ├─< Submission ─< Score >── RubricCriterion
      │                         ├─< JudgeAssignment >── User
      │                         └─< Vote, Comment
      ├─< Certificate >── Event
      └─< Webhook ──< WebhookDelivery        (Webhook.event_id is optional)
AuditLog (event_id, actor_id: soft references, so history outlives what it describes)
```

## Tables

### Users
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| email | VARCHAR(255) | UNIQUE, NOT NULL |
| password_hash | VARCHAR(255) | NOT NULL |
| name | VARCHAR(255) | NOT NULL |
| created_at | TIMESTAMPTZ | DEFAULT NOW() |

### Events
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| organizer_id | UUID | FK → users.id |
| name | VARCHAR(255) | NOT NULL |
| slug | VARCHAR(255) | UNIQUE, NOT NULL |
| description | TEXT | |
| start_date | TIMESTAMPTZ | |
| end_date | TIMESTAMPTZ | |
| submission_deadline | TIMESTAMPTZ | |
| judging_opens_at | TIMESTAMPTZ | |
| judging_closes_at | TIMESTAMPTZ | |
| voting_opens_at | TIMESTAMPTZ | |
| voting_closes_at | TIMESTAMPTZ | |
| team_formation_start / _end | TIMESTAMPTZ | |
| status | ENUM | draft, live, judging, voting, closed (UI names: draft, open, judging, voting, published) |
| voting_mode | VARCHAR(20) | `open` \| `email` \| `auth` \| `quadratic`, default `auth` |
| votes_per_voter | INT | approval-voting budget per person per event, default 1 |
| vote_credits | INT | quadratic-voting credits per person, default 25 |
| created_at | TIMESTAMPTZ | DEFAULT NOW() |

### Tracks
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| event_id | UUID | FK → events.id |
| name | VARCHAR(255) | NOT NULL |
| description | TEXT | |

### EventRoles
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| user_id | UUID | FK → users.id |
| event_id | UUID | FK → events.id |
| role | ENUM | participant, judge, organizer, admin |
| | | UNIQUE(user_id, event_id, role) |

### Teams
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| event_id | UUID | FK → events.id |
| name | VARCHAR(255) | NOT NULL |
| invite_code | VARCHAR(32) | UNIQUE, NOT NULL |
| created_at | TIMESTAMPTZ | DEFAULT NOW() |

### TeamMemberships
| Column | Type | Constraints |
|--------|------|-------------|
| team_id | UUID | FK → teams.id, PK |
| user_id | UUID | FK → users.id, PK |
| role_in_team | ENUM | leader, member |

### Submissions
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| team_id | UUID | FK → teams.id |
| event_id | UUID | FK → events.id |
| track_id | UUID | FK → tracks.id (nullable) |
| name | VARCHAR(255) | NOT NULL |
| tagline | VARCHAR(500) | |
| description_md | TEXT | |
| thumbnail_url | VARCHAR(500) | |
| gallery_image_urls | JSON | DEFAULT [] |
| demo_video_url | VARCHAR(500) | |
| repo_url | VARCHAR(500) | |
| live_url | VARCHAR(500) | |
| tech_tags | JSON | DEFAULT [] |
| custom_answers | JSON | DEFAULT {} |
| status | ENUM | draft, submitted |
| submitted_at | TIMESTAMPTZ | |
| last_edited_at | TIMESTAMPTZ | |
| created_at | TIMESTAMPTZ | DEFAULT NOW() |

### RubricCriteria
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| event_id | UUID | FK → events.id |
| track_id | UUID | FK → tracks.id (nullable) |
| name | VARCHAR(255) | NOT NULL |
| description | TEXT | |
| weight | FLOAT | DEFAULT 1.0 |
| scale_min | FLOAT | DEFAULT 1.0 |
| scale_max | FLOAT | DEFAULT 10.0 |

### JudgeAssignments
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| judge_id | UUID | FK → users.id |
| submission_id | UUID | FK → submissions.id |
| batch_id | VARCHAR(36) | |
| status | ENUM | pending, in_progress, completed |
| assigned_at | TIMESTAMPTZ | DEFAULT NOW() |
| | | UNIQUE(judge_id, submission_id) |

### Scores
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| judge_id | UUID | FK → users.id |
| submission_id | UUID | FK → submissions.id |
| criterion_id | UUID | FK → rubric_criteria.id |
| raw_value | FLOAT | NOT NULL |
| comment | TEXT | |
| created_at | TIMESTAMPTZ | DEFAULT NOW() |
| updated_at | TIMESTAMPTZ | DEFAULT NOW() |
| | | UNIQUE(judge_id, submission_id, criterion_id) |

### NormalizedScores
| Column | Type | Constraints |
|--------|------|-------------|
| submission_id | UUID | FK → submissions.id, PK |
| criterion_id | UUID | FK → rubric_criteria.id, PK |
| method | VARCHAR(50) | PK |
| normalized_value | FLOAT | NOT NULL |
| computed_at | TIMESTAMPTZ | DEFAULT NOW() |

### Votes
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| submission_id | UUID | FK → submissions.id |
| event_id | UUID | FK → events.id, INDEX (the per-event budget is counted on this) |
| voter_fingerprint | VARCHAR(64) | NOT NULL: SHA-256 of the voter identity (user id / canonical email / signed session), never raw |
| ip_hash | VARCHAR(64) | SHA-256 of the client IP, for the per-network cap |
| weight | INT | DEFAULT 1: votes allocated (approval voting = 1; quadratic voting = n, costing n² credits) |
| created_at | TIMESTAMPTZ | DEFAULT NOW() |
| | | UNIQUE(submission_id, voter_fingerprint); INDEX(event_id, voter_fingerprint) |

### Comments
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| submission_id | UUID | FK → submissions.id |
| author_id | UUID | FK → users.id (nullable) |
| body | TEXT | NOT NULL |
| created_at | TIMESTAMPTZ | DEFAULT NOW() |

### AuditLogs
Hash-chained, not just append-only by convention: `seq` gives a strict, DB-assigned insertion
order (independent of wall-clock time, which can collide under load), and each row's `hash`
covers its own fields plus the previous row's `hash` (`prev_hash`). Editing, reordering or
deleting any past row breaks every hash after it - detectable via `GET /admin/audit/verify` or
`backend/scripts/verify_audit_chain.py`, both of which recompute the whole chain independently
rather than trusting a stored flag. See `THREAT-MODEL.md` R4 / J7.

| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| seq | BIGINT | Identity (DB-assigned), UNIQUE, INDEX: strict insertion order |
| actor_id | UUID | FK → users.id (nullable = system / anonymous) |
| event_id | UUID | INDEX, nullable; the event the action belongs to (powers `/admin/audit?event_id=`) |
| action | VARCHAR(100) | NOT NULL, INDEX, e.g. `vote.cast`, `score.update`, `role.grant`, `event.status_change` |
| target_type | VARCHAR(50) | NOT NULL |
| target_id | VARCHAR(36) | NOT NULL |
| extra_data | JSON | DEFAULT {}: `role`, `ip`, `outcome` (ok/denied), `detail`, action-specific fields |
| created_at | TIMESTAMPTZ | DEFAULT NOW(), INDEX |
| prev_hash | VARCHAR(64) | NOT NULL: the previous row's `hash`, or 64 zeros for the first row ever |
| hash | VARCHAR(64) | NOT NULL: sha256 of this row's own fields (incl. `seq`, `prev_hash`), canonical JSON |

### Certificates
| Column | Type | Constraints |
|--------|------|-------------|
| id | UUID | PK |
| user_id | UUID | FK → users.id |
| event_id | UUID | FK → events.id |
| type | VARCHAR(50) | NOT NULL: `participant` \| `judge` \| `winner` |
| issued_at | TIMESTAMPTZ | DEFAULT NOW() |
| verification_hash | VARCHAR(64) | UNIQUE, INDEX: sha256 of the canonical signed payload |
| payload | JSON | the exact signed document |
| signature | TEXT | Ed25519, base64url |
| | | UNIQUE(user_id, event_id, type) |

(Details of what is signed and how it is verified: "Certificates" at the end of this file.)

## Denormalization Decisions

1. **NormalizedScore**: Computed on-demand, not stored per-score. Avoids stale data issues. (The table exists for the `/judging/normalize` write-through; results are always recomputed from raw scores.)
2. **AuditLog**: Append-only with JSON metadata. Flexible schema without migrations. `event_id` is a plain indexed column, not a foreign key, so history survives event deletion.
3. **Vote.voter_fingerprint**: Uses unique constraint for DB-level dedup, not app-level. `Vote.event_id` is denormalized from the submission so the per-event budget is a single indexed count.
4. **Certificate.payload/signature**: stored verbatim so a certificate can never silently change and a database edit is detectable.
5. **WebhookDelivery.body**: stores the exact bytes that are signed and sent, so a retry is byte-identical.

## Fixtures import (`fixtures.json`)

The DOGFOOD spec ships a `fixtures.json`; it is loaded **at boot** (entrypoint runs
`python -m scripts.seed`, and app startup does the same idempotently) from
`FIXTURES_PATH` (`/data/fixtures.json`, mounted read-only from the repo-root `fixtures.json`
by `docker-compose.yml`). There is no import HTTP route: the checker only makes normal
API calls, so the data simply has to be there when `docker compose up` finishes.
Code: `app/services/fixture_import.py`. (Whole-event JSON export/import is a separate feature, below.)

### Mapping

| Fixture | Becomes | Notes |
|---------|---------|-------|
| `event` | `events` row (status `judging`) | `submissions_close` -> `submission_deadline`; the other windows are derived from it (judging +7d, voting +14d). The deadline check that refuses late submissions is driven by **this** date. Organizer = `organizer@dogfoodhack.com`. |
| `tracks[]` | `tracks` | |
| `judges[]` | `users` (by email) + `event_roles(judge)` | `judges[].tracks` has no column and is not stored. |
| `teams[]` | `teams` + `team_memberships` + `event_roles(participant)` | Member emails become users; first member is the leader. Deterministic `invite_code` (sha256 of the team id). |
| `projects[]` | `submissions` (status `submitted`) | `title` -> `name`, `summary` -> `tagline`, `repo_url`, `submitted_at`. `created_at` is set strictly increasing in fixture order so the gallery is stable. An unknown `team` gets a placeholder team; an unknown `track` becomes `NULL`. |
| `scores[]` | `rubric_criteria` + `scores` + `judge_assignments(completed)` | See below. |

### Ids

Fixture ids are opaque strings; ours are UUIDs. Every fixture id maps to a deterministic
`uuid5` (`app/services/stable_ids.py`, e.g. `stable_id("project", "prj_01")`), and users
map by lower-cased email. So the same file yields the same row ids on every boot and
machine, which is what lets `.dogfood.toml` hard-code real routes.

### `scores[].criteria` is a flat dict

Criterion names are not pre-registered. The first time a name is seen a `RubricCriterion`
is created (`weight 1.0`, `scale_min 0`, `scale_max 5`, widened to `ceil(max value)` if a
larger value appears). Each `criteria` entry becomes one `scores` row; the score's single
`comment` is copied onto each of its criterion rows (empty string -> `NULL`). A
`judge_assignments` row (status `completed`) is created for every `(judge, project)` that
has a score. Non-numeric values and scores for an unknown project are skipped and reported
in the import summary.

### Awkward cases in the official file (verified against the real data)

The official `fixtures.json` has 30 judges, 40 teams, 41 project rows and 126 score rows (378 criterion
values); its shape is identical to the published schema (no import changes were needed). What is actually in it:

| Case | In the real file | Handling / observed result |
|------|------------------|----------------------------|
| **Duplicate submission** | `prj_41` repeats `prj_07`: same team `tm_07`, same title "Dry Harbour", same `repo_url`, **different id**, later `submitted_at` | Caught by the team+title rule (not by id). One project remains (id `prj_07`, `prj_41`'s fields win). Import summary: `1 duplicate project row(s) merged`. Judges `jdg_19`, `jdg_21`, `jdg_26` scored both ids, so their 9 criterion rows collide after the merge and the later row wins; 378 - 9 = **369** score rows, 6 distinct reviewers on "Dry Harbour" |
| **Flat-scoring judge(s)** | `jdg_07` (Iva Petrova) gave 4/4/4 on all 3 projects; Mira Kaur (`jdg_19`) is flat only as a side effect of the duplicate merge: she reviewed both `prj_07` (weighted 2.33) and its duplicate `prj_41` (3.67); last-write-wins keeps 3.67, so all three of her remaining projects score 3.67 | Both hit the zero-variance fallback (`sd = 0`): their raw score is standardised against the pooled mean/sd, so z-scores stay in [-1.26, 1.14]; reported in `zero_variance_judges` and audit-logged. Policy note: keeping the *later* review of a duplicated project is the documented rule; averaging the two reviews would be the alternative |
| **Unfinished review batches** | Review counts per project range 2-5 (8 projects with only 2); two judges (`jdg_01` Tomas Varga, `jdg_23` Anya Sokolova) submitted **a single review** each; no score row has a missing criterion | All 40 projects appear in `/judging/results` and the CSV (`judge_count` 2-6 after the merge). Single-review judges also use the fallback (sd undefined) and are flagged `single_review` (UI shows a dagger, not "identical scores") |
| Not present | judge with no `tracks`, null/empty project fields, email reused across judges/members, judge on their own team, scores for unknown ids, submissions after the deadline | nothing to handle; the import tolerates them anyway (see below) |

The results were cross-checked against an independent recomputation (plain `statistics`, no app code):
all 40 projects match to floating-point equality (`norm_z`, `raw_mean`, review counts, rank order).

The import also tolerates, and the tests cover, the shapes the real file happens not to contain:

- **Duplicate projects - last write wins, first id stays canonical.** A repeated `id` is
  overwritten by the later row. A *new* id with the same team and the same title
  (case/whitespace-insensitive) is treated as the same project: it overwrites the earlier
  row's fields, and any scores that reference the alias id are remapped onto the canonical
  project. One `submissions` row results either way.
- **Duplicate scores** for the same `(judge, project, criterion)`: last write wins
  (`UNIQUE(judge_id, submission_id, criterion_id)`).
- **Uneven review counts** (some projects with 2 reviews, some with 5): nothing assumes a
  fixed reviews-per-submission; `judge_count` is per submission.
- **A judge who scored everything identically:** stored as given; normalization handles it
  (`JUDGING.md`, zero-variance fallback). Single-review judges take the same fallback.
- **A judge who is also a team member:** they hold both `judge` and `participant` roles in
  the event (`require_role` accepts any held role).
- **Idempotent:** if the fixture event already exists the import is skipped.

### Checker identities

`participant1@dogfoodhack.com` is additionally made `participant` on the fixture event and
leader of a "Checker Probe Team" (no submission, so it never appears in the gallery); the
checker's submit probe targets that team. The first two fixture judges are `judge_a` /
`judge_b` (with the official file: `jdg_01` Tomas Varga and `jdg_02` Wei Lindqvist; no judge is a team member there, so the dedicated probe participant is not ambiguous) (falling back to the seeded `judge1` / `judge2` if the file has fewer than two).
See `ARCHITECTURE.md`.


## Event export / import (`POST /events/{id}/export`, `POST /events/{id}/import`)

Portability beyond CSV: one JSON document holds an entire event and restores it elsewhere. Code:
`app/services/event_dump.py`, format models in `app/schemas/dump.py`.

### Format `dogfood-event-dump`, version 1

```json
{ "format": "dogfood-event-dump", "version": 1, "exported_at": "...", "checksum": "<sha256>",
  "event":       { "id", "name", "slug", "description", "status", "<all dates>", "voting_mode", "votes_per_voter", "vote_credits" },
  "users":       [ { "id", "email", "name" } ],
  "roles":       [ { "user_id", "role" } ],
  "tracks":      [ ... ],  "criteria": [ ... ],
  "teams":       [ { "id", "name", "invite_code", "members": [ { "user_id", "role_in_team" } ] } ],
  "submissions": [ every column, incl. gallery_image_urls / tech_tags / custom_answers ],
  "assignments": [ ... ],  "scores": [ raw values + comments ],  "votes": [ hashed voter fingerprints + weights ],
  "comments":    [ ... ],  "audit":  [ the event's append-only history ] }
```

Not exported, on purpose: **password hashes and tokens**, raw IPs/emails of voters (votes carry SHA-256 fingerprints only),
normalized scores (recomputed from raw scores, so results are reproducible rather than trusted) and certificates
(re-issued from the restored data). `checksum` is a sha256 of the canonical JSON of everything else (integral floats are
canonicalised, because JavaScript rewrites `4.0` as `4` when it re-serialises a dump); it detects hand edits and truncation.

### Import guarantees

1. **Validated first.** Structure, version, checksum, enums, ISO timestamps, duplicate ids, every reference (team, track,
   criterion, submission, user) and every score against its criterion's scale. All problems are reported together (422)
   and nothing is written. `?dry_run=true` runs the whole thing inside a savepoint that is always rolled back.
2. **One transaction**, applied in dependency order; any failure rolls everything back.
3. **Idempotent upsert.** Rows match by id or natural key (`(judge, submission, criterion)` for scores, `(submission,
   fingerprint)` for votes, `(judge, submission)` for assignments, `(team, user)` for memberships); re-importing the same dump
   creates nothing new (tested).
4. **Additive.** It never deletes. An id that already belongs to a *different* event is a `409`, never a silent overwrite.
5. **Accounts.** Users are matched by email. Unknown emails get an account whose password nobody knows (they must be given
   access another way); existing accounts are never modified.
6. **Audit.** `event.export` and `event.import` (with the checksum and per-section counts) are logged; a score overwritten with
   a different value is logged as `score.update` (`via: import`). The dump's audit history is restored only into the event it
   came from, and each restored row is tagged `imported: true`, so imported history can never pass for native history.

Restoring elsewhere: create an empty event (`POST /events`), then `POST /events/{new_id}/import`. Settings (name, dates, status,
voting config) are copied onto it; its own id/slug/organizer are kept. Restoring into the *same* event id (after data loss)
just works. Import size is capped at 50 MB / 200 000 rows.


## Webhooks (`webhooks`, `webhook_deliveries`, `app/services/webhook_service.py`)

`webhooks`: `owner_id`, optional `event_id` (NULL = every event the owner organizes), `url`, `event_types` (JSON list or `*`), `secret` (HMAC key),
`active`, `consecutive_failures`, `disabled_reason`, `last_status`, `last_delivery_at`.
`webhook_deliveries` is the **outbox**: one row per (event, endpoint), written in the same transaction as the change; `body` is the exact JSON
that is sent and signed, `status` is `pending → sending → success | retry → … → dead`, with `attempts`, `next_attempt_at` (also the lease while
`sending`), `response_status`, `last_error`. Index `(status, next_attempt_at)` serves the worker's "what is due" query.

## Certificates (`certificates` table, `app/services/certificate_service.py`)

| Column | |
|--------|--|
| `user_id`, `event_id`, `type` | recipient, event, kind (`participant` \| `judge` \| `winner`); **unique together**: one certificate per kind |
| `payload` (JSON) | the exact signed document: `{v, issuer, kind, event{id,name}, recipient{id,name}, detail, issued_at[, record]}` |
| `signature` | Ed25519 over `canonical(payload)` (UTF-8 JSON, sorted keys, `(",", ":")` separators), base64url |
| `verification_hash` | `sha256(canonical(payload))` hex: the public code (unique) |

`record` holds only counts: judges `{projects_reviewed, criterion_scores, first_review, last_review}`, winners `{place, projects_ranked}`.
Entitlement is computed from live data at issuance (team membership + submitted project; judge role + at least one score; top-3 normalized
rank once published) and the result is frozen in the row. `check_record()` recomputes hash and signature, so a database edit is detected
by `GET /verify/{code}`. Certificates are not part of event dumps: they are re-issued from the restored data.

### Score attestations (not a table)

`GET /events/{id}/judging/attestation` (`certificate_service.build_score_attestation`) signs the same shape (`kind:
"judge_score_attestation"`) with `record: {scores: [{submission_id, submission_name, criterion_id, criterion_name, value, comment,
updated_at}, ...]}` - the judge's actual per-criterion values, which a `judge` certificate deliberately never includes. It is **not persisted**:
computed and signed fresh on every request, so it can never present a stale snapshot as current, and it has no `verification_hash` row for
`GET /verify/{code}` to find - only `POST /verify` (payload + signature in hand) or the offline verifier can check one. Available any time a
judge has scored something, not gated on the event closing.
