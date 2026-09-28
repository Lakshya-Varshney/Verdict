"""Live T3 test (public voting) through the running stack.

Run: python scripts/live_t3.py [base_url]     default http://localhost:3000/api (via the Next proxy, so
cookies + X-Forwarded-For behave exactly as in production). Uses throwaway events; safe to re-run.
"""
import sys
import uuid

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3000/api"
ok = bad = 0


def chk(label, cond, extra=""):
    global ok, bad
    if cond:
        ok += 1
    else:
        bad += 1
        print(f"FAIL {label} {extra}")


def client():
    return httpx.Client(base_url=BASE, timeout=20)


def H(t):
    return {"Authorization": f"Bearer {t}"}


sfx = uuid.uuid4().hex[:6]
c = client()
org = H(c.post("/auth/login", json={"email": "organizer@dogfoodhack.com", "password": "organizer123"}).json()["token"])


def signup(tag):
    return H(c.post("/auth/signup", json={"email": f"{tag}{sfx}@t.io", "name": tag, "password": "pw123456"}).json()["token"])


def make_event(mode, n_subs=8, **cfg):
    """Event in `voting` status with n_subs submitted projects (each by its own team leader)."""
    e = c.post("/events", headers=org, json={"name": f"T3 {mode} {uuid.uuid4().hex[:4]}", "voting_mode": mode, **cfg}).json()
    eid = e["id"]
    subs = []
    for i in range(n_subs):
        lead = signup(f"lead{uuid.uuid4().hex[:6]}")
        me = c.get("/auth/me", headers=lead).json()
        c.post(f"/events/{eid}/roles", headers=org, json={"user_id": me["id"], "role": "participant"})
        tid = c.post(f"/events/{eid}/teams", headers=lead, json={"name": f"Team {i}"}).json()["id"]
        sid = c.post(f"/teams/{tid}/submissions", headers=lead, json={"name": f"Proj {i}"}).json()["id"]
        c.post(f"/submissions/{sid}/submit", headers=lead)
        subs.append(sid)
    return eid, subs


def to_voting(eid):
    r = c.patch(f"/events/{eid}", headers=org, json={"status": "voting"})
    chk("status -> voting", r.status_code == 200 and r.json()["status"] == "voting", r.text[:100])


