"""Team business logic."""

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.team import Team, TeamMembership, TeamRoleType
from app.models.event import Event, EventRole, EventRoleType


async def _grant_participant_role(db: AsyncSession, event_id: UUID, user_id: UUID) -> None:
    """Creating or joining a team is how a user *becomes* a participant of an event - the only
    other place a participant EventRole is ever created is fixture/demo import, so without this
    a real signup could never pass the `participant` role checks on submissions afterward (or,
    before this fix, even create/join the team in the first place - see the `participant` role
    checks on `create_new_team`/`join_existing_team`, which used to require already holding the
    role they're meant to grant)."""
    existing = await db.execute(
        select(EventRole).where(
            EventRole.user_id == str(user_id),
            EventRole.event_id == str(event_id),
            EventRole.role == EventRoleType.PARTICIPANT,
        )
    )
    if existing.scalar_one_or_none() is None:
        db.add(EventRole(user_id=str(user_id), event_id=str(event_id), role=EventRoleType.PARTICIPANT))
        await db.flush()


async def is_team_formation_active(db: AsyncSession, event_id: UUID) -> bool:
    """Check if team formation period is active for an event."""
    event = await db.execute(select(Event).where(Event.id == str(event_id)))
    event = event.scalar_one_or_none()
    if not event:
        return False
    
    now = datetime.now(timezone.utc)
    if event.team_formation_start and now < event.team_formation_start:
        return False
    if event.team_formation_end and now > event.team_formation_end:
        return False
    return True


async def create_team(
    db: AsyncSession,
    event_id: UUID,
    name: str,
    creator_id: UUID,
) -> Team:
    """Create a new team and add creator as leader."""
    # Check if team formation period is active
    if not await is_team_formation_active(db, event_id):
        raise ValueError("Team formation period has ended or not started yet")

    if await get_user_teams(db, event_id, creator_id):
        raise ValueError("You are already in a team for this event")

    team = Team(
        event_id=str(event_id),
        name=name,
    )
    db.add(team)
    await db.flush()

    # Add creator as leader
    membership = TeamMembership(
        team_id=team.id,
        user_id=str(creator_id),
        role_in_team=TeamRoleType.LEADER,
    )
    db.add(membership)
    await db.flush()
    await _grant_participant_role(db, event_id, creator_id)

    return team


async def get_team(
    db: AsyncSession,
    team_id: UUID,
) -> Optional[Team]:
    """Get team by ID."""
    result = await db.execute(select(Team).where(Team.id == str(team_id)))
    return result.scalar_one_or_none()


async def join_team(
    db: AsyncSession,
    team_id: UUID,
    user_id: UUID,
    invite_code: str,
) -> TeamMembership:
    """Join a team using invite code."""
    team = await get_team(db, team_id)
    if not team:
        raise ValueError("Team not found")

    if team.invite_code != invite_code:
        raise ValueError("Invalid invite code")

    # Check if team formation period is active
    if not await is_team_formation_active(db, team.event_id):
        raise ValueError("Team formation period has ended or not started yet")

    if await get_user_teams(db, team.event_id, user_id):
        raise ValueError("You are already in a team for this event")

    # Check if already a member
    result = await db.execute(
        select(TeamMembership).where(
            TeamMembership.team_id == str(team_id),
            TeamMembership.user_id == str(user_id),
        )
    )
    if result.scalar_one_or_none():
        raise ValueError("Already a member of this team")

    membership = TeamMembership(
        team_id=str(team_id),
        user_id=str(user_id),
        role_in_team=TeamRoleType.MEMBER,
    )
    db.add(membership)
    await db.flush()
    await _grant_participant_role(db, team.event_id, user_id)

    return membership


async def get_user_teams(
    db: AsyncSession,
    event_id: UUID,
    user_id: UUID,
) -> list[Team]:
    """Get all teams a user belongs to for an event."""
    result = await db.execute(
        select(Team)
        .join(TeamMembership)
        .where(
            Team.event_id == str(event_id),
            TeamMembership.user_id == str(user_id),
        )
    )
    return list(result.scalars().all())


async def is_team_member(
    db: AsyncSession,
    team_id: UUID,
    user_id: UUID,
) -> bool:
    """Check if a user is a member of a team."""
    result = await db.execute(
        select(TeamMembership).where(
            TeamMembership.team_id == str(team_id),
            TeamMembership.user_id == str(user_id),
        )
    )
    return result.scalar_one_or_none() is not None


async def is_team_leader(
    db: AsyncSession,
    team_id: UUID,
    user_id: UUID,
) -> bool:
    """Check if a user is the leader of a team."""
    result = await db.execute(
        select(TeamMembership).where(
            TeamMembership.team_id == str(team_id),
            TeamMembership.user_id == str(user_id),
            TeamMembership.role_in_team == TeamRoleType.LEADER,
        )
    )
    return result.scalar_one_or_none() is not None


async def get_team_members(
    db: AsyncSession,
    team_id: UUID,
) -> list[TeamMembership]:
    """Get all members of a team."""
    result = await db.execute(
        select(TeamMembership).where(TeamMembership.team_id == str(team_id))
    )
    return list(result.scalars().all())


async def remove_team_member(
    db: AsyncSession,
    team_id: UUID,
    user_id: UUID,
    requester_id: UUID,
) -> bool:
    """Remove a member from a team.
    
    Only team leader or the member themselves can remove a member.
    Only allowed during team formation period.
    """
    team = await get_team(db, team_id)
    if not team:
        raise ValueError("Team not found")

    # Check if team formation period is active
    if not await is_team_formation_active(db, team.event_id):
        raise ValueError("Team formation period has ended")

    # Check if requester is team leader or the member themselves
    is_leader = await is_team_leader(db, team_id, requester_id)
    if not is_leader and str(requester_id) != str(user_id):
        raise ValueError("Only team leader or the member themselves can remove a member")

    # Cannot remove the team leader
    if await is_team_leader(db, team_id, user_id):
        raise ValueError("Cannot remove team leader")

    result = await db.execute(
        select(TeamMembership).where(
            TeamMembership.team_id == str(team_id),
            TeamMembership.user_id == str(user_id),
        )
    )
    membership = result.scalar_one_or_none()
    if not membership:
        raise ValueError("Member not found")

    await db.delete(membership)
    await db.flush()
    return True
