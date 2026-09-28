"""Hostile-input and abuse regressions found by `scripts/probe_abuse.py` (each was a 500 or a missing limit)."""

import json

import pytest

from app.config import settings
from app.models.event import EventStatus
from app.services.voting_service import canonical_email
from tests.conftest import get_auth_header

NUL = "bad\x00byte"


# ---------------------------------------------------------------- NUL characters (Postgres cannot store them)

@pytest.mark.asyncio
async def test_nul_characters_are_a_clean_422_everywhere(client, test_organizer, test_user, test_team, test_submission, test_event):
    org, lead = get_auth_header(test_organizer), get_auth_header(test_user)
    cases = [
        ("POST", "/auth/signup", {"email": "n@x.io", "name": NUL, "password": "pw123456"}, {}),
        ("POST", "/events", {"name": NUL}, org),
        ("POST", "/events", {"name": "ok", "slug": NUL}, org),
        ("POST", f"/submissions/{test_submission.id}/comments", {"body": NUL}, {}),
        ("PATCH", f"/submissions/{test_submission.id}", {"tagline": NUL}, lead),
        ("POST", f"/events/{test_event.id}/teams", {"name": NUL}, lead),
    ]
    for method, path, body, headers in cases:
        r = await client.request(method, path, json=body, headers=headers)
        assert r.status_code == 422 and "NUL" in r.json()["detail"], (path, r.status_code, r.text[:120])
    # the escaped JSON form (\u0000) is the same attack
    raw = b'{"body": "x\\u0000y"}'
    r = await client.post(f"/submissions/{test_submission.id}/comments", content=raw, headers={"content-type": "application/json"})
    assert r.status_code == 422
    # ... and so is %00 in the URL (path or query)
    assert (await client.get("/verify/%00")).status_code == 422
    assert (await client.get(f"/events/{test_event.id}/submissions", params={"search": NUL})).status_code == 422
    # ordinary requests are untouched
    ok = await client.post(f"/submissions/{test_submission.id}/comments", json={"body": "fine ❤ unicode is welcome"})
    assert ok.status_code == 201


# ---------------------------------------------------------------- length limits

@pytest.mark.asyncio
@pytest.mark.parametrize("field,limit", [("name", 255), ("tagline", 500), ("thumbnail_url", 500), ("repo_url", 500), ("live_url", 500), ("demo_video_url", 500)])
async def test_submission_text_fields_have_exact_limits(client, test_user, test_submission, field, limit):
    h = get_auth_header(test_user)
    make = (lambda n: "https://x.io/" + "a" * (n - 13)) if field.endswith("_url") else (lambda n: "a" * n)  # links must be valid URLs
    assert (await client.patch(f"/submissions/{test_submission.id}", json={field: make(limit)}, headers=h)).status_code == 200
    r = await client.patch(f"/submissions/{test_submission.id}", json={field: make(limit + 1)}, headers=h)
    assert r.status_code == 422 and "at most" in r.text


@pytest.mark.asyncio
async def test_collections_and_blobs_are_bounded(client, test_user, test_submission):
    h = get_auth_header(test_user)
    url = f"/submissions/{test_submission.id}"
    assert (await client.patch(url, json={"description_md": "x" * 50_000}, headers=h)).status_code == 200
    assert (await client.patch(url, json={"description_md": "x" * 50_001}, headers=h)).status_code == 422
    assert (await client.patch(url, json={"gallery_image_urls": ["http://i.io/1"] * 20}, headers=h)).status_code == 200
    assert (await client.patch(url, json={"gallery_image_urls": ["http://i.io/1"] * 21}, headers=h)).status_code == 422
    assert (await client.patch(url, json={"tech_tags": ["t"] * 30}, headers=h)).status_code == 200
    assert (await client.patch(url, json={"tech_tags": ["t"] * 31}, headers=h)).status_code == 422
    assert (await client.patch(url, json={"tech_tags": ["t" * 51]}, headers=h)).status_code == 422
    big = {str(i): "v" * 100 for i in range(300)}  # ~ 34 KB of JSON
    r = await client.patch(url, json={"custom_answers": big}, headers=h)
    assert r.status_code == 422 and "too large" in r.text


