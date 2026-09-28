"""Voting, ballot and comment API routes (T3)."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_optional
from app.config import settings
from app.database import get_db
from app.models.event import Event, EventRole, EventRoleType, EventStatus, Track
from app.models.submission import Submission, SubmissionStatus
from app.models.team import Team
from app.models.user import User
from app.schemas.voting import CommentCreate, VoteCreate
from app.services.audit_service import create_audit_log
from app.services.voting_service import (
    VoteError,
    cast_vote,
    create_comment,
    get_comments,
    get_vote_count,
    resolve_voter,
    voter_state,
    window_error,
)
from app.utils.fingerprint import (
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    client_ip,
    new_session_id,
    read_session,
    seeded_order,
    sha,
    sign_session,
)
from app.utils.rate_limit import hit
from app.services.webhook_service import emit as emit_webhook
from app.schemas.api import BallotOut, CommentOut, VoteCountOut, VoteOut

router = APIRouter(tags=["voting"])


def _session(request: Request, response: Response, hint: Optional[str] = None) -> str:
    """Return the caller's voter-session id, issuing a signed cookie if they have none.

    ``hint`` (the UI's client fingerprint) seeds the id for cookie-less clients so repeat requests from
    them still map to one voter; the cookie, once issued, always wins.
    """
    sid = read_session(request.cookies.get(SESSION_COOKIE))
    if sid is None:
        sid = sha(f"client:{hint}")[:32] if hint else new_session_id()
        response.set_cookie(
            SESSION_COOKIE, sign_session(sid), max_age=SESSION_MAX_AGE, httponly=True, samesite="lax"
        )
    return sid


async def _limit(kind: str, ip: str, identity: str, per_minute: int) -> None:
    """Per (IP + identity) limit, plus a looser per-IP ceiling so rotating cookies doesn't dodge it."""
    for key, cap in ((f"{kind}:{ip}:{identity}", per_minute), (f"{kind}:ip:{ip}", per_minute * 6)):
        ok, retry = await hit(key, cap, 60)
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many {kind} requests, slow down",
                headers={"Retry-After": str(retry)},
            )


async def _published_submission(db: AsyncSession, submission_id: UUID) -> Submission:
    sub = (await db.execute(select(Submission).where(Submission.id == str(submission_id)))).scalar_one_or_none()
    if sub is None or sub.status != SubmissionStatus.SUBMITTED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submission not found")
    return sub


async def _is_staff(db: AsyncSession, user: Optional[User], event_id: str) -> bool:
    if user is None:
        return False
    row = await db.execute(
        select(EventRole).where(
            EventRole.user_id == str(user.id),
            EventRole.event_id == str(event_id),
            EventRole.role.in_([EventRoleType.ORGANIZER, EventRoleType.ADMIN]),
        )
    )
    return row.first() is not None


