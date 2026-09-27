"""Event business logic."""

from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event, Track, EventRole, EventRoleType
from app.models.user import User


async def create_event(
    db: AsyncSession,
    organizer_id: UUID,
    name: str,
    slug: str,
    description: Optional[str] = None,
    **kwargs,
) -> Event:
    """Create a new event."""
    # Check slug uniqueness
    result = await db.execute(select(Event).where(Event.slug == slug))
    if result.scalar_one_or_none():
        raise ValueError("Event slug already exists")

    event = Event(
        organizer_id=str(organizer_id),
        name=name,
        slug=slug,
        description=description,
        **kwargs,
    )
    db.add(event)
    await db.flush()

    # Add organizer role
    role = EventRole(
        user_id=str(organizer_id),
        event_id=event.id,
        role=EventRoleType.ORGANIZER,
    )
    db.add(role)
    await db.flush()

    return event


async def get_event(
    db: AsyncSession,
    event_id: UUID,
    user_id: Optional[UUID] = None,
    public_view: bool = False,
) -> Optional[Event]:
    """Get event by ID.
    
    If user_id is provided, returns None for draft events unless user is organizer/admin.
    """
    from app.models.event import EventRole, EventRoleType
    
    query = select(Event).where(Event.id == str(event_id))

    if user_id and await _is_site_admin(db, user_id):
        user_id, public_view = None, False  # site admin: no draft filter at all
    if public_view and not user_id:  # public routes: drafts are hidden from anonymous visitors too
        query = query.where(Event.status != "draft")

    if user_id:
        # Get events where user is organizer or admin
        organizer_events = select(EventRole.event_id).where(
            EventRole.user_id == str(user_id),
            EventRole.role.in_([EventRoleType.ORGANIZER, EventRoleType.ADMIN])
        )
        # Allow: non-draft events + draft events where user is organizer/admin
        query = query.where(
            (Event.status != "draft") | (Event.id.in_(organizer_events))
        )
    
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_event_by_slug(
    db: AsyncSession,
    slug: str,
) -> Optional[Event]:
    """Get event by slug."""
    result = await db.execute(select(Event).where(Event.slug == slug))
    return result.scalar_one_or_none()


async def _is_site_admin(db: AsyncSession, user_id: Optional[UUID]) -> bool:
    """Holds the ADMIN role in any event: sees drafts everywhere (same meaning as api.deps.is_global_admin)."""
    if not user_id:
        return False
    from app.models.event import EventRole, EventRoleType

    row = await db.execute(select(EventRole.id).where(EventRole.user_id == str(user_id), EventRole.role == EventRoleType.ADMIN))
    return row.first() is not None


async def list_events(
    db: AsyncSession,
    status: Optional[str] = None,
    page: int = 1,
    limit: int = 20,
    user_id: Optional[UUID] = None,
    public_view: bool = False,
) -> tuple[list[Event], int]:
    """List events with optional status filter.
    
    If user_id is provided, filters out draft events unless the user is the organizer or admin.
    """
    from app.models.event import EventRole, EventRoleType
    
    query = select(Event)
    count_query = select(Event)

    if status:
        query = query.where(Event.status == status)
        count_query = count_query.where(Event.status == status)

    # Filter draft events for non-organizer/non-admin users
    if user_id and await _is_site_admin(db, user_id):
        user_id, public_view = None, False  # site admin: no draft filter at all
    if public_view and not user_id:  # public routes: drafts are hidden from anonymous visitors too
        query = query.where(Event.status != "draft")
        count_query = count_query.where(Event.status != "draft")
    if user_id:
        # Get events where user is organizer or admin
        organizer_events = select(EventRole.event_id).where(
            EventRole.user_id == str(user_id),
            EventRole.role.in_([EventRoleType.ORGANIZER, EventRoleType.ADMIN])
        )
        # Allow: non-draft events + draft events where user is organizer/admin
        query = query.where(
            (Event.status != "draft") | (Event.id.in_(organizer_events))
        )
        count_query = count_query.where(
            (Event.status != "draft") | (Event.id.in_(organizer_events))
        )

    # Get total count
    total_result = await db.execute(count_query)
    total = len(total_result.scalars().all())

    # Apply pagination
    query = query.offset((page - 1) * limit).limit(limit)
    result = await db.execute(query)
    events = list(result.scalars().all())

    return events, total


