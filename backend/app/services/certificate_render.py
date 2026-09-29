"""Render a signed certificate as a PDF (reportlab) or a self-contained, verifiable HTML page.

Design: VERDICT's own "Board" theme (see frontend/src/app/globals.css) - dark, split-flap
departures-board palette, not a copy of any external template. The layout borrows a few good
ideas from printed hackathon certificates in general (tracked caps, a divider with a center dot,
a colored place badge, corner registration marks, a structured footer) but the type, color and
signatory block are VERDICT's own: the cryptographic Ed25519 signature stands in for a human
signatory, which is the honest thing for a document a server issues, not a person.
"""

import html
import io
import json
import os

from app.config import settings

TITLES = {"participant": "Certificate of Participation", "judge": "Judge Participation Record", "winner": "Certificate of Achievement"}

_FONT_DIR = os.path.join(os.path.dirname(__file__), "..", "static", "fonts")
_UNICODE_FONT_REGISTERED = False


def _register_unicode_fonts() -> bool:
    """Register the vendored Noto Sans (Regular/Bold) once, for the recipient name and event
    name only - the two fields most likely to hold a script outside Latin-1. Covers Latin
    Extended, Cyrillic, Greek and Vietnamese; CJK is not included (that needs a much larger,
    script-specific font) and still falls back to `_latin1()`'s '?' degradation. Every other
    string on the page (detail line, footer, verification code/URL) stays on the built-in
    Latin-1 fonts on purpose: those are checked byte-for-byte by tests and by anyone diffing
    the PDF, and a TrueType font embeds glyphs by id, not by character code."""
    global _UNICODE_FONT_REGISTERED
    if _UNICODE_FONT_REGISTERED:
        return True
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        pdfmetrics.registerFont(TTFont("NotoSans", os.path.join(_FONT_DIR, "NotoSans-Regular.ttf")))
        pdfmetrics.registerFont(TTFont("NotoSans-Bold", os.path.join(_FONT_DIR, "NotoSans-Bold.ttf")))
        _UNICODE_FONT_REGISTERED = True
    except Exception:
        _UNICODE_FONT_REGISTERED = False
    return _UNICODE_FONT_REGISTERED


def _has_glyphs(text: str, font: str) -> bool:
    """True if every character in `text` (ignoring spaces) has a glyph in `font` - so a name
    with characters the vendored font can't draw (CJK, Arabic, ...) falls back cleanly instead
    of rendering as tofu boxes."""
    from reportlab.pdfbase.pdfmetrics import getFont

    cmap = getFont(font).face.charWidths  # any dict keyed by codepoint works as a coverage check
    return all(ord(c) in cmap for c in text if c != " ")

# The big on-page headline word for each kind - separate from TITLES (which stays put; it only
# feeds document metadata and the verify page's own heading).
_KIND_WORD = {"participant": "PARTICIPATION", "judge": "SERVICE", "winner": "ACHIEVEMENT"}

# VERDICT "Board" theme tokens (frontend/src/app/globals.css :root), as 0..1 RGB for reportlab.
_BG = (0.039, 0.035, 0.031)  # --bg      #0a0908
_LINE = (0.169, 0.153, 0.118)  # --line    #2b271e
_LINE2 = (0.239, 0.220, 0.161)  # --line2   #3d3829
_INK = (0.949, 0.922, 0.851)  # --ink     #f2ebd9
_INK2 = (0.725, 0.694, 0.612)  # --ink2    #b9b19c
_INK3 = (0.498, 0.471, 0.408)  # --ink3    #7f7868
_AMBER = (1.000, 0.722, 0.110)  # --amber   #ffb81c
_SIGNAL = (1.000, 0.353, 0.169)  # --signal  #ff5a2b
_ON_AMBER = (0.086, 0.067, 0.039)  # --on-amber #16110a


def _ordinal(n: int) -> str:
    return {1: "1ST", 2: "2ND", 3: "3RD"}.get(n, f"{n}TH")


def _track(s: str) -> str:
    """Letter-spaced caps for short, fixed labels only - never for user content or verification
    strings (tracking a long or adversarial string would blow past `_fit`'s width budget)."""
    return " ".join(s)


def verify_urls(code: str) -> tuple[str, str]:
    return f"{settings.PUBLIC_WEB_URL.rstrip('/')}/verify/{code}", f"{settings.PUBLIC_API_URL.rstrip('/')}/verify/{code}"


_PUNCT = str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-", "…": "..."})


