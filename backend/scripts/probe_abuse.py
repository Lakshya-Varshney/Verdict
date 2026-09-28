"""Abuse / robustness probe against the running stack.

Run: python backend/scripts/probe_abuse.py [base_url]

Throws hostile input at every kind of endpoint: oversized fields, NUL bytes, absurd numbers, wrong types,
injection strings, brute force. The invariant is simple: **the server must answer with a clean 4xx (or a
success), never a 5xx and never hang.** Also checks a few security properties directly (no user enumeration
via login, no secret leakage in errors, no stack traces). Exits 1 if anything is wrong.
"""
import sys
import time
import uuid

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
c = httpx.Client(base_url=BASE, timeout=30)
sfx = uuid.uuid4().hex[:6]
problems: list[str] = []
checked = 0


def H(t):
    return {"Authorization": f"Bearer {t}"}


def probe(label, r, ok=(400, 401, 403, 404, 409, 413, 422, 429, 200, 201, 204)):
    """A response is acceptable if it is a controlled status and leaks no internals."""
    global checked
    checked += 1
    body = r.text[:300]
    if r.status_code >= 500 or r.status_code not in ok:
        problems.append(f"{label}: HTTP {r.status_code} {body[:120]!r}")
    elif any(x in body for x in ("Traceback", "sqlalchemy", "asyncpg", "psycopg", "File \"/", "password_hash", "JWT_SECRET")):
        problems.append(f"{label}: leaks internals: {body[:160]!r}")
    return r


org = H(c.post("/auth/login", json={"email": "organizer@dogfoodhack.com", "password": "organizer123"}).json()["token"])
lead_t = c.post("/auth/signup", json={"email": f"lead{sfx}@t.io", "name": "Lead", "password": "pw123456"}).json()["token"]
lead = H(lead_t)
created_events: list[str] = []
eid = c.post("/events", headers=org, json={"name": f"Probe {sfx}", "voting_mode": "open"}).json()["id"]
created_events.append(eid)
c.post(f"/events/{eid}/roles", headers=org, json={"email": f"lead{sfx}@t.io", "role": "participant"})
tid = c.post(f"/events/{eid}/teams", headers=lead, json={"name": "T"}).json()["id"]
sid = c.post(f"/teams/{tid}/submissions", headers=lead, json={"name": "P"}).json()["id"]
c.post(f"/submissions/{sid}/submit", headers=lead)

BIG = "A" * 100_000
HUGE = "B" * 1_000_000
NUL = "bad\x00byte"
EMOJI = "\U0001F600" * 300
INJECT = ["' OR 1=1 --", "\"; DROP TABLE users; --", "%", "_", "\\", "<script>alert(1)</script>", "${jndi:ldap://x}", "{{7*7}}", "../../etc/passwd"]

