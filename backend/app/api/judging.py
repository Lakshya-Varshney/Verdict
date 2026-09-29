"""Judging API routes."""

import uuid
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.api.deps import require_role, require_role_global, require_submission_role, get_current_user, get_current_user_optional, hide_draft_event
from app.services.judging_engine import (
    assign_reviewers,
    calculate_raw_weighted_score,
    normalize_with_meta,
)
from app.models.judging import (
    RubricCriterion,
    JudgeAssignment,
    Score,
    NormalizedScore,
    AssignmentStatus,
)
from app.models.event import EventRole, EventRoleType
from app.models.submission import Submission
from app.services.audit_service import create_audit_log
from app.services.certificate_service import CertError, build_score_attestation
from app.services.webhook_service import emit as emit_webhook
from app.utils.fingerprint import client_ip
from app.models.user import User
from app.schemas.judging import (
    RubricCriterionCreate,
    RubricCriterionResponse,
    JudgeAssignmentCreate,
    JudgeAssignmentResponse,
    ScoreCreate,
    ScoreBatchCreate,
    ScoreResponse,
    NormalizedScoreResponse,
    JudgingProgress,
    JudgingResult,
)
from app.schemas.api import AttestationOut, NormalizeOut, AssignResult, AssignmentRow, AssignmentSetOut, CriterionOut, JudgeScoresOut, OkOut, ProgressOut, ResultsOut

router = APIRouter(tags=["judging"])


@router.post("/events/{event_id}/rubric/criteria", response_model=CriterionOut, status_code=status.HTTP_201_CREATED)
async def create_rubric_criterion(
    event_id: UUID,
    criterion_data: RubricCriterionCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(["organizer", "admin"])),
):
    """Create a rubric criterion (organizer only)."""
    criterion = RubricCriterion(
        event_id=str(event_id),
        track_id=str(criterion_data.track_id) if criterion_data.track_id else None,
        name=criterion_data.name,
        description=criterion_data.description,
        weight=criterion_data.weight,
        scale_min=criterion_data.scale_min,
        scale_max=criterion_data.scale_max,
    )
    db.add(criterion)
    await db.flush()
    item = RubricCriterionResponse.model_validate(criterion).model_dump()
    item["max_score"] = criterion.scale_max
    return item


@router.get("/events/{event_id}/rubric/criteria", response_model=list[CriterionOut])
async def list_rubric_criteria(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    """List rubric criteria for an event (public; 404 while the event is a draft, except for its organizers)."""
    await hide_draft_event(db, event_id, current_user)
    result = await db.execute(
        select(RubricCriterion).where(RubricCriterion.event_id == str(event_id))
    )
    criteria = list(result.scalars().all())
    out = []
    for c in criteria:
        item = RubricCriterionResponse.model_validate(c).model_dump()
        item["max_score"] = c.scale_max
        out.append(item)
    return out


@router.delete("/events/{event_id}/rubric/criteria/{criterion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rubric_criterion(
    event_id: UUID,
    criterion_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(["organizer", "admin"])),
):
    """Delete a rubric criterion (organizer only)."""
    result = await db.execute(
        select(RubricCriterion).where(
            RubricCriterion.event_id == str(event_id),
            RubricCriterion.id == str(criterion_id),
        )
    )
    criterion = result.scalar_one_or_none()
    if not criterion:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Criterion not found")
    from sqlalchemy import func as sa_func

    if ((await db.execute(select(sa_func.count(Score.id)).where(Score.criterion_id == criterion.id))).scalar() or 0) > 0:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="This criterion already has scores; judgments are never deleted")
    await db.delete(criterion)