events = []
try:
    # ---- window: before voting opens
    eid, subs = make_event("open")
    events.append(eid)
    # anon GET: new events are drafts, hidden from the public until the organizer opens them
    chk("event stores voting_mode", c.get(f"/events/{eid}", headers=org).json()["voting_mode"] == "open")
    r = client().post(f"/submissions/{subs[0]}/vote")
    chk("vote before window -> 400", r.status_code == 400 and "not started" in r.text, r.text[:100])
    to_voting(eid)

    # ---- open mode through the proxy: cookie identity, one vote per person per event
    v1 = client()
    r = v1.post(f"/submissions/{subs[0]}/vote", json={"fingerprint": "fp-a"})
    chk("open vote 201", r.status_code == 201, r.text[:120])
    chk("session cookie issued", "voter_session" in v1.cookies)
    chk("budget reported", r.json().get("votes_left") == 0, r.text[:120])
    r = v1.post(f"/submissions/{subs[0]}/vote", json={"fingerprint": "fp-a"})
    chk("duplicate -> 400", r.status_code == 400, r.text[:100])
    r = v1.post(f"/submissions/{subs[1]}/vote", json={"fingerprint": "fp-a"})
    chk("second project, same person -> 400 (1 vote/event)", r.status_code == 400 and "limit" in r.text, r.text[:100])
    v2 = client()
    chk("different person can vote", v2.post(f"/submissions/{subs[1]}/vote", json={"fingerprint": "fp-b"}).status_code == 201)

    # ---- results hiding
    r = client().get(f"/submissions/{subs[0]}/votes/count").json()
    chk("count hidden for public during voting", r["hidden"] and r["count"] is None and r["vote_count"] is None, str(r))
    r = c.get(f"/submissions/{subs[0]}/votes/count", headers=org).json()
    chk("organizer sees count", not r["hidden"] and r["count"] == 1, str(r))
    chk("results endpoint closed to public", client().get(f"/events/{eid}/judging/results").status_code == 401)

    # ---- ballot order per session
    def order(cl):
        return [i["id"] for i in cl.get(f"/events/{eid}/ballot").json()["items"]]
    a1, a2, b1 = order(v1), order(v1), order(v2)
    chk("ballot stable per session", a1 == a2 and len(a1) == 8)
    chk("ballot differs across sessions", a1 != b1 and sorted(a1) == sorted(b1))
    ballot = v1.get(f"/events/{eid}/ballot").json()
    chk("ballot shows my votes, no tallies", ballot["voter"]["votes_used"] == 1 and all("count" not in i for i in ballot["items"]))

    # ---- rate limit: 10/min per identity; rotate cookies to hit per-IP ceiling (60/min) -> 429 + Retry-After
    eid2, subs2 = make_event("open", n_subs=1, votes_per_voter=50)
    events.append(eid2)
    to_voting(eid2)
    limited = None
    for i in range(80):
        r = client().post(f"/submissions/{subs2[0]}/vote", json={"fingerprint": f"rot-{i}"}, headers={"X-Forwarded-For": "203.0.113.9"})
        if r.status_code == 429:
            limited = (i, r.headers.get("retry-after"))
            break
    chk("rate limit 429 with Retry-After", limited is not None and limited[1] is not None, str(limited))

    # ---- auth mode
    eid3, subs3 = make_event("auth", n_subs=2)
    events.append(eid3)
    to_voting(eid3)
    chk("auth vote anonymous -> 401", client().post(f"/submissions/{subs3[0]}/vote").status_code == 401)
    voter = signup("voter")
    chk("auth vote ok", client().post(f"/submissions/{subs3[0]}/vote", headers=voter).status_code == 201)
    chk("auth 2nd project -> 400", client().post(f"/submissions/{subs3[1]}/vote", headers=voter).status_code == 400)

    # ---- email mode
    eid4, subs4 = make_event("email", n_subs=2)
    events.append(eid4)
    to_voting(eid4)
    chk("email missing -> 400", client().post(f"/submissions/{subs4[0]}/vote").status_code == 400)
    chk("email ok", client().post(f"/submissions/{subs4[0]}/vote", json={"email": f"a{sfx}@x.org"}).status_code == 201)
    chk("same email other browser -> 400", client().post(f"/submissions/{subs4[1]}/vote", json={"email": f"A{sfx}@X.org"}).status_code == 400)

    # ---- quadratic
    eid5, subs5 = make_event("quadratic", n_subs=3, vote_credits=25)
    events.append(eid5)
    to_voting(eid5)
    q = signup("quad")
    r = client().post(f"/submissions/{subs5[0]}/vote", json={"votes": 3}, headers=q).json()
    chk("quadratic 3 votes cost 9", r.get("credits_left") == 16, str(r))
    r = client().post(f"/submissions/{subs5[1]}/vote", json={"votes": 4}, headers=q).json()
    chk("quadratic 4 votes cost 16 -> 0 left", r.get("credits_left") == 0, str(r))
    r = client().post(f"/submissions/{subs5[2]}/vote", json={"votes": 1}, headers=q)
    chk("quadratic over budget -> 400", r.status_code == 400 and "credits" in r.text, r.text[:100])
    tally = [c.get(f"/submissions/{s}/votes/count", headers=org).json()["count"] for s in subs5]
    chk("quadratic tally = weights", tally == [3, 4, 0], str(tally))

    # ---- comments + rate limit
    cm = client()
    r = cm.post(f"/submissions/{subs[0]}/comments", json={"body": "nice!", "author_name": "Visitor"})
    chk("anonymous comment 201", r.status_code == 201, r.text[:100])
    codes = [cm.post(f"/submissions/{subs[0]}/comments", json={"body": f"c{i}"}).status_code for i in range(15)]
    chk("comment rate limit -> 429", 429 in codes, str(codes))
    chk("comments listed", len(client().get(f"/submissions/{subs[0]}/comments").json()) >= 2)

    # ---- audit: readable without a DB client
    js = c.get("/admin/audit", headers=org, params={"event_id": eid}).json()
    actions = {i["action"] for i in js["items"]}
    chk("audit has vote.cast + vote.rejected + status change", {"vote.cast", "vote.rejected", "event.status_change"} <= actions, str(actions))
    txt = c.get("/admin/audit", headers=org, params={"event_id": eid, "format": "text"})
    chk("audit text view", txt.status_code == 200 and "vote.cast" in txt.text and "denied" in txt.text, txt.text[:200])
    chk("audit closed to public", client().get("/admin/audit").status_code == 401)

    # ---- after close, tally is public
    c.patch(f"/events/{eid}", headers=org, json={"status": "published"})
    r = client().get(f"/submissions/{subs[0]}/votes/count").json()
    chk("tally public after close", not r["hidden"] and r["count"] == 1, str(r))
finally:
    for e in events + ([eid] if "eid" in dir() and eid not in events else []):
        c.delete(f"/events/{e}", headers=org)

print(f"\nRESULT: {ok} passed, {bad} failed")
sys.exit(1 if bad else 0)
