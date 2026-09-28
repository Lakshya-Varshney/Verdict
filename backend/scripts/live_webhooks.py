"""Live webhook test: a real HTTP receiver on this machine, called by the running API container.

Run: python backend/scripts/live_webhooks.py      (docker stack up; the API is allowed to reach private targets in compose)
Starts a receiver on :9191 (reached from the container as host.docker.internal), drives real actions through the
API, and checks the deliveries that arrive: signatures, payloads, retries, isolation and the SSRF guard.
"""
import hashlib
import hmac
import http.server
import json
import socketserver
import sys
import threading
import time
import uuid

import httpx

API = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
PORT = 9191
HOST_FROM_CONTAINER = f"http://host.docker.internal:{PORT}"
ok = bad = 0
received: list[dict] = []
flaky_hits = {"n": 0}
lock = threading.Lock()


def chk(label, cond, extra=""):
    global ok, bad
    if cond:
        ok += 1
    else:
        bad += 1
        print(f"FAIL {label} {extra}")


class Receiver(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length", 0)))
        rec = {"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body.decode()}
        with lock:
            received.append(rec)
            if self.path == "/flaky":
                flaky_hits["n"] += 1
                code = 500 if flaky_hits["n"] == 1 else 200  # fail once, then recover
            else:
                code = 200
        self.send_response(code)
        self.end_headers()

    def log_message(self, *a):
        pass


srv = socketserver.ThreadingTCPServer(("0.0.0.0", PORT), Receiver)
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()


def verify(secret, rec):
    ts = rec["headers"]["x-dogfood-timestamp"]
    mac = hmac.new(secret.encode(), f"{ts}.".encode() + rec["body"].encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest("sha256=" + mac, rec["headers"]["x-dogfood-signature"]) and abs(time.time() - int(ts)) < 300


def wait_for(pred, timeout=25):
    end = time.time() + timeout
    while time.time() < end:
        with lock:
            if pred():
                return True
        time.sleep(0.3)
    return False


c = httpx.Client(base_url=API, timeout=30)
H = lambda t: {"Authorization": f"Bearer {t}"}  # noqa: E731
sfx = uuid.uuid4().hex[:6]
org = H(c.post("/auth/login", json={"email": "organizer@dogfoodhack.com", "password": "organizer123"}).json()["token"])


def signup(tag):
    return H(c.post("/auth/signup", json={"email": f"{tag}{sfx}@t.io", "name": tag, "password": "pw123456"}).json()["token"])


eid = c.post("/events", headers=org, json={"name": f"Hooks {sfx}", "slug": f"hooks-{sfx}", "voting_mode": "open"}).json()["id"]
try:
    lead = signup("lead")
    c.post(f"/events/{eid}/roles", headers=org, json={"email": f"lead{sfx}@t.io", "role": "participant"})

    # ---- registration
    r = c.post("/webhooks/subscribe", headers=org, json={"url": f"{HOST_FROM_CONTAINER}/ok", "event_types": ["*"], "event_id": eid})
    chk("subscribe 201 + secret", r.status_code == 201 and r.json()["secret"].startswith("whsec_"), r.text[:150])
    main = r.json()
    r = c.post("/webhooks/subscribe", headers=org, json={"url": f"{HOST_FROM_CONTAINER}/flaky", "event_types": ["team.created"], "event_id": eid})
    flaky = r.json()
    chk("SSRF: cloud metadata refused", c.post("/webhooks/subscribe", headers=org, json={"url": "http://169.254.169.254/latest", "event_types": ["*"]}).status_code == 422)
    chk("bad type refused", c.post("/webhooks/subscribe", headers=org, json={"url": f"{HOST_FROM_CONTAINER}/x", "event_types": ["nope"]}).status_code == 422)
    chk("participant cannot register", c.post("/webhooks/subscribe", headers=lead, json={"url": f"{HOST_FROM_CONTAINER}/x", "event_types": ["*"]}).status_code == 403)
    chk("secret not listed", "secret" not in json.dumps(c.get("/webhooks", headers=org, params={"event_id": eid}).json()))

    # ---- real actions
    tid = c.post(f"/events/{eid}/teams", headers=lead, json={"name": "T"}).json()["id"]
    sid = c.post(f"/teams/{tid}/submissions", headers=lead, json={"name": "Hook Proj"}).json()["id"]
    c.post(f"/submissions/{sid}/submit", headers=lead)
    c.post(f"/events/{eid}/rubric/criteria", headers=org, json={"name": "Q", "scale_min": 1, "scale_max": 5})
    c.patch(f"/events/{eid}", headers=org, json={"status": "voting"})
    c.post(f"/submissions/{sid}/vote", json={"fingerprint": "hook-test"})
    c.post(f"/submissions/{sid}/comments", json={"body": "hello hooks"})
    c.post(f"/events/{eid}/judging/normalize", headers=org)
    c.patch(f"/events/{eid}", headers=org, json={"status": "published"})

    want = {"team.created", "submission.submitted", "event.status_changed", "vote.cast", "comment.added", "judging.normalized", "results.published"}
    got = lambda: {json.loads(r["body"])["type"] for r in received if r["path"] == "/ok"}  # noqa: E731
    chk("every event type arrives at the receiver", wait_for(lambda: want <= got()), f"missing {want - got()}")

    with lock:
        ok_recs = [r for r in received if r["path"] == "/ok"]
    chk("every delivery's HMAC signature verifies with the secret", all(verify(main["secret"], r) for r in ok_recs) and ok_recs)
    chk("a wrong secret does not verify", not verify("whsec_wrong", ok_recs[0]))
    ids = [json.loads(r["body"])["id"] for r in ok_recs]
    chk("delivery ids unique + match the header", len(set(ids)) == len(ids) and all(json.loads(r["body"])["id"] == r["headers"]["x-dogfood-delivery"] for r in ok_recs))
    vote = next(json.loads(r["body"]) for r in ok_recs if json.loads(r["body"])["type"] == "vote.cast")
    chk("vote.cast carries no tally", vote["data"] == {"submission_id": sid, "weight": 1, "mode": "open", "updated": False}, str(vote["data"]))
    chk("all payloads are for this event only", all(json.loads(r["body"])["event_id"] == eid for r in ok_recs))
    chk("no emails anywhere", "@" not in " ".join(r["body"] for r in ok_recs))

    # ---- retry: the flaky endpoint fails the first request, then recovers via backoff (~5 s)
    chk("flaky endpoint eventually gets the event after a retry", wait_for(lambda: flaky_hits["n"] >= 2, 40), f"hits={flaky_hits['n']}")
    time.sleep(1)
    log = c.get(f"/webhooks/{flaky['id']}/deliveries", headers=org).json()
    chk("delivery log shows success after 2 attempts", log and log[0]["status"] == "success" and log[0]["attempts"] == 2, str(log))
    with lock:
        f_recs = [r for r in received if r["path"] == "/flaky"]
    chk("retry reuses the same delivery id and body", len({r["headers"]["x-dogfood-delivery"] for r in f_recs}) == 1 and len({r["body"] for r in f_recs}) == 1)
    chk("attempt header counts", [r["headers"]["x-dogfood-attempt"] for r in f_recs][:2] == ["1", "2"])

    # ---- ping + management
    p = c.post(f"/webhooks/{main['id']}/ping", headers=org)
    chk("ping accepted", p.status_code == 202)
    chk("ping arrives", wait_for(lambda: any(json.loads(r["body"])["type"] == "webhook.ping" for r in received if r["path"] == "/ok"), 15))
    chk("delete", c.delete(f"/webhooks/{main['id']}", headers=org).json() == {"ok": True})
    n_before = len([r for r in received if r["path"] == "/ok"])
    c.post(f"/events/{eid}/teams", headers=signup("late"), json={"name": "X"})  # no longer subscribed anywhere relevant
    time.sleep(3)
    chk("nothing is sent to a deleted endpoint", len([r for r in received if r["path"] == "/ok"]) == n_before)
    audit = c.get("/admin/audit", headers=org, params={"event_id": eid, "format": "text"}).text
    chk("registration/removal are in the audit log", "webhook.subscribe" in audit and "webhook.delete" in audit)
finally:
    for h in c.get("/webhooks", headers=org).json():
        c.delete(f"/webhooks/{h['id']}", headers=org)
    c.delete(f"/events/{eid}", headers=org)
    srv.shutdown()

print(f"\nRESULT: {ok} passed, {bad} failed")
sys.exit(1 if bad else 0)