@router.post("/events/{event_id}/judging/assign", response_model=AssignResult)
async def assign_judges(
    event_id: UUID,
    assign_data: JudgeAssignmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(["organizer", "admin"])),
):
    """Assign judges to submissions (organizer only)."""
    # Get submissions for this event
    result = await db.execute(
        select(Submission).where(Submission.event_id == str(event_id))
    )
    submissions = [{"id": s.id, "team_id": s.team_id} for s in result.scalars().all()]

    # Get judges for this event
    result = await db.execute(
        select(EventRole).where(
            EventRole.event_id == str(event_id),
            EventRole.role == EventRoleType.JUDGE,
        )
    )
    judge_ids = [r.user_id for r in result.scalars().all()]

    # Teams each judge belongs to in this event (conflict of interest -> never assigned)
    from app.models.team import Team, TeamMembership

    mem = await db.execute(
        select(TeamMembership.user_id, TeamMembership.team_id)
        .join(Team, Team.id == TeamMembership.team_id)
        .where(Team.event_id == str(event_id), TeamMembership.user_id.in_(judge_ids or [""]))
    )
    judge_teams: dict[str, set] = {}
    for uid, tid in mem.all():
        judge_teams.setdefault(uid, set()).add(tid)
    judges = [{"id": jid, "team_ids": judge_teams.get(jid, set())} for jid in judge_ids]

    if not submissions or not judges:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No submissions or judges found",
        )

    # Run assignment algorithm
    assignments = assign_reviewers(
        submissions=submissions,
        judges=judges,
        reviews_per_submission=assign_data.reviews_per_submission,
    )

    # Create database records (skip existing)
    created_assignments = []
    batch_id = str(uuid.uuid4())

    for assign in assignments:
        # Check if assignment already exists
        result = await db.execute(
            select(JudgeAssignment).where(
                JudgeAssignment.judge_id == assign["judge_id"],
                JudgeAssignment.submission_id == assign["submission_id"],
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.batch_id = batch_id
            existing.status = AssignmentStatus.PENDING
            created_assignments.append(existing)
            continue

        ja = JudgeAssignment(
            judge_id=assign["judge_id"],
            submission_id=assign["submission_id"],
            batch_id=batch_id,
            status=AssignmentStatus.PENDING,
        )
        db.add(ja)
        created_assignments.append(ja)

    await db.flush()
    for ja in created_assignments:
        await create_audit_log(
            db, "assignment.create", "judge_assignment", ja.id, actor_id=current_user.id, event_id=event_id,
            extra_data={"role": "organizer", "batch_id": batch_id, "judge_id": ja.judge_id,
                        "submission_id": ja.submission_id, "detail": f"assigned judge {ja.judge_id} to {ja.submission_id}"},
        )
    return {"ok": True, "assignments": [JudgeAssignmentResponse.model_validate(a).model_dump() for a in created_assignments]}


@router.get("/events/{event_id}/judging/assignments/mine", response_model=list[AssignmentRow])
async def get_my_assignments(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(["judge", "organizer", "admin"])),
):
    """Get current judge's assignments enriched for the UI."""
    from app.models.team import Team
    from app.models.event import Track as EventTrack

    # Criteria count for progress
    crit_result = await db.execute(
        select(RubricCriterion).where(RubricCriterion.event_id == str(event_id))
    )
    criteria = list(crit_result.scalars().all())
    crit_count = len(criteria)
    crit_ids = set(c.id for c in criteria)

    result = await db.execute(
        select(JudgeAssignment)
        .join(Submission)
        .where(
            Submission.event_id == str(event_id),
            JudgeAssignment.judge_id == current_user.id,
        )
    )
    assignments = list(result.scalars().all())

    # Scores for this judge on this event
    score_result = await db.execute(
        select(Score)
        .join(Submission)
        .where(
            Submission.event_id == str(event_id),
            Score.judge_id == current_user.id,
        )
    )
    scores = list(score_result.scalars().all())
    from collections import defaultdict
    by_sub = defaultdict(set)
    for s in scores:
        by_sub[s.submission_id].add(s.criterion_id)

    # Submissions + teams + tracks
    sub_result = await db.execute(
        select(Submission).where(Submission.event_id == str(event_id))
    )
    subs = {s.id: s for s in sub_result.scalars().all()}
    team_result = await db.execute(select(Team).where(Team.event_id == str(event_id)))
    teams = {t.id: t for t in team_result.scalars().all()}
    track_result = await db.execute(select(EventTrack).where(EventTrack.event_id == str(event_id)))
    tracks = {t.id: t for t in track_result.scalars().all()}

    out = []
    for a in assignments:
        sub = subs.get(a.submission_id)
        team = teams.get(sub.team_id) if sub else None
        track = tracks.get(sub.track_id) if sub and sub.track_id else None
        scored = len(by_sub.get(a.submission_id, set()))
        out.append({
            "id": a.id,
            "event_id": str(event_id),
            "submission_id": a.submission_id,
            "judge_id": a.judge_id,
            "submission_name": sub.name if sub else "",
            "team_name": team.name if team else "",
            "track_name": track.name if track else None,
            "scored_criteria": scored,
            "total_criteria": crit_count,
            "complete": crit_count > 0 and scored >= crit_count,
            "status": a.status.value if hasattr(a.status, "value") else str(a.status),
            "assigned_at": a.assigned_at.isoformat() if a.assigned_at else None,
        })
    return out


@router.get("/events/{event_id}/judging/assignments", response_model=AssignmentSetOut)
async def get_all_assignments(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(["organizer", "admin"])),
):
    """Get all judge assignments for an event (organizer/admin only)."""
    from app.models.team import Team
    from app.models.event import Track as EventTrack
    from app.models.user import User as UserModel
    from sqlalchemy import select as sa_select

    # Criteria count for progress
    crit_result = await db.execute(
        select(RubricCriterion).where(RubricCriterion.event_id == str(event_id))
    )
    criteria = list(crit_result.scalars().all())
    crit_count = len(criteria)
    crit_ids = set(c.id for c in criteria)

    # All assignments
    result = await db.execute(
        select(JudgeAssignment)
        .join(Submission)
        .where(Submission.event_id == str(event_id))
    )
    assignments = list(result.scalars().all())

    # All scores
    score_result = await db.execute(
        select(Score)
        .join(Submission)
        .where(Submission.event_id == str(event_id))
    )
    scores = list(score_result.scalars().all())
    from collections import defaultdict
    by_sub = defaultdict(set)
    for s in scores:
        by_sub[s.submission_id].add(s.criterion_id)

    # Submissions + teams + tracks
    sub_result = await db.execute(select(Submission).where(Submission.event_id == str(event_id)))
    subs = {s.id: s for s in sub_result.scalars().all()}
    team_result = await db.execute(select(Team).where(Team.event_id == str(event_id)))
    teams = {t.id: t for t in team_result.scalars().all()}
    track_result = await db.execute(select(EventTrack).where(EventTrack.event_id == str(event_id)))
    tracks = {t.id: t for t in track_result.scalars().all()}

    # Load judge names
    judge_ids = set(a.judge_id for a in assignments)
    users = {}
    if judge_ids:
        u_result = await db.execute(sa_select(UserModel).where(UserModel.id.in_(list(judge_ids))))
        users = {u.id: u for u in u_result.scalars().all()}

    out = []
    for a in assignments:
        sub = subs.get(a.submission_id)
        team = teams.get(sub.team_id) if sub else None
        track = tracks.get(sub.track_id) if sub and sub.track_id else None
        scored = len(by_sub.get(a.submission_id, set()))
        judge = users.get(a.judge_id)
        out.append({
            "id": a.id,
            "event_id": str(event_id),
            "submission_id": a.submission_id,
            "judge_id": a.judge_id,
            "judge_name": judge.name if judge else str(a.judge_id),
            "submission_name": sub.name if sub else "",
            "team_name": team.name if team else "",
            "track_name": track.name if track else None,
            "scored_criteria": scored,
            "total_criteria": crit_count,
            "complete": crit_count > 0 and scored >= crit_count,
            "status": a.status.value if hasattr(a.status, "value") else str(a.status),
            "assigned_at": a.assigned_at.isoformat() if a.assigned_at else None,
        })
    return {"assignments": out}


