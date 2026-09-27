"""Submission business logic."""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import lazyload
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.submission import Submission, SubmissionStatus
from app.models.event import Event
from app.models.team import Team


class DeadlinePassedError(ValueError):
    """Raised when a write is attempted after the event's submission deadline."""


def _deadline_passed(event: Optional[Event]) -> bool:
    if not event or not event.submission_deadline:
        return False
    deadline = event.submission_deadline
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return deadline < datetime.now(timezone.utc)


async def create_submission(
    db: AsyncSession,
    team_id: UUID,
    event_id: UUID,
    name: str,
    creator_id: UUID,
    track_id: Optional[UUID] = None,
    **kwargs,
) -> Submission:
    """Create a new submission."""
    # Verify event exists and deadline hasn't passed
    event = await db.execute(select(Event).where(Event.id == str(event_id)))
    event = event.scalar_one_or_none()
    if not event:
        raise ValueError("Event not found")

    if _deadline_passed(event):
        raise DeadlinePassedError("Submission deadline has passed")

    submission = Submission(
        team_id=str(team_id),
        event_id=str(event_id),
        track_id=str(track_id) if track_id else None,
        name=name,
        **kwargs,
    )
    db.add(submission)
    await db.flush()
    return submission


async def get_submission(
    db: AsyncSession,
    submission_id: UUID,
) -> Optional[Submission]:
    """Get submission by ID."""
    result = await db.execute(
        select(Submission).where(Submission.id == str(submission_id))
    )
    return result.scalar_one_or_none()


async def update_submission(
    db: AsyncSession,
    submission_id: UUID,
    **kwargs,
) -> Optional[Submission]:
    """Update submission fields."""
    submission = await get_submission(db, submission_id)
    if not submission:
        return None

    # Check deadline
    event = await db.execute(select(Event).where(Event.id == submission.event_id))
    event = event.scalar_one_or_none()
    if _deadline_passed(event):
        raise DeadlinePassedError("Submission deadline has passed")

    for key, value in kwargs.items():
        if value is not None and hasattr(submission, key):
            # Convert UUID to string for track_id (model stores as string)
            if key == "track_id" and isinstance(value, UUID):
                value = str(value)
            setattr(submission, key, value)

    submission.last_edited_at = datetime.now(timezone.utc)
    await db.flush()
    return submission


async def submit_submission(
    db: AsyncSession,
    submission_id: UUID,
) -> Submission:
    """Submit a draft submission."""
    submission = await get_submission(db, submission_id)
    if not submission:
        raise ValueError("Submission not found")

    if submission.status == SubmissionStatus.SUBMITTED:
        raise ValueError("Submission already submitted")

    # Check deadline
    event = await db.execute(select(Event).where(Event.id == submission.event_id))
    event = event.scalar_one_or_none()
    if _deadline_passed(event):
        raise DeadlinePassedError("Submission deadline has passed")

    submission.status = SubmissionStatus.SUBMITTED
    submission.submitted_at = datetime.now(timezone.utc)
    await db.flush()
    return submission


async def list_event_submissions(
    db: AsyncSession,
    event_id: UUID,
    track_id: Optional[UUID] = None,
    tag: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
) -> tuple[list[Submission], int]:
    """List submissions for public gallery (only submitted)."""
    query = select(Submission).where(
        Submission.event_id == str(event_id),
        Submission.status == SubmissionStatus.SUBMITTED,
    )

    if track_id:
        query = query.where(Submission.track_id == str(track_id))

    if search:
        query = query.where(
            or_(
                Submission.name.ilike(f"%{search}%"),
                Submission.tagline.ilike(f"%{search}%"),
            )
        )

    # Total via COUNT (loading every row would drag in the whole selectin relationship graph)
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar() or 0

    # Apply pagination; the gallery only needs the row's own columns, so skip eager relationship loading
    query = (
        query.options(lazyload("*"))
        .order_by(Submission.created_at, Submission.id)
        .offset((page - 1) * limit)
        .limit(limit)
    )
    result = await db.execute(query)
    submissions = list(result.scalars().all())

    return submissions, total
