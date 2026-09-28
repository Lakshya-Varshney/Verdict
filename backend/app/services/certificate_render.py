"""Render a signed certificate as a PDF (reportlab) or a self-contained, verifiable HTML page."""

import html
import io
import json

from app.config import settings

TITLES = {"participant": "Certificate of Participation", "judge": "Judge Participation Record", "winner": "Certificate of Achievement"}


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


def render_pdf(payload: dict, signature: str, code: str, key_id: str) -> bytes:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.utils import simpleSplit
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    w, h = landscape(A4)
    # invariant: byte-identical output for the same input; uncompressed so the code/URL are plain text in the file
    c = canvas.Canvas(buf, pagesize=(w, h), invariant=1, pageCompression=0)
    c.setTitle(f"{TITLES[payload['kind']]} - {_latin1(payload['recipient']['name'])}")
    c.setAuthor("DOGFOOD")
    c.setSubject("Digitally signed (Ed25519). Verify at " + verify_urls(code)[0])
    ink = (0.09, 0.075, 0.043)
    c.setFillColorRGB(0.957, 0.925, 0.847)
    c.rect(0, 0, w, h, stroke=0, fill=1)
    c.setStrokeColorRGB(*ink)
    c.setLineWidth(3)
    c.rect(28, 28, w - 56, h - 56)
    c.setLineWidth(0.6)
    c.rect(38, 38, w - 76, h - 76)
    c.setFillColorRGB(*ink)
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(w / 2, h - 96, "D O G F O O D")
    event_line = _latin1(payload["event"]["name"]).upper()
    c.setFont("Helvetica", _fit(event_line, "Helvetica", 10, w - 160, 6))
    c.drawCentredString(w / 2, h - 116, event_line)
    c.setFont("Helvetica", 12)
    c.drawCentredString(w / 2, h - 170, TITLES[payload["kind"]].upper())
    name = _latin1(payload["recipient"]["name"])
    c.setFont("Times-Italic", _fit(name, "Times-Italic", 46, w - 140))
    c.drawCentredString(w / 2, h - 250, name)
    c.setFont("Helvetica", 13)
    y = h - 300
    line = _latin1(f"{payload['detail']} at {payload['event']['name']}.")
    for part in simpleSplit(line, "Helvetica", 13, w - 220):
        c.drawCentredString(w / 2, y, part)
        y -= 18
    rec = payload.get("record") or {}
    if payload["kind"] == "judge" and rec:
        c.setFont("Helvetica", 10)
        c.drawCentredString(w / 2, y - 6, f"{rec['projects_reviewed']} projects reviewed  |  {rec['criterion_scores']} criterion scores  |  {rec['first_review'][:10]} to {rec['last_review'][:10]}")
    c.setFont("Helvetica", 9)
    c.drawString(64, 112, "ISSUED")
    c.setFont("Helvetica", 12)
    c.drawString(64, 96, payload["issued_at"][:10])
    web, api = verify_urls(code)
    c.setFont("Helvetica", 8)
    c.drawRightString(w - 64, 112, "VERIFY  (Ed25519 digital signature)")
    c.setFont("Courier", 7.5)
    c.drawRightString(w - 64, 99, f"code {code}")
    c.drawRightString(w - 64, 89, web)
    c.drawRightString(w - 64, 79, f"key {key_id}   sig {signature[:40]}...")
    c.setFont("Helvetica", 7)
    c.drawCentredString(w / 2, 54, "Anyone can verify this document offline against the public key at " + api.rsplit("/verify/", 1)[0] + "/.well-known/dogfood-signing-key")
    c.showPage()
    c.save()
    return buf.getvalue()


def render_html(payload: dict, signature: str, code: str, key_id: str, algorithm: str) -> str:
    e = html.escape
    web, api = verify_urls(code)
    rec = payload.get("record") or {}
    extra = ""
    if payload["kind"] == "judge" and rec:
        extra = (f'<p class="rec">{rec["projects_reviewed"]} projects reviewed · {rec["criterion_scores"]} criterion scores · '
                 f'{e(rec["first_review"][:10])} to {e(rec["last_review"][:10])}</p>')
    doc = {"payload": payload, "signature": signature, "key_id": key_id, "algorithm": algorithm}
    embedded = json.dumps(doc, ensure_ascii=False, sort_keys=True).replace("<", "\\u003c")  # cannot close the script tag
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(TITLES[payload['kind']])} · {e(payload['recipient']['name'])}</title>
<style>body{{margin:0;background:#e9e2cf;font:16px/1.5 Georgia,serif;color:#17130b;padding:24px}}
.sheet{{max-width:920px;margin:0 auto;background:#f4ecd8;border:3px solid #17130b;outline:1px solid #17130b;outline-offset:-9px;padding:48px 40px;text-align:center}}
.brand{{letter-spacing:.35em;font-weight:700}}.ev{{font:12px monospace;letter-spacing:.25em;text-transform:uppercase;opacity:.65;margin-top:4px}}
.kind{{font:13px monospace;letter-spacing:.3em;text-transform:uppercase;opacity:.75;margin-top:36px}}.name{{font-size:52px;font-style:italic;margin:18px 0}}
.rec{{font:13px monospace;opacity:.7}}.foot{{display:flex;justify-content:space-between;gap:16px;margin-top:40px;text-align:left;font:12px monospace;word-break:break-all}}
.foot b{{display:block;opacity:.6;letter-spacing:.15em}}a{{color:#7c4a03}}details{{margin-top:28px;text-align:left;font:12px monospace}}pre{{white-space:pre-wrap;word-break:break-all}}</style></head>
<body><div class="sheet"><div class="brand">DOGFOOD</div><div class="ev">{e(payload['event']['name'])}</div>
<div class="kind">{e(TITLES[payload['kind']])}</div><div class="name">{e(payload['recipient']['name'])}</div>
<p>{e(payload['detail'])} at <b>{e(payload['event']['name'])}</b>.</p>{extra}
<div class="foot"><div><b>ISSUED</b>{e(payload['issued_at'][:10])}</div>
<div><b>VERIFY</b><a href="{e(web, quote=True)}">{e(web)}</a><br>code {e(code)}</div></div>
<details><summary>Digital signature ({e(algorithm)}, key {e(key_id)})</summary>
<p>This page embeds the signed document below. Verify it offline with the public key from
<a href="{e(api.rsplit('/verify/', 1)[0], quote=True)}/.well-known/dogfood-signing-key">/.well-known/dogfood-signing-key</a> and
<code>python backend/scripts/verify_certificate.py</code> (Python standard library only).</p>
<pre>{e(signature)}</pre></details></div>
<script type="application/json" id="dogfood-certificate">{embedded}</script></body></html>"""