@router.get("/events/{event_id}/judging/progress", response_model=ProgressOut)
async def get_judging_progress(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(["organizer", "admin"])),
):
    """Get judging progress dashboard (organizer/admin only)."""
    # Count submissions
    result = await db.execute(
        select(Submission).where(Submission.event_id == str(event_id))
    )
    total_submissions = len(result.scalars().all())

    # Count judges
    result = await db.execute(
        select(EventRole).where(
            EventRole.event_id == str(event_id),
            EventRole.role == EventRoleType.JUDGE,
        )
    )
    total_judges = len(result.scalars().all())

    # Count assignments
    result = await db.execute(
        select(JudgeAssignment)
        .join(Submission)
        .where(Submission.event_id == str(event_id))
    )
    assignments = list(result.scalars().all())
    assignments_total = len(assignments)
    assignments_completed = sum(
        1 for a in assignments if a.status == AssignmentStatus.COMPLETED
    )

    completion = (assignments_completed / assignments_total * 100) if assignments_total > 0 else 0

    # UI Progress shape: {event_id, judges[], total_assignments, total_complete}
    from app.models.user import User as UserModel
    from sqlalchemy import select as sa_select

    # Get judge ids for this event
    judges_result = await db.execute(
        select(EventRole).where(
            EventRole.event_id == str(event_id),
            EventRole.role == EventRoleType.JUDGE,
        )
    )
    judge_roles = list(judges_result.scalars().all())

    # Load all assignments with scores for started/complete detection
    result = await db.execute(
        select(JudgeAssignment)
        .join(Submission)
        .where(Submission.event_id == str(event_id))
    )
    all_assignments = list(result.scalars().all())

    result = await db.execute(
        select(Score).join(Submission).where(Submission.event_id == str(event_id))
    )
    all_scores = list(result.scalars().all())
    score_keys = set((s.judge_id, s.submission_id) for s in all_scores)

    # Criteria count
    crit_result = await db.execute(
        select(RubricCriterion).where(RubricCriterion.event_id == str(event_id))
    )
    criteria = list(crit_result.scalars().all())
    crit_ids = set(c.id for c in criteria)
    crit_count = len(criteria)

    judges_ui = []
    for jr in judge_roles:
        u_result = await db.execute(sa_select(UserModel).where(UserModel.id == str(jr.user_id)))
        user = u_result.scalar_one_or_none()
        mine = [a for a in all_assignments if a.judge_id == jr.user_id]
        complete = 0
        started = 0
        for a in mine:
            sc = [s for s in all_scores if s.judge_id == a.judge_id and s.submission_id == a.submission_id]
            scored_crits = set(s.criterion_id for s in sc)
            if crit_count and scored_crits >= crit_ids:
                complete += 1
            elif sc:
                started += 1
        judges_ui.append({
            "judge_id": jr.user_id,
            "judge_name": user.name if user else str(jr.user_id),
            "assigned": len(mine),
            "complete": complete,
            "started": started,
        })

    return {
        "event_id": str(event_id),
        "judges": judges_ui,
        "total_assignments": assignments_total,
        "total_complete": sum(j["complete"] for j in judges_ui),
        # legacy fields kept for any direct consumers
        "total_submissions": total_submissions,
        "total_judges": total_judges,
        "assignments_total": assignments_total,
        "assignments_completed": assignments_completed,
        "completion_percentage": completion,
    }