try:
    # ---------------------------------------------------------------- signup / login
    for label, body in {
        "signup 100k name": {"email": f"a{sfx}@t.io", "name": BIG, "password": "pw123456"},
        "signup NUL name": {"email": f"b{sfx}@t.io", "name": NUL, "password": "pw123456"},
        "signup 100k email": {"email": BIG + "@t.io", "name": "x", "password": "pw123456"},
        "signup 1MB password": {"email": f"c{sfx}@t.io", "name": "x", "password": HUGE},
        "signup 100-byte password": {"email": f"d{sfx}@t.io", "name": "x", "password": "p" * 100},
        "signup emoji name": {"email": f"e{sfx}@t.io", "name": EMOJI, "password": "pw123456"},
        "signup empty": {},
        "signup wrong types": {"email": 5, "name": [], "password": {}},
        "signup no password": {"email": f"f{sfx}@t.io", "name": "x", "password": ""},
    }.items():
        probe(label, c.post("/auth/signup", json=body))
    for label, body in {
        "login 1MB password": {"email": "organizer@dogfoodhack.com", "password": HUGE},
        "login NUL": {"email": "organizer@dogfoodhack.com", "password": NUL},
        "login sqli email": {"email": "' OR 1=1 --@t.io", "password": "x"},
        "login wrong types": {"email": None, "password": 1},
    }.items():
        probe(label, c.post("/auth/login", json=body))
    probe("malformed json", c.post("/auth/login", content=b"{not json", headers={"content-type": "application/json"}))
    probe("wrong content-type", c.post("/auth/login", content=b"email=a&password=b", headers={"content-type": "text/plain"}))

    # user enumeration: unknown user and wrong password must look identical
    a = c.post("/auth/login", json={"email": "organizer@dogfoodhack.com", "password": "definitely-wrong"})
    b = c.post("/auth/login", json={"email": f"nobody{sfx}@t.io", "password": "definitely-wrong"})
    if (a.status_code, a.json()) != (b.status_code, b.json()):
        problems.append(f"login leaks whether an account exists: {a.status_code} {a.text[:80]} vs {b.status_code} {b.text[:80]}")
    dup = c.post("/auth/signup", json={"email": "organizer@dogfoodhack.com", "name": "x", "password": "pw123456"})
    checked += 1  # signup necessarily reveals a taken email (documented residual risk)

    # ---------------------------------------------------------------- events / teams / submissions / comments
    for field in ("name", "slug", "description", "tagline"):
        for label, val in (("100k", BIG), ("NUL", NUL), ("emoji", EMOJI), ("injection", INJECT[1])):
            r = probe(f"event {field} {label}", c.post("/events", headers=org, json={"name": "x" if field != "name" else val, field: val, **({"slug": f"s-{uuid.uuid4().hex[:8]}"} if field != "slug" else {})}))
            if r.status_code == 201:
                created_events.append(r.json()["id"])
    probe("team 100k name", c.post(f"/events/{eid}/teams", headers=H(c.post("/auth/signup", json={"email": f"t2{sfx}@t.io", "name": "x", "password": "pw123456"}).json()["token"]), json={"name": BIG}))
    for field, val in {
        "name": BIG, "tagline": "T" * 501, "description_md": HUGE, "thumbnail_url": "http://x/" + "u" * 600,
        "demo_video_url": "http://x/" + "u" * 600, "repo_url": "javascript:alert(1)", "live_url": "data:text/html,<script>1</script>",
        "gallery_image_urls": ["http://x/1"] * 5000, "tech_tags": ["t"] * 5000, "custom_answers": {str(i): "v" * 1000 for i in range(2000)},
    }.items():
        probe(f"submission patch {field}", c.patch(f"/submissions/{sid}", headers=lead, json={field: val}))
    for label, val in (("NUL name", NUL), ("NUL tagline", NUL)):
        probe(f"submission {label}", c.patch(f"/submissions/{sid}", headers=lead, json={"name": val if "name" in label else "ok", "tagline": val if "tagline" in label else "ok"}))
    for label, body in {"5001 chars": {"body": "c" * 5001}, "NUL": {"body": NUL}, "100k author": {"body": "x", "author_name": BIG}, "wrong type": {"body": 7}}.items():
        probe(f"comment {label}", c.post(f"/submissions/{sid}/comments", json=body))

    # ---------------------------------------------------------------- numbers and query params
    c.patch(f"/events/{eid}", headers=org, json={"status": "voting"})
    for label, body in {"votes -1": {"votes": -1}, "votes 1e9": {"votes": 10**9}, "votes str": {"votes": "many"}, "votes float": {"votes": 1.5},
                        "email 100k": {"email": BIG}, "fingerprint 1MB": {"fingerprint": HUGE}}.items():
        probe(f"vote {label}", c.post(f"/submissions/{sid}/vote", json=body))
    for label, params in {"page -1": {"page": -1}, "page 1e18": {"page": 10**18}, "limit 1e9": {"limit": 10**9}, "limit str": {"limit": "x"},
                          "search sqli": {"search": INJECT[0]}, "search wildcard": {"search": "%"}, "search 8k": {"search": "S" * 8000},
                          "tag NUL": {"tag": NUL}, "track_id junk": {"track_id": "not-a-uuid"}}.items():
        probe(f"gallery {label}", c.get(f"/events/{eid}/submissions", params=params))
    probe("uuid path junk", c.get("/submissions/%00"))
    probe("uuid path sqli", c.get("/submissions/1' OR '1'='1"))
    probe("path traversal", c.get("/static/../../etc/passwd"))
    probe("path traversal 2", c.get("/static/swagger/..%2f..%2fmain.py"))
    probe("huge header", c.get("/health", headers={"X-Junk": "j" * 60_000}), ok=(200, 400, 431, 413))
    for path in ("/openapi.json", "/docs", "/health", "/.well-known/dogfood-signing-key"):
        probe(f"GET {path}", c.get(path))
    for verb in ("PUT", "DELETE", "PATCH", "OPTIONS", "TRACE"):
        probe(f"{verb} /health", c.request(verb, "/health"), ok=(200, 204, 400, 404, 405))

    # ---------------------------------------------------------------- verify / embed / webhooks / import
    for code in ("x" * 5000, "%00", "' OR 1=1", "0" * 64):
        probe(f"verify {code[:8]!r}", c.get(f"/verify/{code}"))
    probe("verify POST junk", c.post("/verify", json={"payload": {"a": [1] * 100000}, "signature": "!!"}))
    probe("verify POST wrong types", c.post("/verify", json={"payload": "str", "signature": 5}))
    probe("embed junk theme", c.get(f"/embed/{eid}", params={"theme": "<script>"}))
    probe("embed junk limit", c.get(f"/embed/{eid}/gallery", params={"limit": -5}))
    probe("webhook huge url", c.post("/webhooks/subscribe", headers=org, json={"url": "https://" + "a" * 5000 + ".example.com", "event_types": ["*"]}))
    probe("webhook NUL url", c.post("/webhooks/subscribe", headers=org, json={"url": "https://x.example.com/\x00", "event_types": ["*"]}))
    probe("webhook 1000 types", c.post("/webhooks/subscribe", headers=org, json={"url": "https://x.example.com", "event_types": ["*"] * 1000}))
    probe("import junk", c.post(f"/events/{eid}/import", headers=org, json={"format": "dogfood-event-dump", "version": 1, "event": {"id": "x", "name": "n"}, "scores": [{}] * 10}))
    probe("import deep nesting", c.post(f"/events/{eid}/import", headers=org, content=b'{"a":' * 3000 + b"1" + b"}" * 3000, ))
    probe("import wrong type", c.post(f"/events/{eid}/import", headers=org, json=[1, 2, 3]))
    probe("audit filter junk", c.get("/admin/audit", headers=org, params={"action": "x" * 5000, "page": 0}))
    probe("audit sqli", c.get("/admin/audit", headers=org, params={"action": INJECT[0], "event_id": "junk"}))

    # ---------------------------------------------------------------- authorization exploits (must all FAIL)
    def signup(tag):
        r = c.post("/auth/signup", json={"email": f"{tag}{sfx}@t.io", "name": tag, "password": "pw123456"}).json()
        return H(r["token"]), r["user"]["id"]

    def expect(label, cond):
        global checked
        checked += 1
        if not cond:
            problems.append(f"EXPLOIT SUCCEEDED: {label}")

    atk, atk_id = signup("attacker")
    ev_a = c.post("/events", headers=org, json={"name": f"Atk {sfx}"}).json()["id"]
    created_events.append(ev_a)
    c.post(f"/events/{ev_a}/roles", headers=org, json={"user_id": atk_id, "role": "organizer"})  # attacker organizes ONLY this event
    audit = c.get("/admin/audit", headers=atk, params={"limit": 100}).json().get("items", [])
    expect("organizer reads other events' audit log", all(i["event_id"] == ev_a for i in audit))
    expect("organizer requests another event's audit by id", c.get("/admin/audit", headers=atk, params={"event_id": eid}).status_code == 403)
    expect("organizer grants themselves admin", c.post(f"/events/{ev_a}/roles", headers=atk, json={"user_id": atk_id, "role": "admin"}).status_code == 403)
    draft = c.post("/events", headers=org, json={"name": f"Draft {sfx}"}).json()["id"]
    created_events.append(draft)
    anon = httpx.Client(base_url=BASE, timeout=30)
    expect("anonymous lists draft events", all(e["status"] != "draft" for e in anon.get("/events").json()))
    expect("anonymous reads a draft event", anon.get(f"/events/{draft}").status_code == 404)
    for sub_path in ("tracks", "rubric/criteria", "submissions"):
        expect(f"anonymous reads a draft event's {sub_path}", anon.get(f"/events/{draft}/{sub_path}").status_code == 404)
    judge, judge_id = signup("judgeprobe")
    lead2, lead2_id = signup("leadprobe")
    for uid, role in ((judge_id, "judge"), (lead2_id, "participant")):
        c.post(f"/events/{ev_a}/roles", headers=org, json={"user_id": uid, "role": role})
    tid2 = c.post(f"/events/{ev_a}/teams", headers=lead2, json={"name": "T"}).json()["id"]
    sid2 = c.post(f"/teams/{tid2}/submissions", headers=lead2, json={"name": "P"}).json()["id"]
    c.post(f"/submissions/{sid2}/submit", headers=lead2)
    cid = c.post(f"/events/{ev_a}/rubric/criteria", headers=org, json={"name": "Q", "scale_min": 1, "scale_max": 5}).json()["id"]
    c.post(f"/events/{ev_a}/judging/assign", headers=org, json={"reviews_per_submission": 1})
    expect("judge can score inside the window", c.post(f"/submissions/{sid2}/scores", headers=judge, json={"criterion_id": cid, "value": 3}).status_code == 200)
    expect("criterion with scores can be deleted", c.delete(f"/events/{ev_a}/rubric/criteria/{cid}", headers=org).status_code == 409)
    c.patch(f"/events/{ev_a}", headers=org, json={"status": "published"})
    expect("judge changes a score after results are published", c.post(f"/submissions/{sid2}/scores", headers=judge, json={"criterion_id": cid, "value": 5}).status_code == 403)
    c.patch(f"/events/{ev_a}", headers=org, json={"status": "open"})
    expect("javascript: link accepted in a project", c.patch(f"/submissions/{sid2}", headers=lead2, json={"repo_url": "javascript:alert(1)"}).status_code == 422)
    expect("empty password accepted at signup", c.post("/auth/signup", json={"email": f"e{sfx}@t.io", "name": "x", "password": ""}).status_code == 422)
    expect("participant reads another team's scores", c.get(f"/submissions/{sid2}/scores", headers=lead2).status_code == 403)
    expect("judge reads all judges' scores", c.get(f"/submissions/{sid2}/scores", headers=judge).status_code == 403)
    expect("organizer of another event deletes this event", c.delete(f"/events/{ev_a}", headers=signup("nobody")[0]).status_code in (401, 403))
    # ---------------------------------------------------------------- brute force / rate limiting
    statuses = [c.post("/auth/login", json={"email": f"victim{sfx}@t.io", "password": f"guess{i}"}).status_code for i in range(40)]
    checked += 1
    if 429 not in statuses:
        problems.append(f"login is not rate limited: 40 wrong guesses in a row -> {sorted(set(statuses))} (no 429)")
    t0 = time.time()
    n = sum(1 for _ in range(140) if c.post("/auth/signup", json={"email": f"spam{uuid.uuid4().hex[:8]}@t.io", "name": "s", "password": "pw123456"}).status_code == 201)
    checked += 1
    if n == 140:
        problems.append(f"signup is not rate limited: {n} accounts created from one IP (140 attempts) in {time.time() - t0:.1f}s")
finally:
    for e in created_events:  # leave nothing behind
        c.delete(f"/events/{e}", headers=org)

print(f"probes run: {checked}")
if problems:
    print(f"\n{len(problems)} PROBLEM(S):")
    for p in problems:
        print("  -", p)
    sys.exit(1)
print("clean: no 5xx, no leaks, no missing limits, no authorization exploit succeeded")