@router.post("/submissions/{submission_id}/vote", status_code=status.HTTP_201_CREATED, response_model=VoteOut)
async def vote_for_submission(
    submission_id: UUID,
    request: Request,
    response: Response,
    body: Optional[VoteCreate] = None,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Cast a vote.

    Access follows the event's `voting_mode`: `open` (signed session cookie), `email` (body `email`),
    `auth` (bearer token) or `quadratic` (bearer token; body `votes` = votes on this project, cost votes²
    out of the event's credits). Enforced server-side: voting window (`status == voting`), per-person
    budget, duplicate detection (DB unique constraint), and rate limiting (429).
    """
    body = body or VoteCreate()
    sub = await _published_submission(db, submission_id)
    event = (await db.execute(select(Event).where(Event.id == sub.event_id))).scalar_one()
    ip = client_ip(request)
    session_id = _session(request, response, body.fingerprint) if event.voting_mode == "open" else ""

    err = window_error(event)
    if err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=err)
    try:
        fingerprint = resolve_voter(event, current_user, body.email, session_id)
        await _limit("vote", ip, fingerprint[:16], settings.RATE_LIMIT_VOTES_PER_MINUTE)
        vote, state, created = await cast_vote(db, sub, fingerprint, sha(f"ip:{ip}"), body.votes)
    except VoteError as e:
        try:
            await create_audit_log(
                db, "vote.rejected", "submission", sub.id, actor_id=current_user.id if current_user else None,
                event_id=sub.event_id,
                extra_data={"role": "voter", "outcome": "denied", "ip": ip, "detail": e.detail},
            )
            await db.commit()  # keep the denial: the error path below rolls the request back otherwise
        except Exception:
            pass
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    await create_audit_log(
        db, "vote.cast" if created else "vote.update", "vote", vote.id,
        actor_id=current_user.id if current_user else None, event_id=sub.event_id,
        extra_data={"role": "voter", "ip": ip, "submission_id": str(sub.id), "weight": vote.weight,
                    "voter": fingerprint[:12], "detail": f"{event.voting_mode} vote x{vote.weight} for '{sub.name}'"},
    )
    # never any tally: only the fact that a vote happened
    await emit_webhook(db, sub.event_id, "vote.cast",
                       {"submission_id": str(sub.id), "weight": vote.weight, "mode": event.voting_mode, "updated": not created})
    return {
        "ok": True,
        "id": vote.id,
        "submission_id": vote.submission_id,
        "created_at": vote.created_at.isoformat() if vote.created_at else None,
        "votes": vote.weight,
        "votes_left": state["votes_left"],
        "credits_left": state["credits_left"],
        "mode": state["mode"],
    }


@router.get("/submissions/{submission_id}/votes/count", response_model=VoteCountOut)
async def get_submission_vote_count(
    submission_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Vote count. Results-hiding rule: while the event is in `voting`, only organizers/admins see it."""
    sub = (await db.execute(select(Submission).where(Submission.id == str(submission_id)))).scalar_one_or_none()
    count = await get_vote_count(db, submission_id)
    hidden = False
    if sub:
        ev = (await db.execute(select(Event).where(Event.id == str(sub.event_id)))).scalar_one_or_none()
        if ev and ev.status == EventStatus.VOTING:
            hidden = not await _is_staff(db, current_user, sub.event_id)
    return {
        "submission_id": str(submission_id),
        "hidden": hidden,
        "count": None if hidden else count,
        "vote_count": None if hidden else count,
    }


@router.get("/events/{event_id}/ballot", response_model=BallotOut)
async def get_ballot(
    event_id: UUID,
    request: Request,
    response: Response,
    email: Optional[str] = Query(None, description="voter email (email-gated events)"),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Ballot: submitted projects in a per-session randomized order (kills position bias).

    The order is a seeded shuffle keyed by the voter's identity (user id, or the signed session cookie),
    so it is stable across reloads for one voter and differs between voters. Never includes tallies.
    """
    event = (await db.execute(select(Event).where(Event.id == str(event_id)))).scalar_one_or_none()
    if event is None or event.status == EventStatus.DRAFT:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    session_id = _session(request, response)
    seed = f"user:{current_user.id}" if current_user else f"session:{session_id}"

    subs = list(
        (
            await db.execute(
                select(Submission).where(
                    Submission.event_id == str(event_id), Submission.status == SubmissionStatus.SUBMITTED
                )
            )
        ).scalars().all()
    )
    teams = {t.id: t.name for t in (await db.execute(select(Team).where(Team.event_id == str(event_id)))).scalars().all()}
    tracks = {t.id: t.name for t in (await db.execute(select(Track).where(Track.event_id == str(event_id)))).scalars().all()}
    items = [
        {
            "id": s.id, "name": s.name, "tagline": s.tagline, "thumbnail_url": s.thumbnail_url,
            "tech_tags": s.tech_tags or [], "team_name": teams.get(s.team_id, ""),
            "track_name": tracks.get(s.track_id) if s.track_id else None,
        }
        for s in seeded_order(subs, f"{event_id}:{seed}")
    ]

    err = window_error(event)
    voter = None
    try:
        fp = resolve_voter(event, current_user, email, session_id if event.voting_mode == "open" else "")
        voter = await voter_state(db, event, fp)
    except VoteError:
        pass  # identity not established yet (anonymous on auth ballot / email not supplied)
    return {
        "event_id": str(event_id),
        "voting_mode": event.voting_mode,
        "votes_per_voter": event.votes_per_voter,
        "vote_credits": event.vote_credits,
        "open": err is None,
        "closed_reason": err,
        "requires_auth": event.voting_mode in ("auth", "quadratic") and current_user is None,
        "requires_email": event.voting_mode == "email",
        "voter": voter,
        "items": items,
    }


@router.post("/submissions/{submission_id}/comments", response_model=CommentOut, status_code=status.HTTP_201_CREATED)
async def add_comment(
    submission_id: UUID,
    comment_data: CommentCreate,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Comment on a gallery project (signed-in or anonymous; rate-limited)."""
    sub = await _published_submission(db, submission_id)
    ip = client_ip(request)
    identity = f"user:{current_user.id}" if current_user else f"session:{_session(request, response)}"
    await _limit("comment", ip, sha(identity)[:16], settings.RATE_LIMIT_COMMENTS_PER_MINUTE)
    comment = await create_comment(
        db=db, submission_id=submission_id, body=comment_data.body.strip(),
        author_id=current_user.id if current_user else None,
    )
    name = current_user.name if current_user else (comment_data.author_name or "Anonymous")
    await emit_webhook(db, sub.event_id, "comment.added",
                       {"submission_id": str(sub.id), "comment_id": comment.id, "author_name": name, "body": comment.body})
    await create_audit_log(
        db, "comment.add", "comment", comment.id, actor_id=current_user.id if current_user else None,
        event_id=sub.event_id,
        extra_data={"role": "visitor" if current_user is None else "user", "ip": ip,
                    "submission_id": str(sub.id), "detail": f"comment on '{sub.name}'"},
    )
    return {
        "id": comment.id,
        "submission_id": comment.submission_id,
        "user_id": comment.author_id,
        "author_id": comment.author_id,
        "user_name": name,
        "author_name": name,
        "body": comment.body,
        "created_at": comment.created_at.isoformat() if hasattr(comment.created_at, "isoformat") else comment.created_at,
    }


@router.get("/submissions/{submission_id}/comments", response_model=list[CommentOut])
async def list_comments(
    submission_id: UUID,
    page: int = Query(1, ge=1, le=100_000),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Comments for a submission with author names (oldest first)."""
    from app.models.user import User as UserModel

    comments, _ = await get_comments(db, submission_id, page=page, limit=limit)
    out = []
    for c in comments:
        name = None
        if c.author_id:
            user = (await db.execute(select(UserModel).where(UserModel.id == str(c.author_id)))).scalar_one_or_none()
            name = user.name if user else None
        out.append({
            "id": c.id,
            "submission_id": c.submission_id,
            "user_id": c.author_id,
            "author_id": c.author_id,
            "user_name": name or "Anonymous",
            "author_name": name or "Anonymous",
            "body": c.body,
            "created_at": c.created_at.isoformat() if hasattr(c.created_at, "isoformat") else c.created_at,
        })
    return out