@router.post("/submissions/{submission_id}/scores", response_model=OkOut)
async def submit_scores(
    submission_id: UUID,
    score_data: ScoreBatchCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_submission_role(["judge"])),
):
    """Submit scores for a submission (judge only, must be assigned).
    Accepts either a single {criterion_id, value, comment} or a batch {scores: [...]}.
    """
    # Normalize: batch from UI adapter or legacy single
    if score_data.scores:
        scores_list = score_data.scores
    elif score_data.criterion_id is not None:
        scores_list = [{
            "criterion_id": score_data.criterion_id,
            "raw_value": score_data.raw_value if score_data.raw_value is not None else (score_data.value or 0),
            "comment": score_data.comment,
        }]
    else:
        scores_list = []
    # Verify assignment exists
    result = await db.execute(
        select(JudgeAssignment).where(
            JudgeAssignment.judge_id == current_user.id,
            JudgeAssignment.submission_id == str(submission_id),
        )
    )
    assignment = result.scalar_one_or_none()
    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not assigned to this submission",
        )

    sub_row = (await db.execute(select(Submission).where(Submission.id == str(submission_id)))).scalar_one_or_none()
    # judging window, enforced here rather than in the UI: no changing scores once results are published
    if sub_row is not None:
        from datetime import datetime, timezone

        from app.models.event import Event, EventStatus

        ev = (await db.execute(select(Event).where(Event.id == sub_row.event_id))).scalar_one()
        now = datetime.now(timezone.utc)
        aware = lambda d: d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)  # noqa: E731
        if ev.status == EventStatus.CLOSED:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Scoring is closed: results have been published")
        if aware(ev.judging_opens_at) and now < aware(ev.judging_opens_at):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Judging has not opened yet")
        if aware(ev.judging_closes_at) and now > aware(ev.judging_closes_at):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Judging has closed")
    criteria = {
        c.id: c
        for c in (
            await db.execute(select(RubricCriterion).where(RubricCriterion.event_id == sub_row.event_id))
        ).scalars().all()
    } if sub_row else {}

    created_scores = []
    for score in scores_list:
        cid = str(score["criterion_id"] if isinstance(score, dict) else score.criterion_id)
        rval = float(score["raw_value"] if isinstance(score, dict) else score.raw_value)
        crit = criteria.get(cid)
        if crit is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown criterion for this event")
        if not (crit.scale_min <= rval <= crit.scale_max):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Score for '{crit.name}' must be between {crit.scale_min:g} and {crit.scale_max:g}",
            )
        cmt = (score["comment"] if isinstance(score, dict) else score.comment) or None
        # Upsert score
        result = await db.execute(
            select(Score).where(
                Score.judge_id == current_user.id,
                Score.submission_id == str(submission_id),
                Score.criterion_id == cid,
            )
        )
        existing = result.scalar_one_or_none()

        old_value = existing.raw_value if existing else None
        if existing:
            existing.raw_value = rval
            existing.comment = cmt
            created_scores.append(existing)
        else:
            new_score = Score(
                judge_id=current_user.id,
                submission_id=str(submission_id),
                criterion_id=cid,
                raw_value=rval,
                comment=cmt,
            )
            db.add(new_score)
            created_scores.append(new_score)
        await db.flush()
        await create_audit_log(
            db, "score.update" if old_value is not None else "score.create", "score",
            (existing or new_score).id, actor_id=current_user.id, event_id=sub_row.event_id if sub_row else None,
            extra_data={"role": "judge", "ip": client_ip(request), "submission_id": str(submission_id),
                        "criterion_id": cid, "old": old_value, "new": rval,
                        "detail": f"{crit.name}: {old_value} -> {rval}" if old_value is not None else f"{crit.name}: {rval}"},
        )

    await db.flush()
    return {"ok": True}


