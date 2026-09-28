"""End-to-end API test script against running Docker container.

Run: python tests/test_e2e_api.py
Requires: docker compose up -d (API on localhost:8000)

Uses seeded data:
- admin@dogfoodhack.com / admin123
- organizer@dogfoodhack.com / organizer123
- judge1@dogfoodhack.com / judge123
- judge2@dogfoodhack.com / judge123
- participant1@dogfoodhack.com / participant123
"""

import httpx
import sys
import uuid as uuidlib

BASE = "http://localhost:8000"
passed = 0
failed = 0
errors = []


def check(label, resp, expected_status=None):
    global passed, failed
    if expected_status and resp.status_code != expected_status:
        failed += 1
        errors.append(f"  FAIL: {label} — expected {expected_status}, got {resp.status_code}: {resp.text[:200]}")
        print(f"  FAIL: {label} — expected {expected_status}, got {resp.status_code}")
        return False
    passed += 1
    print(f"  PASS: {label} — {resp.status_code}")
    return True


def get_headers(c, email, password):
    """Login and return auth headers."""
    r = c.post("/auth/login", json={"email": email, "password": password})
    if r.status_code != 200:
        return None
    return {"Authorization": f"Bearer {r.json()['token']}"}


def main():
    global passed, failed

    c = httpx.Client(base_url=BASE, timeout=15)

    print("\n" + "=" * 60)
    print("DOGFOOD API — End-to-End Endpoint Test (seeded data)")
    print("=" * 60)

    # ─── 1. HEALTH ───────────────────────────────────────────
    print("\n[1] Health")
    check("GET /health", c.get("/health"), 200)

    # ─── 2. AUTH — Login as seeded users ─────────────────────
    print("\n[2] Auth — Login as seeded users")
    admin_headers = get_headers(c, "admin@dogfoodhack.com", "admin123")
    check("Admin login", httpx.Response(200 if admin_headers else 401, request=httpx.Request("POST", "")), 200)

    org_headers = get_headers(c, "organizer@dogfoodhack.com", "organizer123")
    check("Organizer login", httpx.Response(200 if org_headers else 401, request=httpx.Request("POST", "")), 200)

    judge1_headers = get_headers(c, "judge1@dogfoodhack.com", "judge123")
    check("Judge1 login", httpx.Response(200 if judge1_headers else 401, request=httpx.Request("POST", "")), 200)

    judge2_headers = get_headers(c, "judge2@dogfoodhack.com", "judge123")
    check("Judge2 login", httpx.Response(200 if judge2_headers else 401, request=httpx.Request("POST", "")), 200)

    part_headers = get_headers(c, "participant1@dogfoodhack.com", "participant123")
    check("Participant1 login", httpx.Response(200 if part_headers else 401, request=httpx.Request("POST", "")), 200)

    # Test /auth/me for each
    r = c.get("/auth/me", headers=org_headers)
    check("GET /auth/me (organizer)", r, 200)
    org_user_id = r.json()["id"]

    r = c.get("/auth/me", headers=judge1_headers)
    check("GET /auth/me (judge1)", r, 200)
    judge1_user_id = r.json()["id"]

    r = c.get("/auth/me", headers=part_headers)
    check("GET /auth/me (participant)", r, 200)
    part_user_id = r.json()["id"]

    r = c.get("/auth/me", headers=admin_headers)
    check("GET /auth/me (admin)", r, 200)

    # ─── 3. EVENTS — Get seeded event ────────────────────────
    print("\n[3] Events — List & Detail (seeded)")
    r = c.get("/events")
    check("GET /events (public)", r, 200)
    events = r.json()
    assert len(events) >= 1, "No events found"
    event_id = events[0]["id"]
    print(f"  Using seeded event: {events[0]['name']} ({event_id})")

    r = c.get(f"/events/{event_id}")
    check(f"GET /events/{event_id} (public)", r, 200)

    r = c.get("/events/00000000-0000-0000-0000-000000000000")
    check("GET /events/{nonexistent}", r, 404)

    # ─── 4. EVENT ROLES ──────────────────────────────────────
    print("\n[4] Event Roles")
    r = c.get(f"/events/{event_id}/roles", headers=org_headers)
    check("GET /events/{event_id}/roles (organizer)", r, 200)
    roles = r.json()
    print(f"  Found {len(roles)} existing roles")

    # ─── 5. TRACKS ───────────────────────────────────────────
    print("\n[5] Tracks")
    r = c.get(f"/events/{event_id}/tracks")
    check("GET /events/{event_id}/tracks (public)", r, 200)
    tracks = r.json()
    assert len(tracks) >= 1, "No tracks found"
    track_id = tracks[0]["id"]
    track_ids = {t["name"]: t["id"] for t in tracks}
    print(f"  Tracks: {list(track_ids.keys())}")

    # Create new track (organizer only)
    r = c.post(f"/events/{event_id}/tracks", json={
        "name": "E2E Test Track",
        "description": "Created during E2E test",
    }, headers=org_headers)
    check("POST /events/{event_id}/tracks (organizer)", r, 201)
    new_track_id = r.json()["id"]

    # Participant cannot create track
    r = c.post(f"/events/{event_id}/tracks", json={
        "name": "Unauthorized Track",
    }, headers=part_headers)
    check("POST /events/{event_id}/tracks (participant — 403)", r, 403)

    # ─── 6. TEAMS ────────────────────────────────────────────
    print("\n[6] Teams")
    r = c.get(f"/events/{event_id}/teams/mine", headers=part_headers)
    check("GET /events/{event_id}/teams/mine (participant)", r, 200)
    my_teams = r.json()
    if my_teams:
        team_id = my_teams[0]["id"]
        print(f"  Using existing team: {my_teams[0]['name']} ({team_id})")
    else:
        # Create a team if participant has none
        r = c.post(f"/events/{event_id}/teams", json={
            "name": "E2E Test Team",
        }, headers=part_headers)
        check("POST /events/{event_id}/teams (create)", r, 201)
        team_id = r.json()["id"]

    r = c.get(f"/teams/{team_id}", headers=part_headers)
    check("GET /teams/{team_id} (member)", r, 200)

    # ─── 7. SUBMISSIONS ──────────────────────────────────────
    print("\n[7] Submissions")
    r = c.get(f"/events/{event_id}/submissions")
    check("GET /events/{event_id}/submissions (gallery)", r, 200)
    submissions = r.json()
    team_subs = [s for s in submissions if s.get("team_id") == team_id]
    if team_subs:
        submission_id = team_subs[0]["id"]
        print(f"  Using team's submission: {team_subs[0]['name']} ({submission_id})")
    elif submissions:
        submission_id = submissions[0]["id"]
        print(f"  Using existing submission: {submissions[0]['name']} ({submission_id})")
    else:
        # Create submission
        r = c.post(f"/teams/{team_id}/submissions", json={
            "name": "E2E Test Submission",
            "tagline": "Created during E2E test",
            "track_id": track_id,
        }, headers=part_headers)
        check("POST /teams/{team_id}/submissions (create)", r, 201)
        submission_id = r.json()["id"]

    r = c.get(f"/submissions/{submission_id}")
    check("GET /submissions/{submission_id}", r, 200)

    r = c.patch(f"/submissions/{submission_id}", json={
        "tagline": "Updated by E2E test",
    }, headers=part_headers)
    check("PATCH /submissions/{submission_id} (update)", r, 200)

    # Test submit if draft
    sub_detail = c.get(f"/submissions/{submission_id}").json()
    if sub_detail.get("status") == "draft":
        r = c.post(f"/submissions/{submission_id}/submit", headers=part_headers)
        check("POST /submissions/{submission_id}/submit", r, 200)

    # ─── 8. RUBRIC CRITERIA ──────────────────────────────────
    print("\n[8] Rubric Criteria")
    r = c.get(f"/events/{event_id}/rubric/criteria")
    check("GET /events/{event_id}/rubric/criteria (public)", r, 200)
    criteria = r.json()
    if criteria:
        criterion1_id = criteria[0]["id"]
        criterion2_id = criteria[1]["id"] if len(criteria) > 1 else criteria[0]["id"]
        print(f"  Using existing criteria: {[c['name'] for c in criteria]}")
    else:
        # Create criteria
        r = c.post(f"/events/{event_id}/rubric/criteria", json={
            "name": "Innovation",
            "description": "How innovative?",
            "weight": 1.0,
            "scale_min": 1.0,
            "scale_max": 10.0,
        }, headers=org_headers)
        check("POST /events/{event_id}/rubric/criteria (create)", r, 201)
        criterion1_id = r.json()["id"]

        r = c.post(f"/events/{event_id}/rubric/criteria", json={
            "name": "Technical Excellence",
            "description": "Quality of implementation",
            "weight": 1.5,
            "scale_min": 1.0,
            "scale_max": 10.0,
        }, headers=org_headers)
        check("POST /events/{event_id}/rubric/criteria (create 2nd)", r, 201)
        criterion2_id = r.json()["id"]

    # ─── 9. JUDGE ASSIGNMENTS ────────────────────────────────
    print("\n[9] Judge Assignments")
    r = c.get(f"/events/{event_id}/judging/assignments/mine", headers=judge1_headers)
    check("GET /events/{event_id}/judging/assignments/mine (judge1)", r, 200)
    print(f"  Judge1 has {len(r.json())} assignments")

    r = c.get(f"/events/{event_id}/judging/assignments/mine", headers=judge2_headers)
    check("GET /events/{event_id}/judging/assignments/mine (judge2)", r, 200)

    r = c.get(f"/events/{event_id}/judging/progress", headers=org_headers)
    check("GET /events/{event_id}/judging/progress (organizer)", r, 200)
    prog = r.json()
    print(f"  Progress: {prog.get('completion_percentage', 0):.1f}% complete")

    # Create new assignments (organizer)
    r = c.post(f"/events/{event_id}/judging/assign", json={
        "reviews_per_submission": 2,
    }, headers=org_headers)
    check("POST /events/{event_id}/judging/assign (organizer)", r, 200)

    # Participant cannot see progress
    r = c.get(f"/events/{event_id}/judging/progress", headers=part_headers)
    check("GET /events/{event_id}/judging/progress (participant — 403)", r, 403)

    # ─── 10. SCORING ─────────────────────────────────────────
    print("\n[10] Scoring")
    # the seeded schedule opens judging in a few days and the API enforces it, so an organizer opens judging first
    from datetime import datetime, timedelta, timezone
    r = c.patch(f"/events/{event_id}", json={"status": "judging", "judging_opens_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()}, headers=org_headers)
    check("PATCH /events/{event_id} (organizer opens judging)", r, 200)
    # Judge1 scores
    r = c.post(f"/submissions/{submission_id}/scores", json={
        "scores": [
            {"criterion_id": criterion1_id, "raw_value": 8.5, "comment": "Great innovation"},
            {"criterion_id": criterion2_id, "raw_value": 7.0, "comment": "Solid implementation"},
        ]
    }, headers=judge1_headers)
    check("POST /submissions/{submission_id}/scores (judge1)", r, 200)

    # Judge2 scores
    r = c.post(f"/submissions/{submission_id}/scores", json={
        "scores": [
            {"criterion_id": criterion1_id, "raw_value": 9.0, "comment": "Excellent"},
            {"criterion_id": criterion2_id, "raw_value": 8.0, "comment": "Very good"},
        ]
    }, headers=judge2_headers)
    check("POST /submissions/{submission_id}/scores (judge2)", r, 200)

    r = c.get(f"/submissions/{submission_id}/scores/mine", headers=judge1_headers)
    check("GET /submissions/{submission_id}/scores/mine (judge1)", r, 200)

    r = c.get(f"/submissions/{submission_id}/scores", headers=org_headers)
    check("GET /submissions/{submission_id}/scores (organizer — all)", r, 200)

    # Participant cannot see scores
    r = c.get(f"/submissions/{submission_id}/scores", headers=part_headers)
    check("GET /submissions/{submission_id}/scores (participant — 403)", r, 403)

    # ─── 11. NORMALIZATION & RESULTS ─────────────────────────
    print("\n[11] Normalization & Results")
    r = c.post(f"/events/{event_id}/judging/normalize", headers=org_headers)
    check("POST /events/{event_id}/judging/normalize", r, 200)

    r = c.get(f"/events/{event_id}/judging/results", headers=org_headers)
    check("GET /events/{event_id}/judging/results", r, 200)
    results = r.json()
    print(f"  Results: {len(results)} submissions ranked")

    # ─── 12. VOTING ──────────────────────────────────────────
    print("\n[12] Voting")
    r = c.post(f"/submissions/{submission_id}/vote", headers={
        "User-Agent": "E2E-Test-Client/1.0",
    })
    if r.status_code == 201:
        passed += 1
        print("  PASS: POST /submissions/{submission_id}/vote — 201")
    elif r.status_code == 400 and "not started" in r.text:
        passed += 1
        print("  PASS: POST vote — 400 (voting window not open yet, correctly rejected)")
    else:
        check("POST /submissions/{submission_id}/vote", r, 201)

    r = c.get(f"/submissions/{submission_id}/votes/count")
    check("GET /submissions/{submission_id}/votes/count", r, 200)
    print(f"  Vote count: {r.json()['vote_count']}")

    # Duplicate vote should fail (or voting not started)
    r = c.post(f"/submissions/{submission_id}/vote", headers={
        "User-Agent": "E2E-Test-Client/1.0",
    })
    check("POST /submissions/{submission_id}/vote (duplicate or closed)", r, 400)

    # ─── 13. COMMENTS ────────────────────────────────────────
    print("\n[13] Comments")
    r = c.post(f"/submissions/{submission_id}/comments", json={
        "body": "E2E test comment!",
    }, headers=part_headers)
    check("POST /submissions/{submission_id}/comments (authed)", r, 201)

    r = c.post(f"/submissions/{submission_id}/comments", json={
        "body": "Anonymous E2E comment",
    })
    check("POST /submissions/{submission_id}/comments (anonymous)", r, 201)

    r = c.get(f"/submissions/{submission_id}/comments")
    check("GET /submissions/{submission_id}/comments", r, 200)

    # ─── 14. ADMIN ───────────────────────────────────────────
    print("\n[14] Admin")
    r = c.get("/admin/audit", headers=org_headers)
    check("GET /admin/audit (organizer)", r, 200)

    r = c.get("/admin/audit", headers=part_headers)
    check("GET /admin/audit (participant — 403)", r, 403)

    # ─── 15. AUTH — Signup & duplicate test ──────────────────
    print("\n[15] Auth — New signup & duplicate")
    unique_email = f"e2e-{uuidlib.uuid4().hex[:8]}@test.com"
    r = c.post("/auth/signup", json={
        "email": unique_email,
        "password": "testpass123",
        "name": "E2E New User",
    })
    check("POST /auth/signup (new user)", r, 201)
    new_token = r.json().get("token")
    new_headers = {"Authorization": f"Bearer {new_token}"}

    r = c.post("/auth/signup", json={
        "email": unique_email,
        "password": "testpass123",
        "name": "Duplicate",
    })
    check("POST /auth/signup (duplicate)", r, 400)

    # ─── 16. AUTH — Invalid login ────────────────────────────
    print("\n[16] Auth — Invalid login")
    r = c.post("/auth/login", json={
        "email": "organizer@dogfoodhack.com",
        "password": "wrongpass",
    })
    check("POST /auth/login (invalid password)", r, 401)

    r = c.get("/auth/me")
    check("GET /auth/me (no token)", r, 401)

    # ─── SUMMARY ─────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)

    if errors:
        print("\nFAILURES:")
        for e in errors:
            print(e)

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())