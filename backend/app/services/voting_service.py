"""Voting business logic: access modes, budgets, quadratic credits, window enforcement."""

import re
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.event import Event, EventStatus
from app.models.submission import Submission, SubmissionStatus
from app.models.user import User
from app.models.voting import Comment, Vote
from app.utils.fingerprint import sha

VOTING_MODES = ("open", "email", "auth", "quadratic")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def canonical_email(addr: str) -> str:
    """One mailbox = one voter: lower-case, drop `+tag`, and (Gmail) ignore dots, so aliases cannot mint extra votes."""
    local, _, domain = addr.strip().lower().partition("@")
    local = local.split("+", 1)[0]
    if domain in ("gmail.com", "googlemail.com"):
        local, domain = local.replace(".", ""), "gmail.com"
    return f"{local}@{domain}"


class VoteError(Exception):
    """Business-rule failure carrying the HTTP status the route should return."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def window_error(event: Event) -> Optional[str]:
    """Return why voting is closed right now, or None when it is open.

    Voting requires event.status == voting AND (when set) now inside [voting_opens_at, voting_closes_at].
    """
    now = datetime.now(timezone.utc)
    if event.status == EventStatus.CLOSED:
        return "Voting has ended"
    if event.status != EventStatus.VOTING:
        return "Voting has not started yet"
    opens, closes = _aware(event.voting_opens_at), _aware(event.voting_closes_at)
    if opens and now < opens:
        return "Voting has not started yet"
    if closes and now > closes:
        return "Voting has ended"
    return None


def resolve_voter(
    event: Event,
    user: Optional[User],
    email: Optional[str],
    session_id: str,
) -> str:
    """Map a request to a stable voter fingerprint according to the event's voting mode."""
    mode = event.voting_mode or "auth"
    if mode in ("auth", "quadratic"):
        if user is None:
            raise VoteError(401, "Sign in to vote in this event")
        return sha(f"user:{user.id}")
    if mode == "email":
        addr = (email or (user.email if user else "") or "").strip().lower()
        if not _EMAIL_RE.match(addr):
            raise VoteError(400, "A valid email address is required to vote in this event")
        return sha(f"email:{event.id}:{canonical_email(addr)}")
    # open link: signed session cookie (identity is the cookie; IP cap is enforced separately)
    return sha(f"session:{event.id}:{session_id}")


async def lock_event(db: AsyncSession, event_id: str) -> Event:
    """Serialize concurrent votes per event (row lock on Postgres; no-op on SQLite)."""
    result = await db.execute(select(Event).where(Event.id == str(event_id)).with_for_update())
    return result.scalar_one()


async def voter_state(db: AsyncSession, event: Event, fingerprint: str) -> dict:
    rows = (
        await db.execute(
            select(Vote).where(Vote.event_id == str(event.id), Vote.voter_fingerprint == fingerprint)
        )
    ).scalars().all()
    active = [v for v in rows if v.weight > 0]
    my_votes = {v.submission_id: v.weight for v in active}
    quad = event.voting_mode == "quadratic"
    spent = sum(w * w for w in my_votes.values())
    return {
        "mode": event.voting_mode,
        "my_votes": my_votes,
        "votes_used": len(active),
        "votes_left": None if quad else max(0, event.votes_per_voter - len(active)),
        "credits_total": event.vote_credits if quad else None,
        "credits_left": max(0, event.vote_credits - spent) if quad else None,
    }


async def cast_vote(
    db: AsyncSession,
    submission: Submission,
    fingerprint: str,
    ip_hash: str,
    weight: Optional[int] = None,
) -> tuple[Vote, dict, bool]:
    """Record (or, for quadratic voting, re-allocate) a vote. Returns (vote, voter_state, created)."""
    event = await lock_event(db, submission.event_id)
    err = window_error(event)
    if err:
        raise VoteError(400, err)

    quad = event.voting_mode == "quadratic"
    existing = (
        await db.execute(
            select(Vote).where(
                Vote.submission_id == str(submission.id), Vote.voter_fingerprint == fingerprint
            )
        )
    ).scalar_one_or_none()

    if quad:
        n = 1 if weight is None else weight
        if n < 0:
            raise VoteError(400, "Votes must be zero or more")
        state = await voter_state(db, event, fingerprint)
        others = sum(w * w for sid, w in state["my_votes"].items() if sid != str(submission.id))
        if others + n * n > event.vote_credits:
            raise VoteError(
                400,
                f"Not enough credits: {n} votes cost {n * n}, you have {event.vote_credits - others} left",
            )
    else:
        n = 1
        if existing is not None:
            raise VoteError(400, "Already voted for this submission")
        state = await voter_state(db, event, fingerprint)
        if state["votes_left"] <= 0:
            raise VoteError(
                400, f"Vote limit reached ({event.votes_per_voter} per person for this event)"
            )

    if event.voting_mode == "open" and existing is None:
        from_ip = (
            await db.execute(
                select(func.count(Vote.id)).where(Vote.event_id == str(event.id), Vote.ip_hash == ip_hash)
            )
        ).scalar() or 0
        if from_ip >= max(1, event.votes_per_voter) * settings.VOTES_PER_IP_MULTIPLIER:
            raise VoteError(429, "Too many votes from this network for this event")

    created = existing is None
    if existing is None:
        vote = Vote(
            submission_id=str(submission.id),
            event_id=str(event.id),
            voter_fingerprint=fingerprint,
            ip_hash=ip_hash,
            weight=n,
        )
        db.add(vote)
    else:
        vote = existing
        vote.weight = n
    await db.flush()
    return vote, await voter_state(db, event, fingerprint), created


async def get_vote_count(db: AsyncSession, submission_id: UUID) -> int:
    """Total vote weight for a submission (approval votes count 1, quadratic votes count n)."""
    result = await db.execute(
        select(func.coalesce(func.sum(Vote.weight), 0)).where(Vote.submission_id == str(submission_id))
    )
    return int(result.scalar() or 0)


async def create_comment(
    db: AsyncSession,
    submission_id: UUID,
    body: str,
    author_id: Optional[UUID] = None,
) -> Comment:
    """Create a comment on a submission."""
    comment = Comment(
        submission_id=str(submission_id),
        author_id=str(author_id) if author_id else None,
        body=body,
    )
    db.add(comment)
    await db.flush()
    return comment


async def get_comments(
    db: AsyncSession,
    submission_id: UUID,
    page: int = 1,
    limit: int = 20,
) -> tuple[list[Comment], int]:
    """Get comments for a submission (oldest first)."""
    query = select(Comment).where(Comment.submission_id == str(submission_id))
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0
    result = await db.execute(
        query.order_by(Comment.created_at.asc()).offset((page - 1) * limit).limit(limit)
    )
    return list(result.scalars().all()), total