@router.get("/submissions/{submission_id}/scores/mine", response_model=JudgeScoresOut)
async def get_my_scores(
    submission_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_submission_role(["judge"])),
):
    """Get current judge's scores for a submission (judge only)."""
    result = await db.execute(
        select(Score).where(
            Score.judge_id == current_user.id,
            Score.submission_id == str(submission_id),
        )
    )
    scores = list(result.scalars().all())
    return {
        "judge_id": current_user.id,
        "judge_name": current_user.name,
        "scores": [
            {
                "criterion_id": s.criterion_id,
                "value": s.raw_value,
                "comment": s.comment,
            }
            for s in scores
        ],
    }


@router.get("/submissions/{submission_id}/scores", response_model=list[JudgeScoresOut])
async def get_all_scores(
    submission_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_submission_role(["organizer", "admin"])),
):
    """Get all judges' scores for a submission (organizer/admin only)."""
    result = await db.execute(
        select(Score).where(Score.submission_id == str(submission_id))
    )
    scores = list(result.scalars().all())
    # Group by judge → JudgeScores[]
    from collections import defaultdict
    by_judge = defaultdict(list)
    for s in scores:
        by_judge[s.judge_id].append(s)
    from app.models.user import User as UserModel
    from sqlalchemy import select as sa_select
    out = []
    for jid, items in by_judge.items():
        u_result = await db.execute(sa_select(UserModel).where(UserModel.id == str(jid)))
        user = u_result.scalar_one_or_none()
        out.append({
            "judge_id": jid,
            "judge_name": user.name if user else str(jid),
            "scores": [
                {"criterion_id": s.criterion_id, "value": s.raw_value, "comment": s.comment}
                for s in items
            ],
        })
    return out


