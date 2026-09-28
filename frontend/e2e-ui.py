"""Browser-level UI sweep against the running docker stack (web on :3000, proxied /api).

Run: python frontend/e2e-ui.py     (needs `pip install playwright` + system Chrome)
For each role it signs in through the real login form, visits every page, and records
page errors, console errors and failing /api calls. Expected 401/403 gates are reported
separately from real failures (5xx, JS exceptions, network errors).
"""
import json
import re
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8")
from playwright.sync_api import sync_playwright

WEB = "http://localhost:3000"
API = "http://localhost:8000"


def jget(path):
    return json.load(urllib.request.urlopen(API + path))


def _n(eid):
    try:
        return jget(f"/embed/{eid}/gallery?limit=1")["total"]
    except Exception:
        return -1


E = max((e["id"] for e in jget("/events")), key=_n)  # the event with the most projects (the official fixture)
S = jget(f"/events/{E}/submissions")[0]["id"]
tracks = jget(f"/events/{E}/tracks")
TEAM_ID = "00000000-0000-0000-0000-000000000000"

PAGES = ["/", "/login", "/signup", "/events", "/events/new", "/admin/audit", f"/embed/{E}", f"/join/{TEAM_ID}",
         f"/submissions/{S}", f"/events/{E}", f"/events/{E}/assign", f"/events/{E}/audit", f"/events/{E}/data",
         f"/events/{E}/gallery", f"/events/{E}/judge", f"/events/{E}/judge/duel", f"/events/{E}/judge/{S}",
         f"/events/{E}/progress", f"/events/{E}/results", f"/events/{E}/rubric", f"/events/{E}/settings",
         f"/events/{E}/submit", f"/events/{E}/team", f"/events/{E}/vote", f"/events/{E}/webhooks",
         f"/events/{E}/certificate/{TEAM_ID}"]

ROLES = {
    "visitor": None,
    "participant": ("participant1@dogfoodhack.com", "participant123"),
    "judge": ("judge1@dogfoodhack.com", "judge123"),
    "organizer": ("organizer@dogfoodhack.com", "organizer123"),
    "admin": ("admin@dogfoodhack.com", "admin123"),
}

problems = []
gates = {}

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)
    for role, creds in ROLES.items():
        ctx = browser.new_context(viewport={"width": 1366, "height": 900})
        page = ctx.new_page()
        cur = {"url": ""}
        page.on("pageerror", lambda e, r=role, c=cur: problems.append((r, c["url"], "JS exception", str(e)[:200])))
        page.on("console", lambda m, r=role, c=cur: m.type == "error" and not re.search(r"status of (401|403|404)", m.text)
                and problems.append((r, c["url"], "console.error", m.text[:200])))

        def on_resp(resp, r=role, c=cur):
            if "/api/" in resp.url and resp.status >= 400:
                key = (resp.request.method, re.sub(r"[0-9a-f]{8}-[0-9a-f-]{27}", "{id}", resp.url.split("/api")[1]), resp.status)
                if resp.status in (401, 403, 404, 501):
                    gates.setdefault(key, set()).add(r)
                else:
                    problems.append((r, c["url"], f"HTTP {resp.status}", f"{key[0]} {key[1]}"))
        page.on("response", on_resp)
        page.on("requestfailed", lambda rq, r=role, c=cur: "_rsc=" not in rq.url and problems.append((r, c["url"], "request failed", rq.url[:120])))

        if creds:
            cur["url"] = "/login"
            page.goto(WEB + "/login")
            page.fill('input[type="email"]', creds[0])
            page.fill('input[type="password"]', creds[1])
            page.click("button.btn-primary")
            try:
                page.wait_for_function("localStorage.getItem('verdict.token')", timeout=8000)
            except Exception:
                problems.append((role, "/login", "login did not store token", ""))
        for path in PAGES:
            cur["url"] = path
            try:
                resp = page.goto(WEB + path, wait_until="networkidle", timeout=20000)
                page.wait_for_timeout(400)
                body = page.inner_text("body")
                if resp and resp.status >= 500:
                    problems.append((role, path, f"page HTTP {resp.status}", ""))
                if re.search(r"Application error|Unhandled Runtime Error|Something went wrong", body, re.I):
                    problems.append((role, path, "error boundary rendered", body[:120].replace("\n", " ")))
            except Exception as e:
                problems.append((role, path, "navigation failed", str(e)[:150]))
        ctx.close()
    browser.close()

print(f"pages per role: {len(PAGES)}, roles: {len(ROLES)}")
print("\n== expected gates (401/403/404/501 from /api) ==")
for (m, u, s), roles in sorted(gates.items()):
    print(f"  {s} {m} {u}  <- {','.join(sorted(roles))}")
print("\n== PROBLEMS ==")
seen = set()
for pr in problems:
    if pr in seen:
        continue
    seen.add(pr)
    print("  ", pr)
print(f"\n{len(seen)} problem(s)")
sys.exit(1 if seen else 0)
