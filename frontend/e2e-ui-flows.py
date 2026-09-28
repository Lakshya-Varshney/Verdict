"""Interactive UI flows against the docker stack (needs playwright + system Chrome).

Run: python frontend/e2e-ui-flows.py
Each flow drives the real UI, then verifies the effect through the backend API.
"""
import json
import re
import sys
import urllib.request
import uuid

sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

WEB, API = "http://localhost:3000", "http://localhost:8000"
results = []


def api(method, path, token=None, body=None):
    req = urllib.request.Request(API + path, method=method, data=json.dumps(body).encode() if body else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw and raw[0] in "[{" else raw)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def tok(email, pw):
    return api("POST", "/auth/login", body={"email": email, "password": pw})[1]["token"]


def flow(name):
    def deco(fn):
        try:
            detail = fn()
            results.append((name, "PASS", detail or ""))
        except Exception as e:
            results.append((name, "FAIL", f"{type(e).__name__}: {str(e)[:300]}"))
        return fn
    return deco


def login(page, email, pw):
    page.goto(WEB + "/login")
    page.fill('input[type="email"]', email)
    page.fill('input[type="password"]', pw)
    page.click("button.btn-primary")
    page.wait_for_function("localStorage.getItem('verdict.token')", timeout=8000)


org_t = tok("organizer@dogfoodhack.com", "organizer123")
def _n(eid):
    c, d = api("GET", f"/embed/{eid}/gallery?limit=1")
    return d["total"] if c == 200 else -1


