"""Deep live test: full event lifecycle + negative cases against the running stack.

Run: python scripts/live_lifecycle.py [base_url]    (default http://localhost:8000)
Creates its own throwaway event/users (unique suffix), so it is safe to re-run on the dev DB.
"""
import sys
import uuid

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
c = httpx.Client(base_url=BASE, timeout=20)
ok = bad = 0


def chk(label, r, *want):
    global ok, bad
    if r.status_code in want:
        ok += 1
    else:
        bad += 1
        print(f"FAIL {label}: want {want} got {r.status_code} {r.text[:160]}")
    return r


def H(tok):
    return {"Authorization": f"Bearer {tok}"}


def login(email, pw):
    return c.post("/auth/login", json={"email": email, "password": pw}).json()["token"]


sfx = uuid.uuid4().hex[:8]
org = H(login("organizer@dogfoodhack.com", "organizer123"))
admin = H(login("admin@dogfoodhack.com", "admin123"))

chk("health", c.get("/health"), 200)


# --- auth
def signup(tag):
    r = chk(f"signup {tag}", c.post("/auth/signup", json={"email": f"{tag}{sfx}@t.io", "name": tag, "password": "pw123456"}), 201, 200)
    return r.json()["token"]


lead, mate, judge, j2, rand = (H(signup(t)) for t in ("lead", "mate", "judge", "judgetwo", "rand"))
chk("signup dup", c.post("/auth/signup", json={"email": f"lead{sfx}@t.io", "name": "x", "password": "pw123456"}), 400, 409)
chk("signup bad/422", c.post("/auth/signup", json={"email": "nope"}), 422)
chk("login bad pw", c.post("/auth/login", json={"email": f"lead{sfx}@t.io", "password": "wrong"}), 401)
chk("me", c.get("/auth/me", headers=lead), 200)
chk("me no token", c.get("/auth/me"), 401)
chk("me garbage token", c.get("/auth/me", headers=H("garbage")), 401)
chk("logout", c.post("/auth/logout", headers=lead), 200, 204)

# --- events
chk("create event anon", c.post("/events", json={"name": "x"}), 401)
chk("create event participant", c.post("/events", json={"name": "x"}, headers=lead), 403)
r = chk("create event org", c.post("/events", json={"name": f"Deep {sfx}", "slug": f"deep-{sfx}"}, headers=org), 201)
eid = r.json()["id"]
chk("dup slug", c.post("/events", json={"name": "d", "slug": f"deep-{sfx}"}, headers=org), 400, 409)
chk("get event anon (draft hidden)", c.get(f"/events/{eid}"), 404)
chk("get event org (draft visible to organizer)", c.get(f"/events/{eid}", headers=org), 200)
chk("list events", c.get("/events"), 200)
chk("bad uuid", c.get("/events/not-a-uuid"), 422)
chk("patch anon", c.patch(f"/events/{eid}", json={"tagline": "t"}), 401)
chk("patch participant", c.patch(f"/events/{eid}", json={"tagline": "t"}, headers=lead), 403)
r = chk("patch org", c.patch(f"/events/{eid}", json={"tagline": "hello", "status": "open"}, headers=org), 200)
print("  event after patch:", {k: r.json().get(k) for k in ("status", "tagline")})

# --- roles
chk("roles anon", c.get(f"/events/{eid}/roles"), 401)
chk("roles participant", c.get(f"/events/{eid}/roles", headers=lead), 403)
chk("roles org", c.get(f"/events/{eid}/roles", headers=org), 200)
chk("add role no target", c.post(f"/events/{eid}/roles", json={"role": "judge"}, headers=org), 400, 422)
chk("add role denied", c.post(f"/events/{eid}/roles", json={"email": f"judge{sfx}@t.io", "role": "judge"}, headers=lead), 403)
for tag, role in (("judge", "judge"), ("judgetwo", "judge"), ("lead", "participant"), ("mate", "participant")):
    chk(f"add {tag}", c.post(f"/events/{eid}/roles", json={"email": f"{tag}{sfx}@t.io", "role": role}, headers=org), 200, 201)

# --- tracks
chk("track anon", c.post(f"/events/{eid}/tracks", json={"name": "T"}), 401)
chk("track participant", c.post(f"/events/{eid}/tracks", json={"name": "T"}, headers=lead), 403)
tr = chk("track org", c.post(f"/events/{eid}/tracks", json={"name": "AI", "description": "d"}, headers=org), 201).json()
chk("tracks list", c.get(f"/events/{eid}/tracks"), 200)

