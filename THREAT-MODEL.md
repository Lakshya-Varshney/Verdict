# VERDICT Threat Model

A security analysis of how this platform can be abused, what stops it, what evidence shows that it works, and what is
**not** covered. It concentrates on **voting and submission abuse** (the brief's focus) and on **judging integrity**,
then covers the platform around them.

> **Method.** (1) List assets, actors and trust boundaries. (2) Walk every threat per asset (STRIDE-style) and record
> the control, where it lives in code, and the test that proves it. (3) **Attack the running system** with hostile input
> (`backend/scripts/probe_abuse.py`: 96 hostile-input probes) and with 16 hand-written exploits of the authorization model (same script). That last step
> found real vulnerabilities, listed in [§5](#5-what-adversarial-testing-found-and-fixed) together with their fixes and
> regression tests. Claims in this document that are not backed by a test say so.

Contents: [1 Assets & goals](#1-assets-and-security-goals) · [2 Actors](#2-actors) · [3 Trust boundaries](#3-trust-boundaries) ·
[4 Threat catalogue](#4-threat-catalogue) · [5 Found & fixed](#5-what-adversarial-testing-found-and-fixed) ·
[6 Residual risks](#6-residual-risks-known-and-accepted-or-open) · [7 Operator checklist](#7-operator-checklist-before-going-live) ·
[8 Re-running the evidence](#8-re-running-the-evidence)

---

## 1. Assets and security goals

| # | Asset | Goal |
|---|-------|------|
| A1 | **Judges' scores and the ranking** | Integrity: no one changes results unnoticed; no peeking (judges cannot see each other) |
| A2 | **Public votes** | One person, one vote (per event budget); tally secret until voting closes; ballot order fair |
| A3 | **Submissions and the deadline** | Only the team edits its work; nothing after the deadline; drafts stay private |
| A4 | **Audit log** | Append-only, complete, readable only by the event's organizers |
| A5 | **Accounts and roles** | No takeover, no privilege escalation, roles stay scoped to their event |
| A6 | **Certificates / judge records** | Unforgeable and verifiable by anyone; cannot silently change |
| A7 | **Personal data** | Names/emails visible only where needed; voters are pseudonymous; no secrets in payloads |
| A8 | **Availability** | Hostile input or floods cannot take the service down or make it slow |
| A9 | **The host and its network** | The platform cannot be turned into a proxy into the operator's network (webhooks) |

## 2. Actors

| Actor | Capabilities | Typical goal |
|-------|--------------|--------------|
| **Anonymous visitor** | Public API, gallery, embed, `verify` | Read what is not public; stuff votes; spam |
| **Vote-stuffer / botnet** | Many sessions, IPs and (in `auth` mode) accounts | Inflate a project |
| **Participant** | Own team's data | Edit late, edit others', see rivals' drafts, boost own project |
| **Judge (curious / colluding)** | Own scores | See peers' scores, score outside the assignment, inflate |
| **Organizer of event A** | Full control of event A | Read/alter event B, become site admin, rewrite history |
| **Site admin** | Everything (a role held in any event) | (trusted) |
| **Webhook owner (an organizer)** | Registers URLs the server will call | SSRF into the host network |
| **Network observer / MITM** | Sees traffic if no TLS | Steal tokens |
| **Operator with DB access** | Reads/edits the database | (trusted, but see §6) |

## 3. Trust boundaries

```
 Internet ──▶ [ Next.js :3000 ] ──/api rewrite──▶ [ FastAPI :8000 ] ──▶ PostgreSQL   (secrets, all data)
   │              (React escapes output;              │  request guard → rate limit → auth (JWT) →
   │               security headers)                  │  role check (per event, from the DB) → validation → service
   │                                                  ├──▶ Redis (rate-limit counters; optional, memory fallback)
   └── third-party sites ──▶ /embed*, /verify*        └──▶ outbound: webhook receivers (SSRF-guarded)
        (public, read-only, CORS *)
```

Every request passes, in order: the **request guard** (NUL bytes, body size) → **rate limits** where they matter → **authentication**
(HS256 JWT) → **authorization** (roles come from the database on *every* request, never from the token) → **input validation**
(Pydantic, bounded sizes, http(s)-only links) → business rules in services. Roles are **per event**; the one exception, a global `admin`
role (held in any event), can only be granted by another admin.

---

## 4. Threat catalogue

Status: ✅ mitigated and tested · 🟡 mitigated with a stated limit · ⚠️ residual risk (see [§6](#6-residual-risks-known-and-accepted-or-open)).

### 4.1 Voting abuse (A2)

| ID | Threat | Control (where) | Evidence | |
|----|--------|-----------------|----------|--|
| V1 | Vote repeatedly for the same project | DB `UNIQUE(submission, voter)` + per-event budget (`votes_per_voter`, default **1**) counted on `(event, voter)` (`voting_service.cast_vote`) | `test_duplicate_vote_rejected`, `test_one_vote_per_person_per_event`, `test_db_unique_constraint_backs_up_dedup`, `live_t3.py` | ✅ |
| V2 | Race: two concurrent votes both pass the budget check | The event row is locked (`SELECT … FOR UPDATE`) for the duration of the check-and-insert; the unique constraint is the backstop | constraint tested; the lock is exercised by every vote, but **no concurrent-vote load test exists** | 🟡 |
| V3 | Clear cookies / new browser to vote again (`open` mode) | Identity is a signed session cookie **plus** a per-network cap (`VOTES_PER_IP_MULTIPLIER × budget` votes per IP per event) and rate limits | `test_rotating_cookies_from_one_ip_still_hits_ip_ceiling` | 🟡 many IPs beat it (R1) |
| V4 | Rotate IPs to dodge rate limits/caps | Two limiter keys: per (IP + identity) and a looser per-IP ceiling; Redis-backed (a true sliding window, so a burst cannot straddle a boundary to double the limit) with memory fallback | `test_vote_rate_limit_returns_429`, `test_redis_limiter_is_a_sliding_window_not_a_fixed_one`, `live_t3.py` (429 + `Retry-After`) | 🟡 spoofable `X-Forwarded-For` if :8000 is exposed (R2) |
| V5 | Many accounts in `auth`/`quadratic` mode (Sybil) | Signup is rate limited (100/min/IP); identity = user id | `test_signup_flood_is_throttled` | ⚠️ R1: open signup is not proof of unique personhood |
| V6 | Mint extra votes with mail aliases (`a+1@x`, Gmail dots) in `email` mode | Voter identity is the **canonical mailbox** (lower-case, `+tag` dropped, Gmail dots ignored) | `test_email_aliases_collapse_to_one_identity`, `test_plus_addressing_cannot_mint_extra_votes` | 🟡 email is not verified (R3) |
| V7 | Vote outside the voting window or on the wrong status | `window_error`: status must be `voting` **and** inside the optional dates, checked server-side under the lock | `test_voting_blocked_outside_voting_status`, `test_voting_respects_dates` | ✅ |
| V8 | Vote for a draft / unknown / other-event project | `_published_submission` → 404 | `test_cannot_vote_for_a_draft` | ✅ |
| V9 | Overspend quadratic credits; negative / huge / fractional votes | Budget recomputed server-side from stored allocations; `votes` is `0..100` (schema); cost `n²` checked against `vote_credits` | `test_quadratic_voting`, `test_comment_and_vote_inputs_are_bounded` | ✅ |
| V10 | Learn the tally while voting is open | The count endpoint returns `hidden:true` and **null for both** `count` and `vote_count` (the latter used to leak the number); results and CSV are organizer-only; the embed and webhook payloads contain no tallies; the audit view is organizer-only | `test_results_hidden_during_voting_window`, `test_no_tally_leaks_while_voting`, `test_vote_events_never_carry_tallies` | ✅ |
| V11 | Position bias: first item on the ballot wins | Per-voter seeded shuffle (user id or session), stable per voter, different across voters | `test_ballot_order_is_per_session_and_stable`, UI flow | ✅ |
| V12 | De-anonymize voters | Votes store SHA-256 fingerprints and an IP hash, never raw email/IP; payloads and the embed never include them | tests above | ⚠️ R7: unsalted hashes can be confirmed by a guess |
| V13 | Forge votes | Only via an organizer's import/DB access | — | ⚠️ R4 (a malicious organizer is trusted with their own event) |

### 4.2 Public content: comments and project pages

| ID | Threat | Control | Evidence | |
|----|--------|---------|----------|--|
| C1 | Stored XSS in comments, names, taglines | The API stores text verbatim and **never renders it**; React escapes on output; the embed page HTML-escapes every value; only `http(s)` links/images are ever emitted; the embed page carries a locked-down CSP | `test_html_page_escapes_everything_and_blocks_script_urls`; no `dangerouslySetInnerHTML` on user data (the only use is a static theme snippet) | ✅ |
| C2 | `javascript:` / `data:` links in repo/demo/thumbnail fields | Rejected at write (`422`, http(s) only) for submissions **and** for imported dumps; the frontend also drops any non-http(s) link (`safeHref`) for old data | `test_project_links_must_be_http_or_https`, `test_dumps_cannot_smuggle_script_urls_in` | ✅ |
| C3 | Comment spam / flooding | Rate limit (per IP + identity, plus a per-IP ceiling), 5 000-character cap, empty rejected, no comments on drafts | `test_comment_rate_limit`, `test_no_comments_on_drafts` | 🟡 no moderation/delete tool (R8) |
| C4 | Impersonation via anonymous `author_name` | Length-capped; shown as given | — | ⚠️ R8 |

### 4.3 Submissions (A3)

| ID | Threat | Control | Evidence | |
|----|--------|---------|----------|--|
| S1 | Create/edit/submit after the deadline | Enforced in the service layer (`403`), independent of the UI | `test_fixture_event_deadline_rejects_participant_submit`; the official checker (check 3) | ✅ |
| S2 | Edit or submit another team's project | Only the team **leader** can create/patch/submit (`403`); drafts are visible to team members only (`404` otherwise) | `test_submissions.py`, `live_lifecycle.py` | ✅ |
| S3 | Read drafts / draft events | Drafts never appear in the gallery, embed, ballot or webhooks; **draft events** are hidden from everyone but their organizers, including their tracks, rubric and gallery (`404`) | `test_draft_events_are_invisible_to_anonymous_visitors`, `…_to_signed_in_strangers…` | ✅ (found in §5) |
| S4 | Oversized / abusive content (DoS, DB bloat) | Every field bounded (255 / 500 / 50 000 chars, ≤ 20 images, ≤ 30 tags, ≤ 20 KB custom answers); 2 MB body cap; NUL bytes rejected | `test_hardening.py` | ✅ |
| S5 | Plagiarism / duplicate entries | None (a team may hold several submissions, which the official data requires) | — | ⚠️ R15 |
| S6 | Private data in `custom_answers` | These answers are **shown publicly on the project page by design**; the embed omits them | UI + `test_json_gallery_is_cors_open_cacheable_and_public_safe` | 🟡 don't ask for private information in organizer questions |

### 4.4 Judging integrity (A1) — details in `JUDGING.md`

| ID | Threat | Control | Evidence | |
|----|--------|---------|----------|--|
| J1 | A judge reads peers' scores | `/scores` is organizer-only; `/scores/mine` returns only the caller's rows | `test_peer_scores_are_isolated`, the official checker (check 5) | ✅ |
| J2 | Role confusion across events | Roles are checked against the event that **owns** the submission | `test_roles_are_scoped_to_the_submissions_event` | ✅ |
| J3 | Judge scores an unassigned project / their own team's | Only assigned judges can score; assignment never pairs a judge with their own team | `test_judging_assignment.py` | ✅ |
| J4 | Out-of-range or unknown-criterion scores | `400` unless the criterion belongs to the event and the value is inside its scale | `test_score_must_be_within_criterion_scale` | ✅ |
| J5 | **Change scores after results are published** | Scoring is refused (`403`) once the event is closed and outside `judging_opens_at..judging_closes_at` | `test_scores_cannot_change_after_results_are_published`, `test_judging_window_dates_are_enforced_by_the_api` | ✅ (found in §5) |
| J6 | Delete a criterion to erase judgments | A criterion with scores cannot be deleted (`409`; was a `500`) | `test_a_criterion_with_scores_cannot_be_deleted` | ✅ (found in §5) |
| J7 | Rewrite scores silently, then erase the evidence | Every create/update writes an audit row with the old and new value in the same transaction (import overwrites too); the audit log itself is **hash-chained** (each row hashes its own fields plus the previous row's hash), so editing or deleting a past row breaks the chain from that point on - `GET /admin/audit/verify` (any organizer, not just admins) and the offline `verify_audit_chain.py` both recompute it independently | `test_score_role_and_assignment_writes_are_audited`, `test_dump.py`, `test_audit_chain.py` | ✅ (see R4) |
| J8 | Lenient / harsh judges, flat judges | Per-judge z-score normalization; zero-variance and single-review judges fall back to the pooled scale and are flagged and audit-logged | `test_normalization.py`, `test_real_fixtures.py` | ✅ |
| J9 | Judges collude / inflate together | Normalization damps individual leniency, **not** collusion | — | ⚠️ R14 |
| J10 | A judge's scores are altered (by anyone, including a bug) and they have no way to prove what they actually submitted | `GET /events/{id}/judging/attestation`: a judge can, at any time, get an Ed25519-signed document of their own current scores - carries the real per-criterion values, unlike the `judge` certificate. Not stored (a stale cached copy would misrepresent itself as current), so it is never reachable via the public `GET /verify/{code}`; only whoever holds the document can check it (`POST /verify`, the offline verifier) | `test_score_attestation.py` | ✅ |

### 4.5 Identity, access and secrets (A4, A5)

| ID | Threat | Control | Evidence | |
|----|--------|---------|----------|--|
| A1 | Brute-force / credential stuffing | Failed sign-ins are throttled per (IP + email) (10 / 5 min) and per IP (50 / 5 min) with `429` + `Retry-After`; successes are never counted; bcrypt hashing; passwords ≥ 8 chars (was: empty allowed) | `test_repeated_failed_logins_are_throttled_but_successes_never_are`, `test_new_passwords_must_be_at_least_8_characters…`, probe | 🟡 distributed guessing, no MFA |
| A2 | Discover which emails have accounts | Login gives the *same* response for unknown user and wrong password, and is throttled the same way | probe (`login leaks…` check), `test_repeated_failed_logins…` (ghost account) | 🟡 signup necessarily reveals a taken email |
| A3 | **Organizer becomes site admin** | Only an existing admin can grant `admin` (`403`); a dump import cannot mint admins (skipped with a warning) | `test_an_organizer_cannot_make_themselves_or_anyone_admin`, `test_importing_a_dump_cannot_mint_admins_either` | ✅ (found in §5) |
| A4 | **Organizer reads other events' audit trail** | `/admin/audit` is scoped to the caller's own events (`403` for anyone else's); only admins see all | `test_an_organizer_only_sees_the_audit_trail_of_their_own_events` | ✅ (found in §5) |
| A5 | Access other users' objects (IDOR) | Webhooks: someone else's is a `404`; certificates: self or organizer; teams: members only; exports/imports/roles: that event's organizer; every check is server-side and tested with a second user | `test_webhooks_are_private_to_their_owner`, `test_access_control` (certificates), `test_permissions` (dump) | ✅ |
| A6 | Forged JWTs | HS256 with a server secret, `sub` looked up in the DB each request; no role claims are trusted | `test_auth.py` | ⚠️ R6: the demo secret is public |
| A7 | Stolen token | 24 h expiry | — | ⚠️ R5: token in `localStorage`, no server-side revocation |

### 4.6 Platform and API abuse (A8, A9, A6, A7)

| ID | Threat | Control | Evidence | |
|----|--------|---------|----------|--|
| P1 | SQL injection | SQLAlchemy parameterization everywhere; `LIKE` patterns are bound parameters | the probe's injection payloads (SQL fragments, wildcards, template and path-traversal strings in search, tag, audit filters, ids and login) all returned controlled 4xx | ✅ |
| P2 | Hostile input becomes a 500 (NUL bytes, over-long text, offset overflow) | Request guard (NUL anywhere → `422`), bounded schemas, pagination ceilings (`page ≤ 100 000`), strict `verify` codes | `test_hardening.py`; probe (was 22 failures) | ✅ (found in §5) |
| P3 | Huge bodies / parsing bombs | 2 MB cap (50 MB only for imports, ≤ 200 000 rows), counted while streaming, `413` before the app buffers it; deep-nesting JSON is a clean `4xx` | `test_request_bodies_are_capped_but_imports_may_be_large`, probe | 🟡 no global request rate limit (R11) |
| P4 | Slow reads at scale | Explicit column loading, `COUNT`, batched lookups; all read endpoints < 100 ms with the 40-project data | `test_real_scale_endpoints_stay_fast` | ✅ |
| P5 | **SSRF via webhooks** | http(s) only, no credentials in URLs, **no redirects**, cloud-metadata/link-local always refused, private networks refused by default; the host is resolved and every address re-checked **when subscribing and again right before each send** | `test_dangerous_or_malformed_urls_are_refused`, `test_hostnames_that_resolve_to_internal_addresses_are_refused`, `test_targets_are_rechecked_right_before_sending`, `test_timeouts_and_redirects_are_failures_not_followed`, `live_webhooks.py` | 🟡 residual DNS-rebinding window between check and connect (R10) |
| P6 | Forged or replayed webhook deliveries | HMAC-SHA256 over `timestamp.body`, per-endpoint secret shown once, stable delivery id, 5-minute replay window in the reference verifier | `test_signature_helpers_reject_tampering_replays_and_wrong_keys` | ✅ |
| P7 | Forged certificates | Ed25519 over canonical JSON; the record is re-verified on lookup; a public key is published; offline verifier uses only the standard library | `test_certificates.py` (14), incl. tampering and wrong keys | ⚠️ R12: key custody/revocation |
| P8 | Malicious import file | Validated first, transactional, size and row caps, cross-event id clash → `409`, roles/URLs re-validated, audit history tagged `imported` | `test_dump.py` (13), `test_security_fixes.py` | 🟡 the checksum detects accidents, **not** tampering (R9) |
| P9 | Embed abuse (clickjacking, XSS, data exposure) | The widget is meant to be framed (`frame-ancestors *`) but exposes only public gallery fields, escapes everything, CSP `default-src 'none'`; the **app itself** is not frameable (`X-Frame-Options: SAMEORIGIN`) | `test_embed.py`, `e2e-embed.py` (cross-origin browser test) | ✅ |
| P10 | CORS misuse | Credentialed CORS only for the configured origins; `/embed*` answers `*` **without** credentials | `test_preflight`, `e2e-embed.py` | ✅ |
| P11 | MIME sniffing / referrer leaks | `X-Content-Type-Options: nosniff` and `Referrer-Policy` on every API response and on the web app | `test_every_api_response_carries_basic_security_headers` | ✅ |
| P12 | Secrets in the repository | The demo `JWT_SECRET_KEY` and the long-lived checker tokens are public **by design** (grading); the API logs a loud warning at boot when the secret is a published one | boot log; ARCHITECTURE.md | ⚠️ R6 |
| P13 | Vulnerable / hosted-elsewhere assets | Swagger UI is vendored (no CDN); no third-party requests at runtime (28 page loads, 0 external requests); Python deps pinned, frontend lockfile committed | offline browser test; `test_docs_page_is_self_hosted…` | 🟡 supply chain of the images themselves |

---

## 5. What adversarial testing found and fixed

Probing the running system (rather than reading it) found these. Each was exploitable; each now has a regression test.

| # | Finding | Severity | Fix | Regression test |
|---|---------|----------|-----|-----------------|
| 1 | **Anonymous visitors could list and read every *draft* event**, including its tracks, rubric and gallery (the "hide drafts" filter was skipped when nobody was signed in) | High (disclosure) | Explicit public-view filter for list/detail; shared `hide_draft_event` guard on the sub-resources | `test_draft_events_are_invisible_to_anonymous_visitors` |
| 2 | **An organizer could grant themselves `admin`** and thereby become a site-wide admin (every permission check accepts `admin` from any event) | Critical (escalation) | Only an admin may grant `admin`; imports skip admin roles for non-admins | `test_an_organizer_cannot_make_themselves_or_anyone_admin` |
| 3 | **Any organizer could read every other event's audit log** (98 of the first 100 rows returned belonged to other events; the log holds IPs and actions) | High (disclosure) | Audit view scoped to the caller's own events; `403` for others; admins see all | `test_an_organizer_only_sees_the_audit_trail_of_their_own_events` |
| 4 | **Judges could change scores after results were published** (no judging-window enforcement in the API) | High (integrity) | `403` once the event is closed and outside the judging dates | `test_scores_cannot_change_after_results_are_published` |
| 5 | Deleting a criterion that had scores returned a `500` (and was one step from destroying judgments) | Medium | `409`: judgments are never deleted | `test_a_criterion_with_scores_cannot_be_deleted` |
| 6 | `javascript:` / `data:` URLs accepted in project links and rendered as clickable links | Medium (XSS vector) | http(s)-only validation on write and import; `safeHref` in the UI | `test_project_links_must_be_http_or_https` |
| 7 | Login and signup unthrottled: unlimited password guesses and account creation (and, once added, the first Redis limiter used a fixed window that a burst could straddle to get 2× the limit) | High | Failure-only login throttle (per IP+email, per IP), signup throttle, sliding-window limiter in both Redis and memory | `test_repeated_failed_logins_are_throttled…` |
| 8 | Empty (or 1-character) passwords accepted at signup | Medium | Minimum 8 characters (UI hint updated) | `test_new_passwords_must_be_at_least_8_characters…` |
| 9 | NUL bytes and over-long text in ~20 fields returned `500`; a page number of 10¹⁸ overflowed the database; `/verify/%00` returned `500` | Medium (availability, noise) | Request guard, bounded schemas, pagination ceilings, strict `verify` codes | `test_hardening.py` (21 tests) |
| 10 | `plus`-addressed emails counted as new voters in `email` mode | Medium (vote integrity) | Canonical mailbox identity | `test_plus_addressing_cannot_mint_extra_votes` |
| 11 | Cross-origin CORS preflight to the embed API was rejected by the global CORS policy (`400`) | Low (functional) | Dedicated middleware answering `/embed*` for any origin, without credentials | `test_preflight`, `e2e-embed.py` |
| 12 | Gallery took 13 s and `/roles` 18 s with the real 40-project data (every relationship eager-loaded): a self-inflicted denial of service | Medium (availability) | `lazy="raise"` everywhere; explicit queries | `test_real_scale_endpoints_stay_fast` |

Two of my own fixes briefly shipped with bugs, and the tests caught both within minutes (a missing import that made every role grant `500`, and an
infinite recursion in the security-header wrapper that broke the dev API until it was fixed). They are listed here because *the test suite is part of
the control*: it is what catches a security fix that breaks something else.

## 6. Residual risks (known, and accepted or open)

Ordered roughly by how much they matter for a real deployment.

| ID | Risk | Why it remains | Mitigation for operators |
|----|------|----------------|--------------------------|
| **R1** | **Sybil / botnet voting.** With enough IPs (open mode) or accounts (auth/quadratic), votes can be inflated; open signup is not proof of unique personhood, and quadratic voting assumes it | Unique-person proof needs a trusted identity source, outside this platform's scope | Use `email`/`auth` for anything that matters; keep the public tally hidden until close (default); compare vote timing/volume in the audit log; treat crowd votes as advisory, judges' ranking as authoritative |
| **R2** | **`X-Forwarded-For` spoofing.** `TRUST_PROXY_HEADERS` defaults to on because the web proxy fronts the API; if `:8000` is reachable directly, a client can pick its own "IP" and dodge per-IP limits | Docker Desktop cannot distinguish the proxy from any other client | Do not publish `:8000` in production (the compose file publishes it for the grading checker), or set `TRUST_PROXY_HEADERS=false` |
| **R3** | **`email` mode is not verified.** Anyone can type any address (also someone else's, "burning" their vote) | There is no mail server in an offline-first stack | Document it as "email-gated"; use `auth` where identity matters |
| **R4** | **A malicious organizer / DB operator** can still alter their event's underlying data directly (import, direct SQL) without the application ever knowing an edit happened - hash-chaining the *audit log* does not, and cannot, protect data the application was never told to log. What it does cover: the log itself can no longer be silently rewritten. Every row hashes its own fields plus the previous row's hash (`app/models/audit.py`, `audit_service.append_to_chain`); editing, reordering or deleting any past row breaks every hash after it. `GET /admin/audit/verify` and `backend/scripts/verify_audit_chain.py` both recompute the whole chain independently and report only the first broken row's `seq`/`id`, never its content, so any organizer can check platform-wide integrity without seeing another event's data | Organizers own their event's *data* by design; the log's own integrity no longer depends on that trust | Ship the audit log off-box for an external record a compromised DB can't touch retroactively; run `verify_audit_chain.py` on a schedule |
| **R5** | **Session model:** JWT in `localStorage` (readable by any XSS), 24 h expiry, no server-side revocation or logout | Stateless tokens keep the stack simple | Keep CSP/XSS discipline (escaping is the control today); short expiry; rotate `JWT_SECRET_KEY` to revoke everything |
| **R6** | **Public demo secrets.** The default `JWT_SECRET_KEY` is in the repository, so anyone can mint tokens, including the deliberately long-lived (year 2100) checker tokens | Needed so `docker compose up` works and the checker's tokens are reproducible | **Set your own secret before exposing this** (the API warns at boot); changing it invalidates every token and certificate key |
| **R7** | **Pseudonymous, not anonymous, voters.** `ip_hash` and email fingerprints are unsalted SHA-256: anyone with database access can *confirm a guess* | A keyed hash would tie restored dumps to one secret | Treat the DB as sensitive; a keyed HMAC is a small change if needed |
| **R8** | **No comment moderation.** Anonymous, unverified comments; organizers cannot delete one | Out of scope for the tier | Reverse proxy filtering, or add a delete endpoint |
| **R9** | **Dump checksum is integrity, not authenticity.** Anyone can edit a dump and recompute the checksum | Authenticity would need signed exports | Trust rests on the importing organizer's role; imports are audit-logged; restored history is tagged |
| **R10** | **DNS rebinding window.** Webhook targets are re-resolved and checked immediately before sending, but the HTTP client resolves again to connect | Pinning the connection to the checked address needs a custom transport | Keep private-network targets disabled (default) and egress-filter the API container |
| **R11** | **No global request rate limit.** Only votes, comments, sign-in, sign-up and verification are throttled; authenticated writes rely on quotas and size caps | A proxy does this better | Put nginx/Traefik/a WAF in front |
| **R12** | **Certificate key custody and revocation.** The signing key derives from a server secret; a stolen secret forges certificates; there is no revocation list; PDF names outside the vendored font's coverage (CJK) still degrade to `?` | Keeps offline setup trivial | Set `CERT_SIGNING_KEY` separately and guard it; publish the key id; regenerate on suspicion |
| **R13** | **Multi-process limits.** Without Redis the rate limiter is per process; the webhook worker is safe to run in several processes (leases), the limiter fallback is not | Single container by default | Keep Redis in production |
| **R14** | **Judge collusion.** Normalization removes leniency, not coordinated inflation | Not detectable from scores alone | Review assignment patterns and the audit log; more judges per project |
| **R15** | **No plagiarism / duplicate detection**; a team may hold several projects | The official data requires it | Organizer review |
| **R16** | **Time is the server clock** (deadlines, windows, token expiry, signature replay window) | Standard | Run NTP |
| **R17** | The **web app sets no CSP** for its own pages (React escaping is the XSS control; the embed page does have one) | Next.js inline scripts make a strict CSP a project of its own | Add a nonce-based CSP if the threat model grows |
| **R18** | Fixture teams' invite codes derive from their public ids | Deterministic seeding | Irrelevant once team formation has closed; generate random codes for real events (the API already does) |

## 7. Operator checklist before going live

1. Set `JWT_SECRET_KEY` (and `CERT_SIGNING_KEY`); the API warns at boot while a published secret is in use. Re-mint the checker tokens or stop using them.
2. Put TLS and a reverse proxy in front; **do not publish port 8000**; keep `WEBHOOK_ALLOW_PRIVATE_TARGETS` **off**.
3. Keep Redis running (shared rate limits). Back up PostgreSQL, plus periodic event **exports** (`POST /events/{id}/export`) as portable backups.
4. Choose the voting mode deliberately (R1, R3) and keep the tally hidden until close.
5. Restrict who gets the organizer role; only admins can create admins; review `GET /admin/audit` (`?format=text`).
6. Ship the audit log off-box if organizers are not fully trusted (R4).

## 8. Re-running the evidence

```bash
docker compose up -d
python backend/scripts/probe_abuse.py                      # 96 hostile-input probes + 16 authorization exploits against the running API: expects "clean"
docker compose --profile test run --rm pytest              # incl. test_hardening.py, test_security_fixes.py, test_webhooks.py, ...
python backend/scripts/live_t3.py                          # voting abuse through the real proxy (dedup, 429, hiding, ballot, quadratic)
python backend/scripts/live_webhooks.py                    # a real receiver: signatures, retries, SSRF refusals
python backend/scripts/verify_audit_chain.py                # recomputes the audit log's hash chain independently: expects "OK"
python frontend/e2e-embed.py                               # third-party origin, real browser
```