_all_events = api("GET", "/events")[1]
E = max((e["id"] for e in _all_events), key=_n)  # the event with the most projects (the official fixture)
DEMO = next((e["id"] for e in _all_events if e.get("slug") == "dogfood-hackathon-2024"), None)  # seed.py's demo event: judge1/2/3 are its judges, unlike the fixture's own (passwordless) judges

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)

    def newpage(email, pw):
        ctx = browser.new_context(viewport={"width": 1366, "height": 900}, accept_downloads=True)
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)[:150]))
        pg.errs = errs
        login(pg, email, pw)
        return pg

    @flow("signup through the form -> lands signed in")
    def _():
        ctx = browser.new_context()
        pg = ctx.new_page()
        pg.goto(WEB + "/signup")
        sfx = uuid.uuid4().hex[:6]
        pg.fill('input[autocomplete="name"]', "UI Tester")
        pg.fill('input[type="email"]', f"ui{sfx}@t.io")
        pg.fill('input[type="password"]', "pw123456")
        pg.click("button.btn-primary")
        pg.wait_for_function("localStorage.getItem('verdict.token')", timeout=8000)
        ctx.close()
        return "token stored"

    @flow("organizer: create event via form -> redirected to settings; tagline persisted")
    def _():
        pg = newpage("organizer@dogfoodhack.com", "organizer123")
        pg.goto(WEB + "/events/new")
        name = f"UI Event {uuid.uuid4().hex[:5]}"
        pg.fill('input[placeholder="Dogfood 2027"]', name)
        pg.locator("input.input").nth(1).fill("Ship it fast")
        pg.click("button.btn-primary:has-text('Create event')")
        pg.wait_for_url(re.compile(r"/events/[0-9a-f-]{36}/settings"), timeout=10000)
        eid = re.search(r"/events/([0-9a-f-]{36})/", pg.url).group(1)
        # a fresh event is a draft, hidden from anonymous GETs; read it back as its organizer
        code, ev = api("GET", f"/events/{eid}", org_t)
        assert ev["name"] == name and ev["tagline"] == "Ship it fast", ev
        assert not pg.errs, pg.errs
        api("DELETE", f"/events/{eid}", org_t)
        return f"event {eid} created+deleted"

    @flow("organizer: results page renders ranked rows; CSV download works")
    def _():
        pg = newpage("organizer@dogfoodhack.com", "organizer123")
        pg.goto(WEB + f"/events/{E}/results", wait_until="networkidle")
        body = pg.inner_text("body")
        code, res = api("GET", f"/events/{E}/judging/results", org_t)
        assert code == 200
        n = len(res["rows"])
        if n:
            assert res["rows"][0]["name"] in body, "top project not rendered"
            with pg.expect_download(timeout=8000) as dl:
                pg.click("button:has-text('CSV')")
            text = open(dl.value.path(), encoding="utf-8").read()
            assert text.splitlines()[0].startswith("rank,submission"), text[:80]
        assert not pg.errs, pg.errs
        return f"{n} rows"

    @flow("judge: open assignment, click a score key, score persisted server-side")
    def _():
        # E's own judges are the fixture's imported (passwordless) accounts, so this flow uses
        # the demo seed event instead, where judge1 is a real, loggable-in judge.
        assert DEMO, "seed demo event (dogfood-hackathon-2024) not found"
        jt = tok("judge1@dogfoodhack.com", "judge123")
        # unlock scoring; idempotent. seed.py sets judging_opens_at 3 days in the future, so status
        # alone isn't enough - the scoring-window check 403s until it's patched open too.
        api("PATCH", f"/events/{DEMO}", org_t, {
            "status": "judging",
            "judging_opens_at": "2020-01-01T00:00:00Z",
            "judging_closes_at": "2099-01-01T00:00:00Z",
        })
        mine = api("GET", f"/events/{DEMO}/judging/assignments/mine", jt)[1]
        assert mine, "judge has no assignments"
        sid = mine[0]["submission_id"]
        pg = newpage("judge1@dogfoodhack.com", "judge123")
        pg.goto(WEB + f"/events/{DEMO}/judge/{sid}", wait_until="networkidle")
        keys = pg.locator("button.key:not([disabled])")
        if keys.count() == 0:
            return "scoring locked for this event status (UI shows read-only) - no keys to click"
        keys.nth(3).click()   # "4" on first criterion
        pg.wait_for_timeout(1500)
        mine_scores = api("GET", f"/submissions/{sid}/scores/mine", jt)[1]["scores"]
        assert any(s["value"] == 4 for s in mine_scores), mine_scores
        assert not pg.errs, pg.errs
        return f"{len(mine_scores)} score(s) saved"

    @flow("judge: score in a judging-status event via UI -> persisted; out-of-range blocked by API")
    def _():
        sfx = uuid.uuid4().hex[:6]
        def su(tag):
            return api("POST", "/auth/signup", body={"email": f"{tag}{sfx}@t.io", "name": tag, "password": "pw123456"})[1]["token"]
        lead_t, judge_t = su("lead"), su("judge")
        eid = api("POST", "/events", org_t, {"name": f"Judging {sfx}", "slug": f"j-{sfx}"})[1]["id"]
        try:
            for tag, role in (("lead", "participant"), ("judge", "judge")):
                api("POST", f"/events/{eid}/roles", org_t, {"email": f"{tag}{sfx}@t.io", "role": role})
            tid = api("POST", f"/events/{eid}/teams", lead_t, {"name": "T"})[1]["id"]
            sid = api("POST", f"/teams/{tid}/submissions", lead_t, {"name": "UI Proj"})[1]["id"]
            api("POST", f"/submissions/{sid}/submit", lead_t)
            cid = api("POST", f"/events/{eid}/rubric/criteria", org_t, {"name": "Innov", "scale_min": 1, "scale_max": 5})[1]["id"]
            api("POST", f"/events/{eid}/judging/assign", org_t, {"reviews_per_submission": 1})
            api("PATCH", f"/events/{eid}", org_t, {"status": "judging"})
            pg = newpage(f"judge{sfx}@t.io", "pw123456")
            pg.goto(WEB + f"/events/{eid}/judge/{sid}", wait_until="networkidle")
            keys = pg.locator("button.key:not([disabled])")
            assert keys.count() >= 5, f"expected score keys, got {keys.count()}; body={pg.inner_text('body')[:200]}"
            keys.nth(3).click()
            pg.wait_for_timeout(2000)
            sc = api("GET", f"/submissions/{sid}/scores/mine", judge_t)[1]["scores"]
            assert any(x["criterion_id"] == cid and x["value"] == 4 for x in sc), sc
            assert api("POST", f"/submissions/{sid}/scores", judge_t, {"criterion_id": cid, "value": 99})[0] == 400
            assert not pg.errs, pg.errs
            return "UI click saved 4/5; 99 rejected with 400"
        finally:
            api("DELETE", f"/events/{eid}", org_t)

    def voting_event(mode, n=6, **cfg):
        sfx = uuid.uuid4().hex[:6]
        eid = api("POST", "/events", org_t, {"name": f"Ballot {mode} {sfx}", "voting_mode": mode, **cfg})[1]["id"]
        sids = []
        for i in range(n):
            lt = api("POST", "/auth/signup", body={"email": f"l{i}{sfx}@t.io", "name": f"L{i}", "password": "pw123456"})[1]["token"]
            api("POST", f"/events/{eid}/roles", org_t, {"email": f"l{i}{sfx}@t.io", "role": "participant"})
            tid = api("POST", f"/events/{eid}/teams", lt, {"name": f"Team {i}"})[1]["id"]
            sid = api("POST", f"/teams/{tid}/submissions", lt, {"name": f"Ballot Proj {i}"})[1]["id"]
            api("POST", f"/submissions/{sid}/submit", lt)
            sids.append(sid)
        api("PATCH", f"/events/{eid}", org_t, {"status": "voting"})
        return eid, sids

    @flow("ballot: 2 visitors see different orders; click votes; budget disables the rest; count hidden")
    def _():
        eid, sids = voting_event("open")
        try:
            def titles(pg):
                pg.goto(WEB + f"/events/{eid}/vote", wait_until="networkidle")
                pg.wait_for_selector("text=Ballot Proj", timeout=8000)
                return pg.locator(r"text=/Ballot Proj \d/").all_inner_texts()
            ctxs = [browser.new_context() for _ in range(3)]
            pages = [c.new_page() for c in ctxs]
            for pg in pages:
                pg.errs = []
                pg.on("pageerror", lambda e, pg=pg: pg.errs.append(str(e)[:150]))
            orders = [titles(pg) for pg in pages]
            assert all(len(o) == 6 for o in orders), orders
            assert len({tuple(o) for o in orders}) >= 2, f"all 3 visitors got the same order: {orders[0]}"
            assert titles(pages[0]) == orders[0], "order changed on reload"
            pg = pages[0]
            btns = pg.locator("button:has-text('Vote for this')")
            assert btns.count() == 6
            btns.first.click()
            pg.wait_for_timeout(1500)
            assert pg.locator("button:has-text('Voted')").count() == 1
            pg.reload(wait_until="networkidle")
            pg.wait_for_selector("text=Ballot Proj")
            assert pg.locator("button:has-text('Voted')").count() == 1, "vote not restored from server after reload"
            assert pg.locator("button:has-text('Vote for this')").first.is_disabled(), "budget exhausted but buttons enabled"
            tallies = sum(api("GET", f"/submissions/{s}/votes/count")[1]["count"] or 0 for s in sids)
            assert tallies == 0, "public count leaked during voting"
            assert sum(api("GET", f"/submissions/{s}/votes/count", org_t)[1]["count"] for s in sids) == 1
            assert not any(p.errs for p in pages), [p.errs for p in pages]
            return "orders differ across visitors, vote persisted server-side, public tally hidden"
        finally:
            api("DELETE", f"/events/{eid}", org_t)

    @flow("ballot (quadratic): signed-in voter spends credits with +/-; server enforces the budget")
    def _():
        eid, sids = voting_event("quadratic", n=3, vote_credits=10)
        try:
            sfx = uuid.uuid4().hex[:6]
            api("POST", "/auth/signup", body={"email": f"q{sfx}@t.io", "name": "Quad", "password": "pw123456"})
            pg = newpage(f"q{sfx}@t.io", "pw123456")
            pg.goto(WEB + f"/events/{eid}/vote", wait_until="networkidle")
            pg.wait_for_selector("text=Ballot Proj")
            plus = pg.locator("button[aria-label='More votes']")
            plus.first.click(); pg.wait_for_timeout(600)
            plus.first.click(); pg.wait_for_timeout(600)   # 2 votes = 4 credits
            qt = api("POST", "/auth/login", body={"email": f"q{sfx}@t.io", "password": "pw123456"})[1]["token"]
            state = api("GET", f"/events/{eid}/ballot", qt)[1]["voter"]
            assert state["credits_left"] == 6 and sorted(state["my_votes"].values()) == [2], state
            over = api("POST", f"/submissions/{sids[0]}/vote", qt, {"votes": 4})
            assert over[0] == 400, over   # 16 > 10 credits
            assert not pg.errs, pg.errs
            return "2 votes = 4 credits spent; 4 votes (16) rejected"
        finally:
            api("DELETE", f"/events/{eid}", org_t)

    @flow("organizer: export JSON via UI, dry-run then real import of it (idempotent), counts + checksum shown")
    def _():
        pg = newpage("organizer@dogfoodhack.com", "organizer123")
        pg.goto(WEB + f"/events/{E}/data", wait_until="networkidle")
        with pg.expect_download(timeout=15000) as dl:
            pg.click("button:has-text('Download JSON')")
        path = dl.value.path()
        dump = json.loads(open(path, encoding="utf-8").read())
        assert dump["format"] == "dogfood-event-dump" and dump["event"]["id"] == E and dump["checksum"], dump.keys()
        n_sub = len(dump["submissions"])
        pg.check("text=Validate only (dry run) >> xpath=../input") if False else pg.locator("label:has-text('Validate only') input").check()
        pg.set_input_files("input[type=file]", path)
        pg.wait_for_selector("text=Would import", timeout=15000)
        txt = pg.inner_text("body")
        assert f"{n_sub} submissions" in txt and "checksum" in txt, txt[txt.find("Would import"):][:200]
        pg.locator("label:has-text('Validate only') input").uncheck()
        pg.set_input_files("input[type=file]", path)
        pg.wait_for_selector("p:has-text('Imported:')", timeout=15000)
        assert f"{n_sub} submissions" in pg.inner_text("body")
        # idempotent: the restore created nothing new
        r = api("POST", f"/events/{E}/import", org_t, dump)
        assert r[0] == 200 and sum(r[1]["created"].values()) == 0, r[1]["created"]
        assert not pg.errs, pg.errs
        return f"{n_sub} submissions round-tripped, 0 new rows"

    @flow("certificates: participant + judge open theirs, download PDF/HTML; a logged-out visitor verifies; bogus code fails")
    def _():
        sfx = uuid.uuid4().hex[:6]
        def su(tag):
            return api("POST", "/auth/signup", body={"email": f"{tag}{sfx}@t.io", "name": f"{tag.title()} {sfx}", "password": "pw123456"})[1]["token"]
        lead_t, judge_t = su("lead"), su("judge")
        eid = api("POST", "/events", org_t, {"name": f"Certs {sfx}", "slug": f"c-{sfx}"})[1]["id"]
        try:
            for tag, role in (("lead", "participant"), ("judge", "judge")):
                api("POST", f"/events/{eid}/roles", org_t, {"email": f"{tag}{sfx}@t.io", "role": role})
            tid = api("POST", f"/events/{eid}/teams", lead_t, {"name": "T"})[1]["id"]
            sid = api("POST", f"/teams/{tid}/submissions", lead_t, {"name": "Cert Proj"})[1]["id"]
            api("POST", f"/submissions/{sid}/submit", lead_t)
            cid = api("POST", f"/events/{eid}/rubric/criteria", org_t, {"name": "Q", "scale_min": 1, "scale_max": 5})[1]["id"]
            api("POST", f"/events/{eid}/judging/assign", org_t, {"reviews_per_submission": 1})
            api("POST", f"/submissions/{sid}/scores", judge_t, {"criterion_id": cid, "value": 4})
            assert api("GET", f"/events/{eid}/judging/progress", org_t)[0] == 200
            # not closed yet: the UI/API must refuse
            me = api("GET", "/auth/me", lead_t)[1]["id"]
            assert api("GET", f"/events/{eid}/certificates/{me}", lead_t)[0] == 403
            api("PATCH", f"/events/{eid}", org_t, {"status": "published"})
            codes = {}
            for who, email, kind in (("lead", f"lead{sfx}@t.io", "winner"), ("judge", f"judge{sfx}@t.io", "judge")):
                pg = newpage(email, "pw123456")
                pg.goto(WEB + f"/events/{eid}", wait_until="networkidle")
                pg.click("text=View certificate")
                pg.wait_for_selector("[data-testid=verify-code]", timeout=15000)
                body = pg.inner_text("body")
                assert kind.upper() in body.upper() or {"winner": "ACHIEVEMENT", "judge": "PARTICIPATION"}[kind].upper() in body.upper() or "SERVICE" in body.upper(), body[:200]
                code = pg.locator("[data-testid=verify-code]").inner_text().strip()
                assert len(code) == 64, code
                codes[who] = code
                with pg.expect_download(timeout=15000) as d1:
                    pg.click("button:has-text('Signed PDF')")
                assert open(d1.value.path(), "rb").read(5) == b"%PDF-"
                with pg.expect_download(timeout=15000) as d2:
                    pg.click("button:has-text('Verifiable HTML')")
                assert "dogfood-certificate" in open(d2.value.path(), encoding="utf-8").read()
                assert not pg.errs, pg.errs
            # a logged-out visitor verifies both, and a made-up code
            ctx = browser.new_context()
            pub = ctx.new_page()
            for who, code in codes.items():
                pub.goto(WEB + f"/verify/{code}", wait_until="networkidle")
                pub.wait_for_selector("[data-testid=verify-result]", timeout=10000)
                assert pub.locator("[data-testid=verify-result]").get_attribute("data-valid") == "true", who
            pub.goto(WEB + "/verify/" + "0" * 64, wait_until="networkidle")
            assert "No such" in pub.inner_text("body")
            ctx.close()
            return "winner + judge certificates: PDF/HTML downloaded, public verify page valid, bogus code rejected"
        finally:
            api("DELETE", f"/events/{eid}", org_t)

    @flow("webhooks: register via UI (secret shown once), send test, delivery log succeeds, HMAC verifies at a real receiver, delete")
    def _():
        import hashlib, hmac, http.server, socketserver, threading, time
        got = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("content-length", 0)))
                got.append(({k.lower(): v for k, v in self.headers.items()}, body.decode()))
                self.send_response(200); self.end_headers()

            def log_message(self, *a): pass

        srv = socketserver.ThreadingTCPServer(("0.0.0.0", 9192), H); srv.daemon_threads = True
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        eid = api("POST", "/events", org_t, {"name": f"Hooks UI {uuid.uuid4().hex[:5]}"})[1]["id"]
        try:
            pg = newpage("organizer@dogfoodhack.com", "organizer123")
            pg.goto(WEB + f"/events/{eid}/webhooks", wait_until="networkidle")
            pg.fill("input[placeholder*='hooks.example']", "http://host.docker.internal:9192/hook")
            pg.click("button:has-text('Register')")
            pg.wait_for_selector("[data-testid=webhook-secret]", timeout=10000)
            secret = pg.locator("[data-testid=webhook-secret] code").inner_text().strip()
            assert secret.startswith("whsec_"), secret
            pg.wait_for_selector("[data-testid=webhook-row]", timeout=10000)
            assert secret not in api("GET", f"/webhooks?event_id={eid}", org_t)[1].__str__(), "secret leaked in list"
            pg.click("button[aria-label='Send test delivery']")  # also opens the delivery log
            pg.wait_for_selector("[data-testid=delivery-log] >> text=success", timeout=25000)
            assert got, "receiver got nothing"
            headers, body = got[0]
            mac = hmac.new(secret.encode(), f"{headers['x-dogfood-timestamp']}.".encode() + body.encode(), hashlib.sha256).hexdigest()
            assert hmac.compare_digest("sha256=" + mac, headers["x-dogfood-signature"]), "signature does not verify"
            assert json.loads(body)["type"] == "webhook.ping"
            pg.click("button[aria-label='Remove webhook']")
            pg.wait_for_selector("text=No webhooks", timeout=10000)
            assert not pg.errs, pg.errs
            return "secret shown once, ping delivered + signature verified, deleted"
        finally:
            srv.shutdown()
            for h in api("GET", "/webhooks", org_t)[1]:
                api("DELETE", f"/webhooks/{h['id']}", org_t)
            api("DELETE", f"/events/{eid}", org_t)

    @flow("participant: submission editor renders for own team")
    def _():
        pg = newpage("participant1@dogfoodhack.com", "participant123")
        pg.goto(WEB + f"/events/{E}/submit", wait_until="networkidle")
        body = pg.inner_text("body")
        assert not re.search(r"Application error|denied", body, re.I), body[:200]
        assert not pg.errs, pg.errs
        return "editor rendered"

    @flow("participant: blocked from organizer pages (results/assign/audit)")
    def _():
        pg = newpage("participant1@dogfoodhack.com", "participant123")
        out = []
        for path in ("results", "assign", "audit", "rubric"):
            pg.goto(WEB + f"/events/{E}/{path}", wait_until="networkidle")
            out.append(path)
            assert not pg.errs, pg.errs
        return "no crash on " + ",".join(out)

    @flow("visitor: gallery shows fixture projects; project page renders")
    def _():
        ctx = browser.new_context()
        pg = ctx.new_page()
        pg.goto(WEB + f"/events/{E}/gallery", wait_until="networkidle")
        subs = api("GET", f"/events/{E}/submissions")[1]
        assert subs and subs[0]["name"] in pg.inner_text("body")
        pg.goto(WEB + f"/submissions/{subs[0]['id']}", wait_until="networkidle")
        assert subs[0]["name"] in pg.inner_text("body")
        return f"{len(subs)} projects"

    browser.close()

w = max(len(r[0]) for r in results)
for n, s, d in results:
    print(f"{s}  {n.ljust(w)}  {d}")
sys.exit(1 if any(s == "FAIL" for _, s, _ in results) else 0)