@pytest.mark.asyncio
async def test_account_event_team_and_comment_fields_are_bounded(client, test_organizer, test_user, test_event):
    org, lead = get_auth_header(test_organizer), get_auth_header(test_user)
    assert (await client.post("/auth/signup", json={"email": "a@x.io", "name": "n" * 256, "password": "pw123456"})).status_code == 422
    assert (await client.post("/auth/signup", json={"email": "a@x.io", "name": "n", "password": "p" * 129})).status_code == 422
    assert (await client.post("/auth/login", json={"email": "a@x.io", "password": "p" * 129})).status_code == 422
    assert (await client.post("/events", json={"name": "n" * 256}, headers=org)).status_code == 422
    assert (await client.post("/events", json={"name": "ok", "slug": "s" * 256}, headers=org)).status_code == 422
    assert (await client.post("/events", json={"name": "ok", "description": "d" * 20_001}, headers=org)).status_code == 422
    assert (await client.post(f"/events/{test_event.id}/tracks", json={"name": "t" * 256}, headers=org)).status_code == 422
    assert (await client.post(f"/events/{test_event.id}/rubric/criteria", json={"name": "c" * 256}, headers=org)).status_code == 422
    assert (await client.post(f"/events/{test_event.id}/teams", json={"name": "t" * 256}, headers=lead)).status_code == 422
    assert (await client.post("/webhooks/subscribe", json={"url": "https://x.example.com/" + "a" * 2000, "event_types": ["*"]}, headers=org)).status_code == 422
    assert (await client.post("/webhooks/subscribe", json={"url": "https://x.example.com", "event_types": ["*"] * 21}, headers=org)).status_code == 422


@pytest.mark.asyncio
async def test_comment_and_vote_inputs_are_bounded(client, test_submission, test_event, db_session):
    url = f"/submissions/{test_submission.id}/comments"
    assert (await client.post(url, json={"body": "x", "author_name": "a" * 101})).status_code == 422
    assert (await client.post(url, json={"body": "x" * 5001})).status_code == 422
    test_event.status = EventStatus.VOTING
    test_event.voting_mode = "email"
    await db_session.commit()
    v = f"/submissions/{test_submission.id}/vote"
    assert (await client.post(v, json={"email": "a" * 300 + "@x.io"})).status_code == 422
    assert (await client.post(v, json={"fingerprint": "f" * 201})).status_code == 422
    assert (await client.post(v, json={"votes": -1})).status_code == 422


@pytest.mark.asyncio
async def test_pagination_cannot_overflow_the_database(client, test_event, test_submission, test_organizer):
    for path in (f"/events/{test_event.id}/submissions", f"/submissions/{test_submission.id}/comments", f"/embed/{test_event.id}/gallery"):
        assert (await client.get(path, params={"page": 10**18})).status_code == 422
        assert (await client.get(path, params={"page": 100_001})).status_code == 422
        assert (await client.get(path, params={"page": 100_000})).status_code == 200
    assert (await client.get("/admin/audit", params={"page": 10**18}, headers=get_auth_header(test_organizer))).status_code == 422


@pytest.mark.asyncio
async def test_verify_code_must_look_like_a_hash(client):
    assert (await client.get("/verify/" + "0" * 65)).status_code == 422
    assert (await client.get("/verify/not-hex!")).status_code == 422
    assert (await client.get("/verify/" + "A" * 64)).status_code == 404  # well-formed, unknown, case-insensitive


# ---------------------------------------------------------------- body size caps

