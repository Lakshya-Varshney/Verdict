"""T4: embeddable gallery widget (JSON, iframe page, script snippet)."""

import pytest

from app.models.event import EventStatus
from app.models.submission import Submission, SubmissionStatus
from app.models.team import Team
from app.models.voting import Vote


async def _sub(db, event, i, **kw):
    team = Team(event_id=event.id, name=f"Team {i}", invite_code=f"emb{i}{event.id[:5]}")
    db.add(team)
    await db.flush()
    s = Submission(team_id=team.id, event_id=event.id, name=kw.pop("name", f"Proj {i}"),
                   status=kw.pop("status", SubmissionStatus.SUBMITTED), **kw)
    db.add(s)
    await db.commit()
    return s


@pytest.mark.asyncio
async def test_json_gallery_is_cors_open_cacheable_and_public_safe(client, db_session, test_event, test_submission):
    test_submission.custom_answers = {"secret_question": "organizer-only answer"}
    await db_session.commit()
    r = await client.get(f"/embed/{test_event.id}/gallery")
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "*"
    assert "max-age" in r.headers["cache-control"] and "access-control-allow-credentials" not in r.headers
    body = r.json()
    assert body["event"]["id"] == test_event.id and body["total"] == 1 and len(body["items"]) == 1
    item = body["items"][0]
    assert item["name"] == "Test Submission" and item["url"].endswith(f"/submissions/{test_submission.id}")
    # nothing that is not already public: no custom answers, votes, scores
    assert "custom_answers" not in item and "secret_question" not in r.text
    assert not any(k in item for k in ("votes", "vote_count", "scores", "score"))
    assert f'data-event="{test_event.id}"' in body["snippet"] and body["iframe_url"].endswith(f"/embed/{test_event.id}")


@pytest.mark.asyncio
async def test_drafts_and_draft_events_are_never_embedded(client, db_session, test_event, test_submission):
    await _sub(db_session, test_event, 1, name="Hidden draft", status=SubmissionStatus.DRAFT)
    body = (await client.get(f"/embed/{test_event.id}/gallery")).json()
    assert [i["name"] for i in body["items"]] == ["Test Submission"]
    test_event.status = EventStatus.DRAFT
    await db_session.commit()
    assert (await client.get(f"/embed/{test_event.id}/gallery")).status_code == 404
    assert (await client.get(f"/embed/{test_event.id}")).status_code == 404
    assert (await client.get("/embed/00000000-0000-0000-0000-000000000000/gallery")).status_code == 404


@pytest.mark.asyncio
async def test_no_tally_leaks_while_voting(client, db_session, test_event, test_submission):
    test_event.status = EventStatus.VOTING
    db_session.add(Vote(submission_id=test_submission.id, event_id=test_event.id, voter_fingerprint="x"))
    await db_session.commit()
    r = await client.get(f"/embed/{test_event.id}/gallery")
    assert r.status_code == 200 and "vote" not in r.text.lower().replace("voting", "")
    assert "vote" not in (await client.get(f"/embed/{test_event.id}")).text.lower().replace("voting", "")


@pytest.mark.asyncio
async def test_pagination_and_validation(client, db_session, test_event):
    for i in range(5):
        await _sub(db_session, test_event, i)
    r = (await client.get(f"/embed/{test_event.id}/gallery", params={"limit": 2, "page": 2})).json()
    assert r["total"] == 5 and len(r["items"]) == 2 and r["page"] == 2
    assert (await client.get(f"/embed/{test_event.id}/gallery", params={"limit": 101})).status_code == 422
    assert (await client.get(f"/embed/{test_event.id}/gallery", params={"page": 0})).status_code == 422


@pytest.mark.asyncio
async def test_preflight(client, test_event):
    r = await client.options(f"/embed/{test_event.id}/gallery", headers={"Origin": "https://blog.example", "Access-Control-Request-Method": "GET"})
    assert r.status_code == 204 and r.headers["access-control-allow-origin"] == "*"


@pytest.mark.asyncio
async def test_html_page_escapes_everything_and_blocks_script_urls(client, db_session, test_event):
    await _sub(db_session, test_event, 1, name='<script>alert(1)</script>"><img src=x onerror=alert(2)>',
               tagline="<b>bold</b>", thumbnail_url="javascript:alert(3)", repo_url="javascript:alert(4)",
               tech_tags=["<i>x</i>"])
    await _sub(db_session, test_event, 2, name="Safe", thumbnail_url="https://img.example/a.png", repo_url="https://example.org/r")
    r = await client.get(f"/embed/{test_event.id}?limit=5")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    page = r.text
    assert "<script>alert" not in page and "<img src=x" not in page  # raw markup never reaches the page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page and "&lt;b&gt;bold&lt;/b&gt;" in page and "&lt;i&gt;x&lt;/i&gt;" in page
    assert "javascript:" not in page
    assert 'src="https://img.example/a.png"' in page
    csp = r.headers["content-security-policy"]
    assert "frame-ancestors *" in csp and "default-src 'none'" in csp
    assert "x-frame-options" not in r.headers  # must be frameable


@pytest.mark.asyncio
async def test_html_theme_empty_state_and_no_external_assets(client, test_event):
    page = (await client.get(f"/embed/{test_event.id}?theme=dark")).text
    assert 'class="dark"' in page and "No projects submitted yet" in page
    import re
    assert not re.findall(r'(?:src|href)="https?://', page)  # nothing external besides project links/thumbnails
    assert (await client.get(f"/embed/{test_event.id}?theme=neon")).status_code == 422


@pytest.mark.asyncio
async def test_embed_script(client):
    r = await client.get("/embed.js")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/javascript")
    assert r.headers["access-control-allow-origin"] == "*"
    js = r.text
    assert "data-event" in js and "createElement('iframe')" in js and "dogfood-embed-height" in js
    assert "m.source !== f.contentWindow" in js  # only trusts resize messages from its own iframe
    assert "eval(" not in js and "innerHTML" not in js
    assert "DOMContentLoaded" in js and "data-target" in js  # works from <head> and can mount into a container