async def _compute_results(db: AsyncSession, event_id: UUID) -> dict:
    """Single source of truth for raw/normalised results (results, CSV, normalize).

    * a judge's score for a submission is the weighted mean over the criteria they
      actually scored (partial reviews count, nothing assumes a fixed rubric size);
    * per-judge z-scores via ``normalize_with_meta`` (zero-variance judges flagged);
    * review counts per submission may differ freely.
    Ranking ties: more judge reviews, then earlier submission time, then name.
    """
    import statistics as stats
    from collections import defaultdict
    from datetime import datetime, timezone

    from app.models.event import Event, Track
    from app.models.team import Team

    ev_result = await db.execute(select(Event).where(Event.id == str(event_id)))
    event = ev_result.scalar_one_or_none()
    status_val = event.status.value if event and event.status else "draft"
    status_map = {"live": "open", "closed": "published"}
    ui_status = status_map.get(status_val, status_val)

    result = await db.execute(select(Submission).where(Submission.event_id == str(event_id)))
    submissions = {s.id: s for s in result.scalars().all()}
    teams = {
        t.id: t
        for t in (await db.execute(select(Team).where(Team.event_id == str(event_id)))).scalars().all()
    }
    tracks = {
        t.id: t
        for t in (await db.execute(select(Track).where(Track.event_id == str(event_id)))).scalars().all()
    }
    weights = {
        c.id: c.weight
        for c in (
            await db.execute(select(RubricCriterion).where(RubricCriterion.event_id == str(event_id)))
        ).scalars().all()
    }

    all_scores = list(
        (
            await db.execute(select(Score).join(Submission).where(Submission.event_id == str(event_id)))
        ).scalars().all()
    )

    by_pair: dict[tuple, list[dict]] = defaultdict(list)
    for sc in all_scores:
        by_pair[(sc.judge_id, sc.submission_id)].append(
            {"criterion_id": sc.criterion_id, "raw_value": sc.raw_value}
        )

    criteria_list = [{"id": cid, "weight": w} for cid, w in weights.items()]
    judge_scores: dict[str, list[dict]] = defaultdict(list)
    raw_by_sub: dict[str, list[float]] = defaultdict(list)
    for (jid, sid), items in by_pair.items():
        if sid not in submissions:
            continue
        t = calculate_raw_weighted_score(items, criteria_list)
        judge_scores[jid].append({"submission_id": sid, "weighted_score": t})
        raw_by_sub[sid].append(t)

    normalized, meta = normalize_with_meta(dict(judge_scores))
    pooled_mu, pooled_sd = meta["pooled_mean"], meta["pooled_sd"]

    def ts(sub: Submission) -> float:
        return sub.submitted_at.timestamp() if sub.submitted_at else float("inf")

    rows = []
    for sid, raws in raw_by_sub.items():
        sub = submissions[sid]
        team = teams.get(sub.team_id)
        track = tracks.get(sub.track_id) if sub.track_id else None
        z = normalized.get(sid, 0.0)
        rows.append({
            "submission_id": sid,
            "name": sub.name,
            "team_name": team.name if team else "",
            "track_name": track.name if track else None,
            "judge_count": len(raws),
            "raw_mean": stats.mean(raws),
            "norm_z": z,
            # z re-expressed in raw points (monotone in z) so it is comparable to raw_mean
            "norm_mean": pooled_mu + z * pooled_sd,
            "raw_rank": 0,
            "norm_rank": None,
            "scores": [],
            "_ts": ts(sub),
        })

    rows.sort(key=lambda r: (-r["raw_mean"], -r["judge_count"], r["_ts"], r["name"]))
    for i, r in enumerate(rows):
        r["raw_rank"] = i + 1
    rows.sort(key=lambda r: (-r["norm_z"], -r["judge_count"], r["_ts"], r["name"]))
    for i, r in enumerate(rows):
        r["norm_rank"] = i + 1
        del r["_ts"]

    names = {}
    if meta["per_judge"]:
        for u in (
            await db.execute(select(User).where(User.id.in_(list(meta["per_judge"]))))
        ).scalars().all():
            names[u.id] = u.name
    judges = [
        {
            "judge_id": jid,
            "judge_name": names.get(jid, jid),
            "n": st["n"],
            "mean": st["mean"],
            "sd": st["sd"],
            "offset": st["mean"] - pooled_mu,
            "zero_variance": st["zero_variance"],
            "single_review": st["n"] < 2,  # sd undefined; covered by the same pooled-standardisation fallback
        }
        for jid, st in meta["per_judge"].items()
    ]

    return {
        "event_id": str(event_id),
        "normalized": bool(judges),
        "normalized_at": datetime.now(timezone.utc).isoformat() if judges else None,
        "method": "per_judge_z_score",
        "published": ui_status == "published",
        "rows": rows,
        "judges": judges,
        "zero_variance_judges": meta["zero_variance_judges"],
        "single_review_judges": [j for j, st in meta["per_judge"].items() if st["n"] < 2],
        "spread_raw": None,
        "spread_norm": None,
    }