@pytest.mark.asyncio
async def test_request_bodies_are_capped_but_imports_may_be_large(client, test_organizer, test_event):
    big = b'{"email":"a@x.io","password":"' + b"p" * (3 * 1024 * 1024) + b'"}'
    r = await client.post("/auth/login", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413 and "too large" in r.json()["detail"]
    # an import may be far larger than an ordinary body (up to 50 MB): a 3 MB upload must get past the guard
    r = await client.post(f"/events/{test_event.id}/import", content=big, headers={"content-type": "application/json", **get_auth_header(test_organizer)})
    assert r.status_code != 413
    r = await client.post("/auth/login", content=b"{}", headers={"content-type": "application/json", "content-length": "abc"})
    assert r.status_code == 400


# ---------------------------------------------------------------- brute force / floods

@pytest.mark.asyncio
async def test_repeated_failed_logins_are_throttled_but_successes_never_are(client, test_user):
    bad = {"email": test_user.email, "password": "wrong-password"}
    codes = [(await client.post("/auth/login", json=bad)).status_code for _ in range(settings.LOGIN_MAX_FAILURES + 2)]
    assert codes[: settings.LOGIN_MAX_FAILURES] == [401] * settings.LOGIN_MAX_FAILURES and codes[-1] == 429
    r = await client.post("/auth/login", json=bad)
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    # the lock is per (IP, email): a different account from the same address is not locked out
    other = await client.post("/auth/signup", json={"email": "other@x.io", "name": "o", "password": "pw123456"})
    assert other.status_code == 201
    assert (await client.post("/auth/login", json={"email": "other@x.io", "password": "pw123456"})).status_code == 200
    # unknown accounts are throttled exactly the same (no oracle for which emails exist)
    ghost = {"email": "ghost@x.io", "password": "x"}
    ghost_codes = [(await client.post("/auth/login", json=ghost)).status_code for _ in range(settings.LOGIN_MAX_FAILURES + 1)]
    assert ghost_codes[-1] == 429


@pytest.mark.asyncio
async def test_successful_logins_do_not_count_toward_the_limit(client, test_user):
    for _ in range(settings.LOGIN_MAX_FAILURES * 3):
        r = await client.post("/auth/login", json={"email": test_user.email, "password": "testpassword123"})
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_spraying_many_emails_from_one_ip_is_throttled_per_ip(client, monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_MAX_FAILURES_PER_IP", 5)
    codes = [(await client.post("/auth/login", json={"email": f"user{i}@x.io", "password": "guess"})).status_code for i in range(8)]
    assert codes[:5] == [401] * 5 and set(codes[5:]) == {429}


@pytest.mark.asyncio
async def test_signup_flood_is_throttled(client, monkeypatch):
    monkeypatch.setattr(settings, "RATE_LIMIT_SIGNUPS_PER_MINUTE", 3)
    codes = [(await client.post("/auth/signup", json={"email": f"s{i}@x.io", "name": "s", "password": "pw123456"})).status_code for i in range(5)]
    assert codes == [201, 201, 201, 429, 429]


# ---------------------------------------------------------------- one mailbox = one voter

def test_email_aliases_collapse_to_one_identity():
    assert canonical_email("Ada@Example.org") == canonical_email("ada+vote2@example.org") == canonical_email(" ada+x+y@EXAMPLE.ORG ")
    assert canonical_email("a.b.c@gmail.com") == canonical_email("abc+1@googlemail.com") == "abc@gmail.com"
    assert canonical_email("a.b@example.org") != canonical_email("ab@example.org")  # dots only collapse for Gmail
    assert canonical_email("ada@example.org") != canonical_email("bob@example.org")


@pytest.mark.asyncio
async def test_plus_addressing_cannot_mint_extra_votes(client, db_session, test_event, test_submission):
    from httpx import ASGITransport, AsyncClient

    from app.main import app

    test_event.status = EventStatus.VOTING
    test_event.voting_mode = "email"
    await db_session.commit()
    url = f"/submissions/{test_submission.id}/vote"
    assert (await client.post(url, json={"email": "ada@example.org"})).status_code == 201
    for alias in ("ada+2@example.org", "ADA+x@Example.org"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as other:
            r = await other.post(url, json={"email": alias})
        assert r.status_code == 400, alias  # the same mailbox has already voted


@pytest.mark.asyncio
async def test_new_passwords_must_be_at_least_8_characters_but_login_guesses_are_just_401(client):
    for pw in ("", "a", "1234567"):
        r = await client.post("/auth/signup", json={"email": "pw@x.io", "name": "n", "password": pw})
        assert r.status_code == 422 and "at least 8" in r.text, pw
    assert (await client.post("/auth/signup", json={"email": "pw@x.io", "name": "n", "password": "12345678"})).status_code == 201
    r = await client.post("/auth/login", json={"email": "pw@x.io", "password": "x"})
    assert r.status_code == 401  # a short guess is a failed login, not a validation error


# ---------------------------------------------------------------- the Redis limiter is a true sliding window

@pytest.mark.asyncio
async def test_redis_limiter_is_a_sliding_window_not_a_fixed_one(monkeypatch):
    """A fixed window lets a burst straddle the boundary and get 2x the limit; the sliding window must not."""
    import fakeredis.aioredis

    from app.utils import rate_limit as rl

    fake = fakeredis.aioredis.FakeRedis()
    monkeypatch.setattr(rl, "_get_redis", lambda: fake)
    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(rl.time, "time", lambda: clock["t"])

    clock["t"] += 59.5  # just before a fixed-window boundary
    first = [await rl.hit("k", 5, 60) for _ in range(5)]
    assert all(ok for ok, _ in first)
    clock["t"] += 1.0   # 60.5 s: a fixed window would have reset here
    burst = [await rl.hit("k", 5, 60) for _ in range(5)]
    assert not any(ok for ok, _ in burst), "the boundary must not reset the budget"
    ok, retry = await rl.hit("k", 5, 60)
    assert not ok and 1 <= retry <= 60
    clock["t"] += 60.0  # the original five have now aged out
    assert (await rl.hit("k", 5, 60))[0] is True
    # rejected attempts do not extend the window, and peek() never counts
    assert (await rl.peek("other", 2, 60))[0] is False
    await rl.hit("other", 2, 60); await rl.hit("other", 2, 60)
    assert (await rl.peek("other", 2, 60))[0] is True
    await fake.aclose()
