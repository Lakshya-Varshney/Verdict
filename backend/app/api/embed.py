"""Embeddable gallery widget (T4): CORS-open read-only JSON, an iframe-able page and a one-line JS snippet.

Everything here is public and read-only. It exposes only what the public gallery already shows, minus
`custom_answers` (organizer-defined form answers), and never any vote tally, score or draft.
"""

import html
from typing import Optional
from urllib.parse import quote, urlparse
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.event import Event, EventStatus, Track
from app.models.team import Team
from app.schemas.api import EmbedGalleryOut
from app.services.submission_service import list_event_submissions

router = APIRouter(tags=["embed"])

CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, OPTIONS"}
CACHE = {"Cache-Control": "public, max-age=30"}


def _safe_url(url: Optional[str]) -> str:
    """Only http(s) URLs are ever emitted as links/images (blocks javascript:, data: and friends)."""
    if not url:
        return ""
    try:
        p = urlparse(url.strip())
    except ValueError:
        return ""
    return url.strip() if p.scheme in ("http", "https") and p.netloc else ""


async def _event_or_404(db: AsyncSession, event_id: UUID) -> Event:
    ev = (await db.execute(select(Event).where(Event.id == str(event_id)))).scalar_one_or_none()
    if ev is None or ev.status == EventStatus.DRAFT:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return ev


async def _gallery(db: AsyncSession, event: Event, page: int, limit: int, track_id, tag, search):
    subs, total = await list_event_submissions(
        db, event.id, track_id=track_id, tag=tag, search=search, page=page, limit=limit
    )
    team_ids = {str(s.team_id) for s in subs}
    track_ids = {str(s.track_id) for s in subs if s.track_id}
    teams = dict((await db.execute(select(Team.id, Team.name).where(Team.id.in_(team_ids or {""})))).all())
    tracks = dict((await db.execute(select(Track.id, Track.name).where(Track.id.in_(track_ids or {""})))).all())
    items = []
    for s in subs:
        items.append({
            "id": s.id,
            "event_id": s.event_id,
            "team_id": s.team_id,
            "team_name": teams.get(str(s.team_id), ""),
            "track_id": s.track_id,
            "track_name": tracks.get(str(s.track_id)) if s.track_id else None,
            "name": s.name,
            "tagline": s.tagline or "",
            "description": s.description_md or "",
            "thumbnail_url": _safe_url(s.thumbnail_url) or None,
            "images": [u for u in (s.gallery_image_urls or []) if _safe_url(u)],
            "video_url": _safe_url(s.demo_video_url),
            "repo_url": _safe_url(s.repo_url),
            "live_url": _safe_url(s.live_url),
            "tags": s.tech_tags or [],
            "status": "submitted",
            "submitted_at": s.submitted_at.isoformat() if s.submitted_at else None,
            "updated_at": (s.last_edited_at or s.created_at).isoformat(),
            "url": f"{settings.PUBLIC_WEB_URL.rstrip('/')}/submissions/{s.id}",
        })
    return items, total


