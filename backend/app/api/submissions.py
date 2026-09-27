"""Submission API routes."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import require_role, require_role_global, get_current_user, get_current_user_optional, hide_draft_event
from app.services.submission_service import (
    create_submission,
    get_submission,
    update_submission,
    submit_submission,
    list_event_submissions,
    DeadlinePassedError,
)
from app.services.team_service import is_team_leader, is_team_member
from app.schemas.submission import (
    SubmissionCreate,
    SubmissionUpdate,
    SubmissionResponse,
)
from app.models.user import User
from app.services.webhook_service import emit as emit_webhook
from app.schemas.api import SubmissionView

router = APIRouter(tags=["submissions"])


@router.post("/teams/{team_id}/submissions", response_model=SubmissionResponse, status_code=status.HTTP_201_CREATED)
async def create_team_submission(
    team_id: UUID,
    submission_data: SubmissionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_global(["participant"])),
):
    """Create a new submission for a team (team leader only)."""
    if not await is_team_leader(db, team_id, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only team leader can create submissions",
        )

    # Get team to find event_id
    from app.services.team_service import get_team
    team = await get_team(db, team_id)
    if not team:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Team not found",
        )

    try:
        submission = await create_submission(
            db=db,
            team_id=team_id,
            event_id=team.event_id,
            name=submission_data.name,
            creator_id=current_user.id,
            track_id=submission_data.track_id,
            tagline=submission_data.tagline,
            description_md=submission_data.description_md,
            thumbnail_url=submission_data.thumbnail_url,
            gallery_image_urls=submission_data.gallery_image_urls,
            demo_video_url=submission_data.demo_video_url,
            repo_url=submission_data.repo_url,
            live_url=submission_data.live_url,
            tech_tags=submission_data.tech_tags,
            custom_answers=submission_data.custom_answers,
        )
        return SubmissionResponse.model_validate(submission)
    except DeadlinePassedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/submissions/{submission_id}", response_model=SubmissionView)
async def get_submission_detail(
    submission_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """Get submission details."""
    submission = await get_submission(db, submission_id)
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    # If draft, only team members can view
    from app.models.submission import SubmissionStatus
    if submission.status == SubmissionStatus.DRAFT:
        if not current_user or not await is_team_member(db, submission.team_id, current_user.id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Submission not found",
            )

    item = SubmissionResponse.model_validate(submission).model_dump()
    item.update({
        "description": submission.description_md or "",
        "images": submission.gallery_image_urls or [],
        "video_url": submission.demo_video_url or "",
        "tags": submission.tech_tags or [],
        "updated_at": submission.last_edited_at.isoformat() if submission.last_edited_at else submission.created_at.isoformat(),
        "team_name": "",
        "track_name": None,
    })
    return item


@router.patch("/submissions/{submission_id}", response_model=SubmissionView)
async def update_submission_detail(
    submission_id: UUID,
    submission_data: SubmissionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_global(["participant"])),
):
    """Update submission (team leader only, deadline enforced)."""
    submission = await get_submission(db, submission_id)
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    if not await is_team_leader(db, submission.team_id, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only team leader can update submissions",
        )

    try:
        updated = await update_submission(
            db,
            submission_id,
            **submission_data.model_dump(exclude_unset=True),
        )
    except DeadlinePassedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    item = SubmissionResponse.model_validate(updated).model_dump()
    item.update({
        "description": updated.description_md or "",
        "images": updated.gallery_image_urls or [],
        "video_url": updated.demo_video_url or "",
        "tags": updated.tech_tags or [],
        "updated_at": updated.last_edited_at.isoformat() if updated.last_edited_at else updated.created_at.isoformat(),
        "team_name": "",
        "track_name": None,
    })
    return item


@router.post("/submissions/{submission_id}/submit", response_model=SubmissionView)
async def submit_submission_endpoint(
    submission_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role_global(["participant"])),
):
    """Submit a draft submission (team leader only, deadline enforced)."""
    submission = await get_submission(db, submission_id)
    if not submission:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submission not found",
        )

    if not await is_team_leader(db, submission.team_id, current_user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only team leader can submit",
        )

    try:
        submitted = await submit_submission(db, submission_id)
    except DeadlinePassedError as e:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(e),
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    await emit_webhook(db, submitted.event_id, "submission.submitted",
                       {"submission_id": submitted.id, "name": submitted.name, "team_id": submitted.team_id})
    item = SubmissionResponse.model_validate(submitted).model_dump()
    item.update({
        "description": submitted.description_md or "",
        "images": submitted.gallery_image_urls or [],
        "video_url": submitted.demo_video_url or "",
        "tags": submitted.tech_tags or [],
        "updated_at": submitted.last_edited_at.isoformat() if submitted.last_edited_at else submitted.created_at.isoformat(),
        "team_name": "",
        "track_name": None,
    })
    return item


@router.get("/events/{event_id}/submissions", response_model=list[SubmissionView])
async def list_submissions_gallery(
    event_id: UUID,
    track_id: Optional[UUID] = Query(None),
    tag: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1, le=100_000),
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """List submissions for public gallery (only submitted submissions visible; 404 while the event is a draft)."""
    await hide_draft_event(db, event_id, current_user)
    from sqlalchemy import select as sa_select
    from app.models.team import Team
    submissions, total = await list_event_submissions(
        db,
        event_id,
        track_id=track_id,
        tag=tag,
        search=search,
        page=page,
        limit=limit,
    )
    from app.models.event import Track as EventTrack

    # Batch the name lookups (2 queries per page instead of 2 per project); columns only, no eager loads
    from sqlalchemy.orm import lazyload
    team_ids = {str(s.team_id) for s in submissions}
    track_ids = {str(s.track_id) for s in submissions if s.track_id}
    team_names = {
        tid: name for tid, name in (
            await db.execute(sa_select(Team.id, Team.name).where(Team.id.in_(team_ids or {""})))
        ).all()
    }
    track_names = {
        tid: name for tid, name in (
            await db.execute(sa_select(EventTrack.id, EventTrack.name).where(EventTrack.id.in_(track_ids or {""})))
        ).all()
    }
    out = []
    for s in submissions:
        item = SubmissionResponse.model_validate(s).model_dump()
        item["team_name"] = team_names.get(str(s.team_id), "")
        item["track_name"] = track_names.get(str(s.track_id)) if s.track_id else None
        # UI aliases
        item["description"] = s.description_md or ""
        item["images"] = s.gallery_image_urls or []
        item["video_url"] = s.demo_video_url or ""
        item["tags"] = s.tech_tags or []
        item["updated_at"] = s.last_edited_at.isoformat() if s.last_edited_at else s.created_at.isoformat()
        out.append(item)
    return out