# --- teams
r = chk("team create", c.post(f"/events/{eid}/teams", json={"name": "Alpha"}, headers=lead), 201).json()
tid = r["id"]
code = r.get("invite_code")
chk("team mine", c.get(f"/events/{eid}/teams/mine", headers=lead), 200)
chk("team get", c.get(f"/teams/{tid}", headers=lead), 200)
chk("join bad code", c.post(f"/teams/{tid}/join", json={"invite_code": "wrong"}, headers=mate), 400, 403, 404)
chk("join anon", c.post(f"/teams/{tid}/join", json={"invite_code": code}), 401)
chk("join ok", c.post(f"/teams/{tid}/join", json={"invite_code": code}, headers=mate), 200, 201)
chk("join twice", c.post(f"/teams/{tid}/join", json={"invite_code": code}, headers=mate), 400, 409)
chk("second team same user", c.post(f"/events/{eid}/teams", json={"name": "Beta"}, headers=lead), 400, 409)

# --- submissions
chk("sub create non-leader", c.post(f"/teams/{tid}/submissions", json={"name": "N"}, headers=mate), 403)
r = chk("sub create", c.post(f"/teams/{tid}/submissions", json={"name": "Proj", "tagline": "tg", "tech_tags": ["a"], "custom_answers": {"q": {"n": 1}}, "gallery_image_urls": ["http://x/1.png"], "track_id": tr["id"]}, headers=lead), 201).json()
sid = r["id"]
chk("sub create 2nd (allowed: fixtures have multi-project teams)", c.post(f"/teams/{tid}/submissions", json={"name": "P2"}, headers=lead), 201)
chk("sub draft hidden anon", c.get(f"/submissions/{sid}"), 404)
chk("sub draft visible member", c.get(f"/submissions/{sid}", headers=mate), 200)
gal = chk("gallery hides draft", c.get(f"/events/{eid}/submissions"), 200).json()
if gal != []:
    bad += 1
    print("FAIL draft leaked into gallery", gal)
chk("sub patch non-leader", c.patch(f"/submissions/{sid}", json={"name": "H"}, headers=mate), 403)
r = chk("sub patch", c.patch(f"/submissions/{sid}", json={"description_md": "# hi", "custom_answers": {"z": [1, 2]}}, headers=lead), 200).json()
if r.get("custom_answers") != {"z": [1, 2]}:
    bad += 1
    print("FAIL custom_answers roundtrip", r.get("custom_answers"))
chk("sub submit non-leader", c.post(f"/submissions/{sid}/submit", headers=mate), 403)
chk("sub submit anon", c.post(f"/submissions/{sid}/submit"), 401)
chk("sub submit", c.post(f"/submissions/{sid}/submit", headers=lead), 200)
g = chk("gallery shows", c.get(f"/events/{eid}/submissions"), 200).json()
if [x["id"] for x in g] != [sid]:
    bad += 1
    print("FAIL gallery content", g)
chk("gallery filter track", c.get(f"/events/{eid}/submissions", params={"track_id": tr["id"]}), 200)
chk("gallery filter tag", c.get(f"/events/{eid}/submissions", params={"tag": "a"}), 200)
chk("gallery search", c.get(f"/events/{eid}/submissions", params={"search": "Proj"}), 200)
chk("gallery page 0", c.get(f"/events/{eid}/submissions", params={"page": 0}), 422)
chk("gallery limit 201", c.get(f"/events/{eid}/submissions", params={"limit": 201}), 422)
chk("sub 404", c.get(f"/submissions/{uuid.uuid4()}"), 404)

# --- rubric
chk("crit participant", c.post(f"/events/{eid}/rubric/criteria", json={"name": "X"}, headers=lead), 403)
c1 = chk("crit 1", c.post(f"/events/{eid}/rubric/criteria", json={"name": "Innov", "weight": 2, "scale_min": 1, "scale_max": 5}, headers=org), 201).json()
c2 = chk("crit 2", c.post(f"/events/{eid}/rubric/criteria", json={"name": "Impact", "weight": 1, "scale_min": 1, "scale_max": 5}, headers=org), 201).json()
c3 = chk("crit 3", c.post(f"/events/{eid}/rubric/criteria", json={"name": "Tmp"}, headers=org), 201).json()
chk("crit list", c.get(f"/events/{eid}/rubric/criteria"), 200)
chk("crit delete participant", c.delete(f"/events/{eid}/rubric/criteria/{c3['id']}", headers=lead), 403)
chk("crit delete", c.delete(f"/events/{eid}/rubric/criteria/{c3['id']}", headers=org), 204)
chk("crit delete again", c.delete(f"/events/{eid}/rubric/criteria/{c3['id']}", headers=org), 404)

# --- judging
chk("assign participant", c.post(f"/events/{eid}/judging/assign", json={"reviews_per_submission": 1}, headers=lead), 403)
chk("assign", c.post(f"/events/{eid}/judging/assign", json={"reviews_per_submission": 2}, headers=org), 200)
chk("assignments org", c.get(f"/events/{eid}/judging/assignments", headers=org), 200)
chk("assignments participant", c.get(f"/events/{eid}/judging/assignments", headers=lead), 403)
a = chk("assign mine judge", c.get(f"/events/{eid}/judging/assignments/mine", headers=judge), 200).json()
print("  judge assignments:", len(a))
chk("progress org", c.get(f"/events/{eid}/judging/progress", headers=org), 200)
chk("progress judge", c.get(f"/events/{eid}/judging/progress", headers=judge), 403)

