"""Team API routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import require_role, require_role_global, get_current_user
from app.services.team_service import (
    create_team,
    get_team,
    join_team,
    get_user_teams,
    get_team_members,
    remove_team_member,
)
from app.schemas.team import TeamCreate, TeamJoin, TeamResponse, TeamMembershipResponse, TeamWithMembers
from app.models.user import User
from app.services.webhook_service import emit as emit_webhook
from app.schemas.api import TeamDetailOut

router = APIRouter(tags=["teams"])


@router.post("/events/{event_id}/teams", response_model=TeamResponse, status_code=status.HTTP_201_CREATED)
async def create_new_team(
    event_id: UUID,
    team_data: TeamCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_global(["participant"])),
):
    """Create a new team (participant only)."""
    try:
        team = await create_team(
            db=db,
            event_id=event_id,
            name=team_data.name,
            creator_id=current_user.id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    await emit_webhook(db, event_id, "team.created", {"team_id": team.id, "name": team.name})
    return TeamResponse.model_validate(team)


@router.post("/teams/{team_id}/join", response_model=TeamMembershipResponse)
async def join_existing_team(
    team_id: UUID,
    join_data: TeamJoin,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_global(["participant"])),
):
    """Join a team using invite code (participant only)."""
    try:
        membership = await join_team(
            db=db,
            team_id=team_id,
            user_id=current_user.id,
            invite_code=join_data.invite_code,
        )
        return TeamMembershipResponse.model_validate(membership)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/teams/{team_id}", response_model=TeamDetailOut)
async def get_team_detail(
    team_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get team details (team members only)."""
    from app.services.team_service import is_team_member

    if not await is_team_member(db, team_id, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this team",
        )

    team = await get_team(db, team_id)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )

    members = await get_team_members(db, team_id)
    from sqlalchemy import select as sa_select
    from app.models.user import User as UserModel
    from app.models.submission import Submission

    enriched = []
    for m in members:
        result = await db.execute(sa_select(UserModel).where(UserModel.id == str(m.user_id)))
        user = result.scalar_one_or_none()
        enriched.append({
            "user_id": m.user_id,
            "name": user.name if user else str(m.user_id),
            "email": user.email if user else "",
            "is_lead": m.role_in_team.value == "leader",
            "role_in_team": m.role_in_team.value,
        })
    sub_result = await db.execute(sa_select(Submission).where(Submission.team_id == str(team_id)))
    sub = sub_result.scalars().first()
    return {
        "id": team.id,
        "event_id": team.event_id,
        "name": team.name,
        "invite_code": team.invite_code,
        "created_at": team.created_at.isoformat() if team.created_at else None,
        "members": enriched,
        "submission_id": sub.id if sub else None,
    }


@router.get("/events/{event_id}/teams/mine", response_model=list[TeamDetailOut])
async def get_my_teams(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_global(["participant"])),
):
    """Get teams the current user belongs to, with members."""
    from sqlalchemy import select as sa_select
    from app.models.submission import Submission
    from app.models.user import User as UserModel

    teams = await get_user_teams(db, event_id, current_user.id)
    out: list[TeamWithMembers] = []
    for t in teams:
        resp = TeamWithMembers.model_validate(t)
        members = await get_team_members(db, t.id)
        enriched = []
        for m in members:
            result = await db.execute(sa_select(UserModel).where(UserModel.id == str(m.user_id)))
            user = result.scalar_one_or_none()
            item = TeamMembershipResponse.model_validate(m)
            # Stash display fields via extra attributes the schema ignores;
            # frontend maps role_in_team → is_lead and needs name/email from user.
            # Use a plain dict response instead:
            enriched.append({
                "user_id": m.user_id,
                "name": user.name if user else str(m.user_id),
                "email": user.email if user else "",
                "is_lead": m.role_in_team.value == "leader",
                "role_in_team": m.role_in_team.value,
            })
        resp.members = []  # type: ignore[assignment]
        sub_result = await db.execute(
            sa_select(Submission).where(Submission.event_id == str(event_id))
        )
        subs = list(sub_result.scalars().all())
        # Find first submission for this team
        sub_id = next((s.id for s in subs if s.team_id == str(t.id)), None)
        out.append(resp)
        # Attach via response override below
        resp.__dict__["members_display"] = enriched
        resp.__dict__["submission_id"] = sub_id
    # Return as TeamWithMembers-compatible dicts with display members
    result_list = []
    for t, resp in zip(teams, out):
        result_list.append({
            "id": resp.id,
            "event_id": resp.event_id,
            "name": resp.name,
            "invite_code": resp.invite_code,
            "created_at": resp.created_at.isoformat() if resp.created_at else None,
            "members": resp.__dict__.get("members_display", []),
            "submission_id": resp.__dict__.get("submission_id"),
        })
    return result_list


@router.delete("/teams/{team_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_team_member_endpoint(
    team_id: UUID,
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a member from a team.
    
    Only team leader or the member themselves can remove.
    Only allowed during team formation period.
    """
    try:
        await remove_team_member(db, team_id, user_id, current_user.id)
    except ValueError as e:
        raise HTTPException(
            status_code=(
                status.HTTP_403_FORBIDDEN
                if str(e).startswith("Only team leader")
                else status.HTTP_400_BAD_REQUEST
            ),
            detail=str(e),
        )