def _latin1(text: str) -> str:
    """The built-in PDF fonts are Latin-1: typographic punctuation is straightened, anything else non-Latin-1
    degrades to '?' (the JSON and HTML forms keep the full, exact text)."""
    return text.translate(_PUNCT).encode("latin-1", "replace").decode("latin-1")


def _fit(text: str, font: str, size: float, max_width: float, min_size: float = 12) -> float:
    """Largest font size <= `size` at which `text` fits in `max_width` (so long names never leave the page)."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    while size > min_size and stringWidth(text, font, size) > max_width:
        size -= 1
    return size


def _best_font(text: str, unicode_font: str, latin1_font: str) -> tuple[str, str]:
    """(text_to_draw, font_name): the raw text on the vendored Unicode font if every character
    in it has a glyph there, else the Latin-1-straightened text on the built-in font (the
    original behaviour). Only for display fields - never for text a test or verifier matches
    byte-for-byte (see `_register_unicode_fonts`)."""
    if _register_unicode_fonts() and _has_glyphs(text, unicode_font):
        return text, unicode_font
    return _latin1(text), latin1_font


def render_pdf(payload: dict, signature: str, code: str, key_id: str) -> bytes:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.utils import simpleSplit
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    w, h = landscape(A4)
    # invariant: byte-identical output for the same input; uncompressed so the code/URL are plain text in the file
    c = canvas.Canvas(buf, pagesize=(w, h), invariant=1, pageCompression=0)
    c.setTitle(f"{TITLES[payload['kind']]} - {_latin1(payload['recipient']['name'])}")
    c.setAuthor("VERDICT")
    c.setSubject("Digitally signed (Ed25519). Verify at " + verify_urls(code)[0])

    c.setFillColorRGB(*_BG)
    c.rect(0, 0, w, h, stroke=0, fill=1)

    # corner registration marks
    inset, arm = 34, 28
    c.setStrokeColorRGB(*_AMBER)
    c.setLineWidth(1.2)
    for x0, dx in ((inset, 1), (w - inset, -1)):
        for y0, dy in ((inset, 1), (h - inset, -1)):
            c.line(x0, y0, x0, y0 + arm * dy)
            c.line(x0, y0, x0 + arm * dx, y0)

    top = h - 66
    c.setFont("Helvetica", 8)
    c.setFillColorRGB(*_INK3)
    c.drawCentredString(w / 2, top, _track("VERDICT"))

    event_line, event_font = _best_font(payload["event"]["name"].upper(), "NotoSans-Bold", "Helvetica-Bold")
    size = _fit(event_line, event_font, 22, w - 160, 6)
    c.setFont(event_font, size)
    c.setFillColorRGB(*_AMBER)
    c.drawCentredString(w / 2, top - 27, event_line)

    ry = top - 52
    c.setStrokeColorRGB(*_LINE2)
    c.setLineWidth(0.75)
    c.line(w / 2 - 140, ry, w / 2 - 10, ry)
    c.line(w / 2 + 10, ry, w / 2 + 140, ry)
    c.setFillColorRGB(*_AMBER)
    c.circle(w / 2, ry, 2.2, stroke=0, fill=1)

    c.setFont("Times-Italic", 12)
    c.setFillColorRGB(*_INK2)
    c.drawCentredString(w / 2, ry - 28, "Certificate of")

    kind_word = _KIND_WORD[payload["kind"]]
    c.setFont("Helvetica-Bold", 21)
    c.setFillColorRGB(*_INK)
    c.drawCentredString(w / 2, ry - 52, _track(kind_word))

    y = ry - 52
    rec = payload.get("record") or {}
    if payload["kind"] == "winner" and rec.get("place"):
        label = f"PLACED {_ordinal(rec['place'])} OF {rec.get('projects_ranked', '?')}"
        bw = stringWidth(label, "Helvetica-Bold", 13) + 56
        bx, by = w / 2 - bw / 2, y - 40
        c.setFillColorRGB(*_SIGNAL)
        c.rect(bx, by, bw, 24, stroke=0, fill=1)
        c.setFillColorRGB(*_ON_AMBER)
        c.setFont("Helvetica-Bold", 13)
        c.drawCentredString(w / 2, by + 7, label)
        y = by
    else:
        y -= 16

    c.setFont("Times-Italic", 11)
    c.setFillColorRGB(*_INK3)
    c.drawCentredString(w / 2, y - 34, "- awarded to -")

    name, name_font = _best_font(payload["recipient"]["name"], "NotoSans-Bold", "Helvetica-Bold")
    size = _fit(name, name_font, 42, w - 140)
    c.setFont(name_font, size)
    c.setFillColorRGB(*_INK)
    c.drawCentredString(w / 2, y - 74, name)

    dy = y - 96
    c.setStrokeColorRGB(*_LINE)
    c.setLineWidth(0.6)
    c.line(w / 2 - 160, dy, w / 2 + 160, dy)

    c.setFont("Times-Italic", 12.5)
    c.setFillColorRGB(*_INK2)
    yy = dy - 24
    line = _latin1(f"{payload['detail']} at {payload['event']['name']}.")
    for part in simpleSplit(line, "Times-Italic", 12.5, w - 220):
        c.drawCentredString(w / 2, yy, part)
        yy -= 17

    if payload["kind"] == "judge" and rec:
        c.setFont("Courier", 9)
        c.setFillColorRGB(*_INK3)
        c.drawCentredString(
            w / 2, yy - 8,
            f"{rec['projects_reviewed']} projects reviewed  //  {rec['criterion_scores']} criterion scores  //  "
            f"{rec['first_review'][:10]} to {rec['last_review'][:10]}",
        )

    # footer
    fx1, fx2, fy = 62, w - 62, 78
    c.setFont("Helvetica", 7.5)
    c.setFillColorRGB(*_INK3)
    c.drawString(fx1, fy + 16, _track("ISSUED"))
    c.setFont("Helvetica", 12)
    c.setFillColorRGB(*_INK)
    c.drawString(fx1, fy, payload["issued_at"][:10])

    c.setFont("Courier", 7.5)
    c.setFillColorRGB(*_INK3)
    c.drawCentredString(w / 2, fy + 52, "VERDICT // OPEN HACKATHON PLATFORM // DIGITALLY SIGNED")

    web, api = verify_urls(code)
    c.setFont("Helvetica-Bold", 8)
    c.setFillColorRGB(*_AMBER)
    c.drawRightString(fx2, fy + 34, "Ed25519 signature")
    c.setFont("Courier", 7.5)
    c.setFillColorRGB(*_INK2)
    c.drawRightString(fx2, fy + 20, f"code {code}")
    c.drawRightString(fx2, fy + 9, web)
    c.setFillColorRGB(*_INK3)
    c.drawRightString(fx2, fy - 3, f"key {key_id}   sig {signature[:40]}...")

    c.setFont("Helvetica", 6.8)
    c.setFillColorRGB(*_INK3)
    c.drawCentredString(w / 2, 40, "Anyone can verify this document offline against the public key at " + api.rsplit("/verify/", 1)[0] + "/.well-known/dogfood-signing-key")

    c.showPage()
    c.save()
    return buf.getvalue()


def render_html(payload: dict, signature: str, code: str, key_id: str, algorithm: str) -> str:
    e = html.escape
    web, api = verify_urls(code)
    rec = payload.get("record") or {}
    kind = payload["kind"]
    extra = ""
    if kind == "judge" and rec:
        extra = (
            f'<p class="rec">{rec["projects_reviewed"]} projects reviewed &middot; {rec["criterion_scores"]} criterion scores &middot; '
            f'{e(rec["first_review"][:10])} to {e(rec["last_review"][:10])}</p>'
        )
    badge = ""
    if kind == "winner" and rec.get("place"):
        badge = f'<div class="badge">Placed {e(_ordinal(rec["place"]))} of {e(str(rec.get("projects_ranked", "?")))}</div>'

    doc = {"payload": payload, "signature": signature, "key_id": key_id, "algorithm": algorithm}
    embedded = json.dumps(doc, ensure_ascii=False, sort_keys=True).replace("<", "\\u003c")  # cannot close the script tag

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(TITLES[kind])} &middot; {e(payload['recipient']['name'])}</title>
<style>
:root{{--bg:#0a0908;--panel:#100e0b;--line:#2b271e;--line2:#3d3829;--ink:#f2ebd9;--ink2:#b9b19c;--ink3:#7f7868;--amber:#ffb81c;--signal:#ff5a2b;--on-amber:#16110a}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);font:16px/1.6 Georgia,'Times New Roman',serif;color:var(--ink);padding:32px 16px;display:flex;justify-content:center}}
.sheet{{position:relative;max-width:880px;width:100%;background:var(--panel);border:1px solid var(--line);padding:56px 40px;text-align:center;overflow:hidden}}
.tick{{position:absolute;width:26px;height:26px;border:1.5px solid var(--amber)}}
.tick.tl{{top:14px;left:14px;border-right:0;border-bottom:0}}.tick.tr{{top:14px;right:14px;border-left:0;border-bottom:0}}
.tick.bl{{bottom:14px;left:14px;border-right:0;border-top:0}}.tick.br{{bottom:14px;right:14px;border-left:0;border-top:0}}
.kicker{{font:11px/1 'Courier New',monospace;letter-spacing:.35em;text-transform:uppercase;color:var(--ink3)}}
.event{{margin-top:10px;font-family:Arial,Helvetica,sans-serif;font-weight:800;letter-spacing:.03em;text-transform:uppercase;color:var(--amber);font-size:clamp(17px,3vw,26px);word-break:break-word}}
.rule{{display:flex;align-items:center;gap:10px;margin:22px auto 20px;max-width:360px}}
.rule::before,.rule::after{{content:"";flex:1;height:1px;background:var(--line2)}}
.rule .dot{{width:5px;height:5px;border-radius:50%;background:var(--amber);flex:none}}
.kind-kicker{{font-style:italic;color:var(--ink2);font-size:14px}}
.kind{{margin-top:6px;font-family:Arial,Helvetica,sans-serif;font-weight:800;letter-spacing:.15em;text-transform:uppercase;font-size:21px;color:var(--ink)}}
.badge{{display:inline-block;margin:18px auto 2px;padding:7px 20px;background:var(--signal);color:var(--on-amber);font-family:Arial,Helvetica,sans-serif;font-weight:800;letter-spacing:.08em;font-size:13px;text-transform:uppercase}}
.awarded{{margin-top:22px;font-style:italic;color:var(--ink3);font-size:13px}}
.name{{margin:10px 0 18px;font-family:Arial,Helvetica,sans-serif;font-weight:800;font-size:clamp(26px,5vw,42px);color:var(--ink);word-break:break-word}}
.detail{{max-width:600px;margin:0 auto;font-style:italic;color:var(--ink2);font-size:15px}}
.rec{{margin-top:10px;font:12px/1.6 'Courier New',monospace;letter-spacing:.03em;color:var(--ink3)}}
.foot{{display:flex;justify-content:space-between;gap:20px;margin-top:40px;padding-top:18px;border-top:1px solid var(--line);text-align:left;font:12px/1.5 'Courier New',monospace;color:var(--ink2)}}
.foot .lbl{{display:block;color:var(--ink3);letter-spacing:.2em;font-size:10px;text-transform:uppercase;margin-bottom:4px}}
.foot .center{{align-self:center;color:var(--ink3);font-size:10.5px;letter-spacing:.12em;text-align:center;flex:1}}
.foot .right{{text-align:right;word-break:break-all;max-width:44%}}
a{{color:var(--amber)}}
details{{margin-top:22px;text-align:left;font:12px monospace;color:var(--ink3)}}
details summary{{cursor:pointer;color:var(--ink2)}}
pre{{white-space:pre-wrap;word-break:break-all}}
</style></head>
<body><div class="sheet">
<span class="tick tl"></span><span class="tick tr"></span><span class="tick bl"></span><span class="tick br"></span>
<div class="kicker">Verdict</div>
<div class="event">{e(payload['event']['name'])}</div>
<div class="rule"><span class="dot"></span></div>
<div class="kind-kicker">Certificate of</div>
<div class="kind">{e(_KIND_WORD[kind])}</div>
{badge}
<div class="awarded">&mdash; awarded to &mdash;</div>
<div class="name">{e(payload['recipient']['name'])}</div>
<p class="detail">{e(payload['detail'])} at {e(payload['event']['name'])}.</p>
{extra}
<div class="foot">
<div><span class="lbl">Issued</span>{e(payload['issued_at'][:10])}</div>
<div class="center">VERDICT &middot; DIGITALLY SIGNED</div>
<div class="right"><span class="lbl">Verify (Ed25519)</span><a href="{e(web, quote=True)}">{e(web)}</a><br>code {e(code)}</div>
</div>
<details><summary>Digital signature ({e(algorithm)}, key {e(key_id)})</summary>
<p>This page embeds the signed document below. Verify it offline with the public key from
<a href="{e(api.rsplit('/verify/', 1)[0], quote=True)}/.well-known/dogfood-signing-key">/.well-known/dogfood-signing-key</a> and
<code>python backend/scripts/verify_certificate.py</code> (Python standard library only).</p>
<pre>{e(signature)}</pre></details></div>
<script type="application/json" id="dogfood-certificate">{embedded}</script></body></html>"""