# --- scoring
chk("score anon", c.post(f"/submissions/{sid}/scores", json={"criterion_id": c1["id"], "value": 4}), 401)
chk("score participant", c.post(f"/submissions/{sid}/scores", json={"criterion_id": c1["id"], "value": 4}, headers=lead), 403)
chk("score judge single", c.post(f"/submissions/{sid}/scores", json={"criterion_id": c1["id"], "value": 4, "comment": "ok"}, headers=judge), 200)
chk("score out of range", c.post(f"/submissions/{sid}/scores", json={"criterion_id": c1["id"], "value": 99}, headers=judge), 400, 422)
chk("score partial j2", c.post(f"/submissions/{sid}/scores", json={"scores": [{"criterion_id": c2["id"], "raw_value": 2}]}, headers=j2), 200)
chk("score overwrite", c.post(f"/submissions/{sid}/scores", json={"criterion_id": c1["id"], "value": 5}, headers=judge), 200)
m = chk("scores mine", c.get(f"/submissions/{sid}/scores/mine", headers=judge), 200).json()
if not (len(m["scores"]) == 1 and m["scores"][0]["value"] == 5):
    bad += 1
    print("FAIL scores/mine content", m)
chk("scores mine participant", c.get(f"/submissions/{sid}/scores/mine", headers=lead), 403)
chk("scores all judge (peer)", c.get(f"/submissions/{sid}/scores", headers=j2), 403)
chk("scores all org", c.get(f"/submissions/{sid}/scores", headers=org), 200)
chk("scores all other user", c.get(f"/submissions/{sid}/scores", headers=rand), 403)

# --- normalize / results / csv
chk("normalize participant", c.post(f"/events/{eid}/judging/normalize", headers=lead), 403)
chk("normalize", c.post(f"/events/{eid}/judging/normalize", headers=org), 200)
res = chk("results", c.get(f"/events/{eid}/judging/results", headers=org), 200).json()
if not (len(res["rows"]) == 1 and res["rows"][0]["judge_count"] == 2):
    bad += 1
    print("FAIL partial reviews not counted", res["rows"])
chk("results participant", c.get(f"/events/{eid}/judging/results", headers=lead), 403)
chk("results anon", c.get(f"/events/{eid}/judging/results"), 401)
csv = chk("csv", c.get(f"/events/{eid}/judging/export.csv", headers=org), 200)
if not (csv.headers["content-type"].startswith("text/csv") and len(csv.text.splitlines()) == 2):
    bad += 1
    print("FAIL csv shape", csv.text)
chk("csv judge", c.get(f"/events/{eid}/judging/export.csv", headers=judge), 403)
chk("csv anon", c.get(f"/events/{eid}/judging/export.csv"), 401)

# --- votes / comments
chk("votecount", c.get(f"/submissions/{sid}/votes/count"), 200)
ua = {"User-Agent": "deep/" + sfx}
v1 = chk("vote (201 or closed 400)", c.post(f"/submissions/{sid}/vote", headers=ua), 201, 400)
if v1.status_code == 201:
    chk("vote dup", c.post(f"/submissions/{sid}/vote", headers=ua), 400, 409)
chk("comment authed", c.post(f"/submissions/{sid}/comments", json={"body": "nice"}, headers=rand), 201)
chk("comment anon", c.post(f"/submissions/{sid}/comments", json={"body": "nice", "author_name": "A"}), 201, 401)
chk("comment empty", c.post(f"/submissions/{sid}/comments", json={"body": ""}, headers=rand), 400, 422)
chk("comments list", c.get(f"/submissions/{sid}/comments"), 200)

# --- admin/audit
chk("audit anon", c.get("/admin/audit"), 401)
chk("audit participant", c.get("/admin/audit", headers=lead), 403)
chk("audit org", c.get("/admin/audit", headers=org), 200)
chk("audit admin", c.get("/admin/audit", headers=admin), 200)

# --- member removal + event delete
mate_id = c.get("/auth/me", headers=mate).json()["id"]
chk("remove member by non-leader", c.delete(f"/teams/{tid}/members/{mate_id}", headers=rand), 403)
chk("remove member by leader", c.delete(f"/teams/{tid}/members/{mate_id}", headers=lead), 200, 204)
chk("delete event participant", c.delete(f"/events/{eid}", headers=lead), 403)
chk("delete event anon", c.delete(f"/events/{eid}"), 401)
chk("delete event", c.delete(f"/events/{eid}", headers=org), 200, 204)
chk("event gone", c.get(f"/events/{eid}"), 404)

print(f"\nRESULT: {ok} passed, {bad} failed")
sys.exit(1 if bad else 0)