@router.post("/events/{event_id}/judging/normalize", response_model=NormalizeOut)
async def normalize_scores(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(["organizer", "admin"])),
):
    """Recompute normalized scores (organizer only)."""
    from app.services.audit_service import create_audit_log

    results = await _compute_results(db, event_id)

    criteria_ids = [
        c.id
        for c in (
            await db.execute(select(RubricCriterion).where(RubricCriterion.event_id == str(event_id)))
        ).scalars().all()
    ]
    for row in results["rows"]:
        for cid in criteria_ids:
            existing = (
                await db.execute(
                    select(NormalizedScore).where(
                        NormalizedScore.submission_id == row["submission_id"],
                        NormalizedScore.criterion_id == cid,
                        NormalizedScore.method == "per_judge_z_score",
                    )
                )
            ).scalar_one_or_none()
            if existing:
                existing.normalized_value = row["norm_z"]
            else:
                db.add(
                    NormalizedScore(
                        submission_id=row["submission_id"],
                        criterion_id=cid,
                        method="per_judge_z_score",
                        normalized_value=row["norm_z"],
                    )
                )

    for jid in results["zero_variance_judges"]:
        await create_audit_log(
            db,
            action="normalization.zero_variance_judge",
            target_type="user",
            target_id=jid,
            actor_id=current_user.id,
            event_id=event_id,
            extra_data={"role": "organizer", "event_id": str(event_id), "fallback": "pooled-standardised raw score",
                        "detail": f"judge {jid} has zero variance; standardised against the pooled mean/sd"},
        )
    await create_audit_log(
        db, "normalization.run", "event", str(event_id), actor_id=current_user.id, event_id=event_id,
        extra_data={"role": "organizer", "submissions": len(results["rows"]),
                    "zero_variance_judges": len(results["zero_variance_judges"]),
                    "detail": f"normalized {len(results['rows'])} submissions"},
    )

    await db.flush()
    await emit_webhook(db, str(event_id), "judging.normalized",
                       {"submissions": len(results["rows"]), "zero_variance_judges": len(results["zero_variance_judges"])})
    return {
        "message": "Normalization complete",
        "submissions_normalized": len(results["rows"]),
        "zero_variance_judges": results["zero_variance_judges"],
    }