async def update_event(
    db: AsyncSession,
    event_id: UUID,
    **kwargs,
) -> Optional[Event]:
    """Update event fields."""
    event = await get_event(db, event_id)
    if not event:
        return None

    for key, value in kwargs.items():
        if value is not None and hasattr(event, key):
            setattr(event, key, value)

    await db.flush()
    return event


async def create_track(
    db: AsyncSession,
    event_id: UUID,
    name: str,
    description: Optional[str] = None,
) -> Track:
    """Create a track for an event."""
    track = Track(
        event_id=str(event_id),
        name=name,
        description=description,
    )
    db.add(track)
    await db.flush()
    return track


async def list_tracks(
    db: AsyncSession,
    event_id: UUID,
) -> list[Track]:
    """List tracks for an event."""
    result = await db.execute(
        select(Track).where(Track.event_id == str(event_id))
    )
    return list(result.scalars().all())


async def assign_role(
    db: AsyncSession,
    event_id: UUID,
    user_id: UUID,
    role: EventRoleType,
) -> EventRole:
    """Assign a role to a user for an event."""
    # Check if role already exists
    result = await db.execute(
        select(EventRole).where(
            EventRole.user_id == str(user_id),
            EventRole.event_id == str(event_id),
            EventRole.role == role,
        )
    )
    if result.scalar_one_or_none():
        raise ValueError("User already has this role")

    event_role = EventRole(
        user_id=str(user_id),
        event_id=str(event_id),
        role=role,
    )
    db.add(event_role)
    await db.flush()
    return event_role


async def delete_event(
    db: AsyncSession,
    event_id: UUID,
) -> bool:
    """Delete an event."""
    event = await get_event(db, event_id)
    if not event:
        return False
    
    # Explicit dependency-ordered deletes: ORM cascades try to NULL composite primary-key
    # columns (normalized_scores.criterion_id) and 500.
    from sqlalchemy import delete
    from app.models.certificate import Certificate
    from app.models.judging import JudgeAssignment, NormalizedScore, RubricCriterion, Score
    from app.models.submission import Submission
    from app.models.team import Team, TeamMembership
    from app.models.voting import Comment, Vote

    eid = str(event_id)
    subs = select(Submission.id).where(Submission.event_id == eid)
    teams = select(Team.id).where(Team.event_id == eid)
    crits = select(RubricCriterion.id).where(RubricCriterion.event_id == eid)
    for stmt in (
        delete(NormalizedScore).where(NormalizedScore.submission_id.in_(subs)),
        delete(NormalizedScore).where(NormalizedScore.criterion_id.in_(crits)),
        delete(Score).where(Score.submission_id.in_(subs)),
        delete(JudgeAssignment).where(JudgeAssignment.submission_id.in_(subs)),
        delete(Vote).where(Vote.submission_id.in_(subs)),
        delete(Comment).where(Comment.submission_id.in_(subs)),
        delete(Submission).where(Submission.event_id == eid),
        delete(TeamMembership).where(TeamMembership.team_id.in_(teams)),
        delete(Team).where(Team.event_id == eid),
        delete(RubricCriterion).where(RubricCriterion.event_id == eid),
        delete(Track).where(Track.event_id == eid),
        delete(EventRole).where(EventRole.event_id == eid),
        delete(Certificate).where(Certificate.event_id == eid),
        delete(Event).where(Event.id == eid),
    ):
        await db.execute(stmt)
    db.expire_all()
    await db.flush()
    return True


async def list_event_roles(
    db: AsyncSession,
    event_id: UUID,
) -> list[EventRole]:
    """List all roles for an event."""
    result = await db.execute(
        select(EventRole).where(EventRole.event_id == str(event_id))
    )
    return list(result.scalars().all())
