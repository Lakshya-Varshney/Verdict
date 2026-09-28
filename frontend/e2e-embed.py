"""Embed widget, tested the way a third party would use it: from a *different origin*.

Run: python frontend/e2e-embed.py     (docker stack up; needs playwright + system Chrome)
"""
import http.server
import json
import re
import socketserver
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

API, WEB, BLOG_PORT = "http://localhost:8000", "http://localhost:3000", 9099
def _total(eid):
    return json.load(urllib.request.urlopen(f"{API}/embed/{eid}/gallery?limit=1"))["total"]


# the event with the most projects (the official 40-project fixture event)
E = max((e["id"] for e in json.load(urllib.request.urlopen(API + "/events"))), key=_total)
total = _total(E)

site = Path(tempfile.mkdtemp())
(site / "direct.html").write_text(f'<h1>My blog</h1><p>before</p><script src="{API}/embed.js" data-event="{E}" data-limit="12"></script><p id="after">after</p>')
(site / "proxy.html").write_text(f'<script src="{WEB}/api/embed.js" data-event="{E}" data-limit="6" data-theme="dark"></script>')
(site / "fetch.html").write_text("<p>x</p>")


class Quiet(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(site), **k)

    def log_message(self, *a):
        pass


srv = socketserver.TCPServer(("127.0.0.1", BLOG_PORT), Quiet)
threading.Thread(target=srv.serve_forever, daemon=True).start()

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))


with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)

    # 1. script tag from another origin, straight from the API
    ctx = b.new_context()
    pg = ctx.new_page()
    errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)[:120]))
    pg.on("console", lambda m: m.type == "error" and "favicon" not in m.text and "404" not in m.text and errs.append(m.text[:120]))
    pg.goto(f"http://localhost:{BLOG_PORT}/direct.html")
    pg.wait_for_selector("iframe", timeout=10000)
    fr = pg.frame_locator("iframe")
    fr.locator("a.card").first.wait_for(timeout=10000)
    n = fr.locator("a.card").count()
    check("script tag renders an iframe with cards", n == min(12, total), f"{n} cards (total {total})")
    pg.wait_for_timeout(600)
    h = pg.evaluate("document.querySelector('iframe').getBoundingClientRect().height")
    check("iframe auto-resizes to its content (postMessage)", h > 480, f"height {h:.0f}px")
    order = pg.evaluate("[...document.body.children].map(e=>e.tagName)")
    check("iframe inserted right after the script tag", order.index("IFRAME") == order.index("SCRIPT") + 1, str(order))
    first = fr.locator("a.card .name").first.inner_text()
    check("cards show real project names", len(first) > 2, first)
    href = fr.locator("a.card").first.get_attribute("href")
    check("card links go to the public project page", re.search(r"/submissions/[0-9a-f-]{36}$", href or ""), href)
    check("no page/console errors on the host page", not errs, str(errs))

    # 2. third-party JS fetches the JSON cross-origin (CORS *), with a custom header (forces a preflight)
    # a custom header forces a CORS preflight; if CORS were wrong, fetch() would reject instead of returning
    res = pg.evaluate("""async (u) => { try { const r = await fetch(u, {headers: {'X-Widget-Version': '1'}});
        const j = await r.json(); return {status: r.status, n: j.items.length, total: j.total}; } catch (e) { return {error: String(e)}; } }""",
                      f"{API}/embed/{E}/gallery?limit=5")
    check("cross-origin fetch works incl. preflight (CORS *)", res.get("status") == 200 and res.get("n") == 5, str(res))
    ctx.close()

    # 3. the same snippet through the web proxy (what the organizer UI hands out), dark theme
    ctx = b.new_context()
    pg = ctx.new_page()
    pg.goto(f"http://localhost:{BLOG_PORT}/proxy.html")
    pg.wait_for_selector("iframe", timeout=10000)
    fr = pg.frame_locator("iframe")
    fr.locator("a.card").first.wait_for(timeout=10000)
    check("works through the web proxy (/api/embed.js)", fr.locator("a.card").count() == 6)
    check("theme=dark applied", fr.locator("html.dark").count() == 1)
    ctx.close()

    # 4. organizer UI hands out the script snippet; /backend-docs still reaches working docs
    ctx = b.new_context()
    pg = ctx.new_page()
    pg.goto(WEB + "/login")
    pg.fill('input[type="email"]', "organizer@dogfoodhack.com")
    pg.fill('input[type="password"]', "organizer123")
    pg.click("button.btn-primary")
    pg.wait_for_function("localStorage.getItem('verdict.token')")
    pg.goto(f"{WEB}/events/{E}/data", wait_until="networkidle")
    snippet = pg.locator("code").first.inner_text()
    check("organizer data page shows the one-line snippet", "embed.js" in snippet and E in snippet, snippet[:120])
    pg.frame_locator("iframe[title='Embed preview']").locator("a.card").first.wait_for(timeout=10000)
    check("embed preview renders in the UI", True)
    ctx.close()

    ctx = b.new_context()
    pg = ctx.new_page()
    blocked = []
    pg.route("**/*", lambda r: r.continue_() if re.match(r"https?://localhost", r.request.url) else (blocked.append(r.request.url), r.abort()))
    pg.goto(WEB + "/backend-docs", wait_until="networkidle")
    pg.wait_for_selector(".opblock", timeout=15000)
    check("/backend-docs redirects to working offline Swagger UI", pg.locator(".opblock").count() >= 40 and "/api/docs" in pg.url and not blocked,
          f"{pg.locator('.opblock').count()} ops at {pg.url}")
    ctx.close()
    b.close()

srv.shutdown()
w = max(len(n) for n, *_ in results)
for n, ok, d in results:
    print(("PASS " if ok else "FAIL ") + n.ljust(w) + "  " + str(d)[:110])
sys.exit(0 if all(ok for _, ok, _ in results) else 1)