@router.get("/embed/{event_id}/gallery", response_model=EmbedGalleryOut)
async def embed_gallery_json(
    event_id: UUID,
    response: Response,
    page: int = Query(1, ge=1, le=100_000),
    limit: int = Query(24, ge=1, le=100),
    track_id: Optional[UUID] = Query(None),
    tag: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Read-only JSON gallery for third-party sites. CORS-open (`Access-Control-Allow-Origin: *`)."""
    ev = await _event_or_404(db, event_id)
    items, total = await _gallery(db, ev, page, limit, track_id, tag, search)
    for k, v in {**CORS, **CACHE}.items():
        response.headers[k] = v
    base = settings.PUBLIC_API_URL.rstrip("/")
    return {
        "event": {"id": ev.id, "name": ev.name, "status": ev.status.value,
                  "tagline": (ev.description or "").split("\n\n", 1)[0]},
        "items": items, "total": total, "page": page, "limit": limit,
        "iframe_url": f"{base}/embed/{ev.id}",
        "snippet": f'<script src="{base}/embed.js" data-event="{ev.id}"></script>',
    }


_CSS = """
:root{--bg:#fff;--fg:#14171c;--mut:#5b6472;--line:#e3e6ea;--card:#f7f8fa;--acc:#b45309}
.dark{--bg:#12151a;--fg:#eef0f3;--mut:#9aa3b0;--line:#262b33;--card:#1a1e25;--acc:#f59e0b}
*{box-sizing:border-box}body{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,-apple-system,Segoe UI,sans-serif}
h1{font-size:18px;margin:0 0 4px}.sub{color:var(--mut);font-size:12px;margin:0 0 14px}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fill,minmax(220px,1fr))}
a.card{display:block;text-decoration:none;color:inherit;background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
a.card:hover{border-color:var(--acc)}.thumb{aspect-ratio:16/10;background:var(--line);display:flex;align-items:center;justify-content:center;color:var(--mut);font-size:28px;font-weight:700}
.thumb img{width:100%;height:100%;object-fit:cover;display:block}.body{padding:10px 12px}.name{font-weight:650}.tag{color:var(--mut);font-size:12.5px;margin-top:2px}
.meta{margin-top:8px;font-size:11px;color:var(--mut)}.chip{display:inline-block;border:1px solid var(--line);border-radius:999px;padding:1px 7px;margin:0 4px 4px 0}
.foot{margin-top:14px;text-align:center;font-size:11px;color:var(--mut)}.empty{padding:30px;text-align:center;color:var(--mut)}
"""

_RESIZE = "<script>function h(){parent.postMessage({type:'dogfood-embed-height',height:document.documentElement.scrollHeight},'*')}addEventListener('load',h);addEventListener('resize',h);new MutationObserver(h).observe(document.body,{subtree:true,childList:true})</script>"


@router.get("/embed/{event_id}", response_class=HTMLResponse)
async def embed_gallery_page(
    event_id: UUID,
    limit: int = Query(12, ge=1, le=50),
    theme: str = Query("light", pattern="^(light|dark)$"),
    track_id: Optional[UUID] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Self-contained, iframe-able gallery page (no external assets, all values HTML-escaped)."""
    ev = await _event_or_404(db, event_id)
    items, total = await _gallery(db, ev, 1, limit, track_id, None, None)
    e = html.escape
    cards = []
    for s in items:
        thumb = (f'<img src="{e(s["thumbnail_url"], quote=True)}" alt="" loading="lazy">' if s["thumbnail_url"]
                 else e((s["name"] or "?")[:1].upper()))
        chips = "".join(f'<span class="chip">{e(t)}</span>' for t in s["tags"][:4])
        meta = " · ".join(x for x in (s["team_name"], s["track_name"]) if x)
        cards.append(
            f'<a class="card" href="{e(s["url"], quote=True)}" target="_blank" rel="noopener noreferrer">'
            f'<div class="thumb">{thumb}</div><div class="body"><div class="name">{e(s["name"])}</div>'
            f'<div class="tag">{e(s["tagline"])}</div><div class="meta">{e(meta)}</div><div class="meta">{chips}</div></div></a>'
        )
    body = f'<div class="grid">{"".join(cards)}</div>' if cards else '<div class="empty">No projects submitted yet.</div>'
    doc = (
        f'<!doctype html><html lang="en" class="{"dark" if theme == "dark" else ""}"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(ev.name)} · gallery</title>'
        f"<style>{_CSS}</style></head><body><h1>{e(ev.name)}</h1>"
        f'<p class="sub">{total} project{"" if total == 1 else "s"}</p>{body}'
        f'<div class="foot">Powered by DOGFOOD</div>{_RESIZE}</body></html>'
    )
    headers = {
        **CACHE,
        # meant to be framed anywhere; locked down otherwise (no external loads except project thumbnails)
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
                                   "img-src http: https: data:; frame-ancestors *",
    }
    return HTMLResponse(doc, headers=headers)


_EMBED_JS = r"""/* DOGFOOD gallery widget: <script src=".../embed.js" data-event="EVENT_ID"></script>
   Options (data-*): limit, theme (light|dark), track, height (initial px), width (default 100%),
   target (CSS selector of a container to mount into; default: right after this script tag). */
(function () {
  var s = document.currentScript || document.querySelector('script[data-event][src*="embed.js"]');
  if (!s) return;
  var ev = s.getAttribute('data-event');
  if (!ev) { console.error('dogfood embed: data-event is required'); return; }
  var base = s.src.replace(/\/embed\.js(\?.*)?$/, '');
  var q = [];
  ['limit', 'theme'].forEach(function (k) { var v = s.getAttribute('data-' + k); if (v) q.push(k + '=' + encodeURIComponent(v)); });
  var track = s.getAttribute('data-track'); if (track) q.push('track_id=' + encodeURIComponent(track));
  var f = document.createElement('iframe');
  f.src = base + '/embed/' + encodeURIComponent(ev) + (q.length ? '?' + q.join('&') : '');
  f.title = 'Project gallery';
  f.loading = 'lazy';
  f.style.cssText = 'border:0;width:' + (s.getAttribute('data-width') || '100%') + ';height:' + (s.getAttribute('data-height') || '480') + 'px;display:block';
  f.setAttribute('referrerpolicy', 'no-referrer-when-downgrade');
  window.addEventListener('message', function (m) {
    if (m.source !== f.contentWindow || !m.data || m.data.type !== 'dogfood-embed-height') return;
    var h = Number(m.data.height); if (h > 0 && h < 20000) f.style.height = h + 'px';
  });
  function mount() {
    var t = s.getAttribute('data-target'), box = t && document.querySelector(t);
    if (box) box.appendChild(f);
    else if (s.parentNode && s.parentNode !== document.head && document.body && document.body.contains(s)) s.parentNode.insertBefore(f, s.nextSibling);
    else document.body.appendChild(f);  // script sits in <head>: an iframe there would never render
  }
  if (document.body) mount(); else document.addEventListener('DOMContentLoaded', mount);
})();
"""


@router.get("/embed.js", response_class=Response)
async def embed_script() -> Response:
    """The one-line widget script. Inserts an auto-resizing iframe right after the `<script>` tag."""
    return Response(_EMBED_JS, media_type="application/javascript", headers={**CORS, "Cache-Control": "public, max-age=3600"})