@router.get("/events/{event_id}/judging/export.csv")
async def export_results_csv(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(["organizer", "admin"])),
):
    """Export results as CSV text (UI wraps as blob)."""
    import csv
    import io

    from fastapi.responses import PlainTextResponse

    results = await _compute_results(db, event_id)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["rank", "submission", "team", "track", "judges", "raw_mean", "norm_mean", "norm_z"])
    for r in results["rows"]:
        w.writerow([
            r["norm_rank"],
            r["name"],
            r["team_name"],
            r["track_name"] or "",
            r["judge_count"],
            f"{r['raw_mean']:.3f}",
            f"{r['norm_mean']:.3f}",
            f"{r['norm_z']:.3f}",
        ])
    return PlainTextResponse(buf.getvalue(), media_type="text/csv")


@router.get("/events/{event_id}/judging/results", response_model=ResultsOut)
async def get_judging_results(
    event_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(["organizer", "admin"])),
):
    """Get final judging results (organizer/admin only) as UI Results shape."""
    return await _compute_results(db, event_id)


@router.get("/events/{event_id}/judging/attestation", response_model=AttestationOut)
async def get_score_attestation(
    event_id: UUID,
    judge_id: Optional[UUID] = Query(None, description="An organizer/admin may request another judge's attestation; defaults to yourself"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(["judge", "organizer", "admin"])),
):
    """A judge's own signed proof of exactly what they scored, as of right now.

    Unlike a `judge` certificate (participation counts only, issued once the event closes), this
    carries the actual per-criterion values and is available any time a judge has scored
    something - so a judge can attest "this is what I scored" before the window even closes. Not
    stored: re-request it and you get a fresh signature over your current scores.
    """
    from app.models.event import Event

    event = (await db.execute(select(Event).where(Event.id == str(event_id)))).scalar_one_or_none()
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")

    target_id = str(judge_id) if judge_id else current_user.id
    if str(target_id) != str(current_user.id):
        staff = await db.execute(select(EventRole.id).where(
            EventRole.event_id == str(event_id), EventRole.user_id == str(current_user.id),
            EventRole.role.in_([EventRoleType.ORGANIZER, EventRoleType.ADMIN])))
        if staff.first() is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You can only attest your own scores")
    judge = (await db.execute(select(User).where(User.id == str(target_id)))).scalar_one_or_none()
    if judge is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    try:
        doc = await build_score_attestation(db, event, judge)
    except CertError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)

    await create_audit_log(
        db, "judging.attestation_issued", "attestation", judge.id, actor_id=current_user.id, event_id=event.id,
        extra_data={"role": "self" if str(target_id) == str(current_user.id) else "organizer",
                    "judge_id": str(target_id), "verify_hash": doc["verify_hash"],
                    "detail": f"issued a score attestation ({len(doc['payload']['record']['scores'])} scores)"},
    )
    return doc
