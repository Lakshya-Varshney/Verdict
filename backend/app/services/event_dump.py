"""Whole-event JSON export and restore (T4 bulk import/export).

Import is:
  * validated first (structure, references, enums, score ranges, checksum) so it fails as a whole with a
    precise list of problems (422) and never half-applies;
  * one transaction (any error rolls everything back);
  * an idempotent upsert: ids / natural keys match existing rows, so re-importing the same dump changes nothing;
  * additive: it never deletes rows;
  * safe by construction: no password hashes are imported, users are matched by email, an id that already
    belongs to a *different* event is a 409, imported audit rows are tagged and only accepted back into the
    event they came from.
"""

import hashlib
import json
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.event import Event, EventRole, EventRoleType, EventStatus, Track
from app.models.judging import AssignmentStatus, JudgeAssignment, RubricCriterion, Score
from app.models.submission import Submission, SubmissionStatus
from app.models.team import Team, TeamMembership, TeamRoleType
from app.models.user import User
from app.models.voting import Comment, Vote
from app.schemas.dump import DUMP_FORMAT, DUMP_VERSION, EventDump
from app.services.audit_service import create_audit_log
from app.utils.security import get_password_hash

MAX_ROWS = 200_000
SECTIONS = ["users", "roles", "tracks", "criteria", "teams", "memberships", "submissions",
            "assignments", "scores", "votes", "comments", "audit"]


class DumpError(Exception):
    """Invalid dump (422) or conflict with existing data (409)."""

    def __init__(self, status_code: int, problems: list[str]):
        super().__init__("; ".join(problems[:3]))
        self.status_code = status_code
        self.problems = problems


def _canonical_numbers(obj: Any) -> Any:
    """`3.0` and `3` are the same number: JavaScript (the UI, most tooling) rewrites the former as the latter
    when it re-serialises a dump, so integral floats must hash identically to ints."""
    if isinstance(obj, dict):
        return {k: _canonical_numbers(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_canonical_numbers(v) for v in obj]
    if isinstance(obj, float) and obj.is_integer():
        return int(obj)
    return obj


def checksum_of(dump: EventDump) -> str:
    body = _canonical_numbers(dump.model_dump(mode="json", exclude={"checksum"}))
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ------------------------------------------------------------------ export

async def build_dump(db: AsyncSession, event_id: str) -> EventDump:
    eid = str(event_id)
    ev = (await db.execute(select(Event).where(Event.id == eid))).scalar_one()

    async def rows(model, *where):
        return list((await db.execute(select(model).where(*where))).scalars().all())

    roles = await rows(EventRole, EventRole.event_id == eid)
    tracks = await rows(Track, Track.event_id == eid)
    criteria = await rows(RubricCriterion, RubricCriterion.event_id == eid)
    teams = await rows(Team, Team.event_id == eid)
    team_ids = [t.id for t in teams]
    members = await rows(TeamMembership, TeamMembership.team_id.in_(team_ids or [""]))
    subs = await rows(Submission, Submission.event_id == eid)
    sub_ids = [s.id for s in subs]
    assigns = await rows(JudgeAssignment, JudgeAssignment.submission_id.in_(sub_ids or [""]))
    scores = await rows(Score, Score.submission_id.in_(sub_ids or [""]))
    votes = await rows(Vote, Vote.event_id == eid)
    comments = await rows(Comment, Comment.submission_id.in_(sub_ids or [""]))
    audit = await rows(AuditLog, AuditLog.event_id == eid)

    user_ids = {r.user_id for r in roles} | {m.user_id for m in members} | {a.judge_id for a in assigns} \
        | {s.judge_id for s in scores} | {c.author_id for c in comments if c.author_id} \
        | {a.actor_id for a in audit if a.actor_id} | {ev.organizer_id}
    users = await rows(User, User.id.in_(list(user_ids) or [""]))
    by_team: dict[str, list] = {}
    for m in members:
        by_team.setdefault(m.team_id, []).append({"user_id": m.user_id, "role_in_team": m.role_in_team.value})

    data: dict[str, Any] = {
        "format": DUMP_FORMAT,
        "version": DUMP_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "event": {
            "id": ev.id, "name": ev.name, "slug": ev.slug, "description": ev.description, "status": ev.status.value,
            **{k: _iso(getattr(ev, k)) for k in (
                "start_date", "end_date", "submission_deadline", "judging_opens_at", "judging_closes_at",
                "voting_opens_at", "voting_closes_at", "team_formation_start", "team_formation_end", "created_at")},
            "voting_mode": ev.voting_mode, "votes_per_voter": ev.votes_per_voter, "vote_credits": ev.vote_credits,
        },
        "users": [{"id": u.id, "email": u.email, "name": u.name} for u in sorted(users, key=lambda u: u.email)],
        "roles": [{"user_id": r.user_id, "role": r.role.value} for r in roles],
        "tracks": [{"id": t.id, "name": t.name, "description": t.description} for t in tracks],
        "criteria": [{"id": c.id, "name": c.name, "description": c.description, "weight": c.weight,
                      "scale_min": c.scale_min, "scale_max": c.scale_max, "track_id": c.track_id} for c in criteria],
        "teams": [{"id": t.id, "name": t.name, "invite_code": t.invite_code, "created_at": _iso(t.created_at),
                   "members": by_team.get(t.id, [])} for t in teams],
        "submissions": [{
            "id": s.id, "team_id": s.team_id, "track_id": s.track_id, "name": s.name, "tagline": s.tagline,
            "description_md": s.description_md, "thumbnail_url": s.thumbnail_url,
            "gallery_image_urls": s.gallery_image_urls or [], "demo_video_url": s.demo_video_url,
            "repo_url": s.repo_url, "live_url": s.live_url, "tech_tags": s.tech_tags or [],
            "custom_answers": s.custom_answers or {}, "status": s.status.value, "submitted_at": _iso(s.submitted_at),
            "last_edited_at": _iso(s.last_edited_at), "created_at": _iso(s.created_at)} for s in subs],
        "assignments": [{"id": a.id, "judge_id": a.judge_id, "submission_id": a.submission_id, "batch_id": a.batch_id,
                         "status": a.status.value, "assigned_at": _iso(a.assigned_at)} for a in assigns],
        "scores": [{"id": s.id, "judge_id": s.judge_id, "submission_id": s.submission_id,
                    "criterion_id": s.criterion_id, "raw_value": s.raw_value, "comment": s.comment,
                    "created_at": _iso(s.created_at), "updated_at": _iso(s.updated_at)} for s in scores],
        "votes": [{"id": v.id, "submission_id": v.submission_id, "voter_fingerprint": v.voter_fingerprint,
                   "ip_hash": v.ip_hash, "weight": v.weight, "created_at": _iso(v.created_at)} for v in votes],
        "comments": [{"id": c.id, "submission_id": c.submission_id, "author_id": c.author_id, "body": c.body,
                      "created_at": _iso(c.created_at)} for c in comments],
        "audit": [{"id": a.id, "actor_id": a.actor_id, "action": a.action, "target_type": a.target_type,
                   "target_id": a.target_id, "extra_data": a.extra_data or {}, "created_at": _iso(a.created_at)}
                  for a in sorted(audit, key=lambda a: (a.created_at or datetime.min.replace(tzinfo=timezone.utc)))],
    }
    dump = EventDump.model_validate(data)
    dump.checksum = checksum_of(dump)
    return dump


# ------------------------------------------------------------------ validation

def validate_dump(dump: EventDump) -> list[str]:
    """Structural / referential checks that need no database. Returns human-readable problems."""
    p: list[str] = []
    if dump.format != DUMP_FORMAT:
        p.append(f"format must be '{DUMP_FORMAT}', got '{dump.format}'")
    if dump.version != DUMP_VERSION:
        p.append(f"unsupported dump version {dump.version} (this server reads version {DUMP_VERSION})")
    total = sum(len(getattr(dump, s)) for s in ("users", "roles", "tracks", "criteria", "teams", "submissions",
                                                 "assignments", "scores", "votes", "comments", "audit"))
    if total > MAX_ROWS:
        p.append(f"dump has {total} rows, the limit is {MAX_ROWS}")

    def dupes(name: str, ids: list[str]):
        seen: set = set()
        for i in ids:
            if i in seen:
                p.append(f"{name}: duplicate id {i}")
            seen.add(i)

    for name in ("tracks", "criteria", "teams", "submissions", "assignments", "scores", "votes", "comments", "audit", "users"):
        dupes(name, [r.id for r in getattr(dump, name)])
    emails = [u.email.strip().lower() for u in dump.users]
    if len(emails) != len(set(emails)):
        p.append("users: the same email appears twice")

    users = {u.id for u in dump.users}
    tracks = {t.id for t in dump.tracks}
    crit = {c.id: c for c in dump.criteria}
    teams = {t.id for t in dump.teams}
    subs = {s.id for s in dump.submissions}

    def ref(kind: str, value: Optional[str], pool, where: str):
        if value is not None and value not in pool:
            p.append(f"{where}: unknown {kind} '{value}'")

    role_values = {r.value for r in EventRoleType}
    team_role_values = {r.value for r in TeamRoleType}
    for r in dump.roles:
        ref("user", r.user_id, users, "roles")
        if r.role not in role_values:
            p.append(f"roles: invalid role '{r.role}'")
    for c in dump.criteria:
        ref("track", c.track_id, tracks, f"criteria[{c.name}]")
        if c.scale_min >= c.scale_max:
            p.append(f"criteria[{c.name}]: scale_min must be < scale_max")
    for t in dump.teams:
        for m in t.members:
            ref("user", m.user_id, users, f"teams[{t.name}].members")
            if m.role_in_team not in team_role_values:
                p.append(f"teams[{t.name}]: invalid role_in_team '{m.role_in_team}'")
    from app.schemas.limits import http_url

    sub_status = {s.value for s in SubmissionStatus}
    for s in dump.submissions:
        for fld in ("thumbnail_url", "demo_video_url", "repo_url", "live_url"):
            try:
                http_url(getattr(s, fld) or "")
            except ValueError:
                p.append(f"submissions[{s.name}].{fld}: must be an http:// or https:// URL")
        for u in s.gallery_image_urls:
            try:
                http_url(u)
            except ValueError:
                p.append(f"submissions[{s.name}].gallery_image_urls: must be http:// or https:// URLs")
        ref("team", s.team_id, teams, f"submissions[{s.name}]")
        ref("track", s.track_id, tracks, f"submissions[{s.name}]")
        if s.status not in sub_status:
            p.append(f"submissions[{s.name}]: invalid status '{s.status}'")
    a_status = {s.value for s in AssignmentStatus}
    for a in dump.assignments:
        ref("user", a.judge_id, users, "assignments")
        ref("submission", a.submission_id, subs, "assignments")
        if a.status not in a_status:
            p.append(f"assignments: invalid status '{a.status}'")
    for s in dump.scores:
        ref("user", s.judge_id, users, "scores")
        ref("submission", s.submission_id, subs, "scores")
        c = crit.get(s.criterion_id)
        if c is None:
            p.append(f"scores: unknown criterion '{s.criterion_id}'")
        elif not (c.scale_min <= s.raw_value <= c.scale_max):
            p.append(f"scores: {s.raw_value} is outside {c.name}'s scale {c.scale_min:g}-{c.scale_max:g}")
    for v in dump.votes:
        ref("submission", v.submission_id, subs, "votes")
        if v.weight < 0:
            p.append("votes: negative weight")
    for c in dump.comments:
        ref("submission", c.submission_id, subs, "comments")
        ref("user", c.author_id, users, "comments")
    for a in dump.audit:
        ref("user", a.actor_id, users, "audit")
    if dump.event.status not in {s.value for s in EventStatus}:
        p.append(f"event: invalid status '{dump.event.status}'")
    for name in ("start_date", "end_date", "submission_deadline", "judging_opens_at", "judging_closes_at",
                 "voting_opens_at", "voting_closes_at", "team_formation_start", "team_formation_end"):
        try:
            _dt(getattr(dump.event, name))
        except ValueError:
            p.append(f"event.{name}: not an ISO 8601 timestamp")
    return p[:50]


# ------------------------------------------------------------------ import

class _Tally:
    def __init__(self):
        self.created = {s: 0 for s in SECTIONS}
        self.updated = {s: 0 for s in SECTIONS}

    def out(self):
        imported = {s: self.created[s] + self.updated[s] for s in SECTIONS}
        return imported, dict(self.created), dict(self.updated)


async def import_dump(
    db: AsyncSession, target_event_id: str, dump: EventDump, actor_id: str, dry_run: bool = False, actor_is_admin: bool = False
) -> dict:
    """Apply a dump to an existing event. See module docstring for the guarantees."""
    problems = validate_dump(dump)
    verified = False
    if dump.checksum:
        if dump.checksum != checksum_of(dump):
            problems.append("checksum mismatch: the dump was modified or truncated after export")
        else:
            verified = True
    if problems:
        raise DumpError(422, problems)

    eid = str(target_event_id)
    # a dry run does the real work inside a SAVEPOINT that is always rolled back, so it can undo nothing but itself
    savepoint = await db.begin_nested() if dry_run else None
    tally = _Tally()
    warnings: list[str] = []
    conflicts: list[str] = []
    event = (await db.execute(select(Event).where(Event.id == eid))).scalar_one()
    same_event = dump.event.id == eid

    # --- users: match by email; new accounts get a hash nobody knows (one bcrypt for all)
    by_email = {
        u.email.lower(): u
        for u in (await db.execute(select(User).where(User.email.in_([x.email.strip().lower() for x in dump.users] or [""])))).scalars().all()
    }
    unusable = None
    uid: dict[str, str] = {}
    taken_user_ids = {r for (r,) in (await db.execute(select(User.id).where(User.id.in_([u.id for u in dump.users] or [""])))).all()}
    for u in dump.users:
        email = u.email.strip().lower()
        if email in by_email:
            uid[u.id] = by_email[email].id
            continue
        unusable = unusable or get_password_hash(secrets.token_urlsafe(32))
        new_id = u.id if u.id not in taken_user_ids else str(uuid.uuid4())
        db.add(User(id=new_id, email=email, name=u.name, password_hash=unusable))
        uid[u.id] = new_id
        tally.created["users"] += 1
    if tally.created["users"]:
        warnings.append(f"{tally.created['users']} user account(s) created without a usable password (they must be given access another way)")
    tally.updated["users"] = len(dump.users) - tally.created["users"]
    await db.flush()

    # --- event settings (never id / slug / organizer / created_at)
    ev = dump.event
    event.name, event.description = ev.name, ev.description
    event.status = EventStatus(ev.status)
    for name in ("start_date", "end_date", "submission_deadline", "judging_opens_at", "judging_closes_at",
                 "voting_opens_at", "voting_closes_at", "team_formation_start", "team_formation_end"):
        setattr(event, name, _dt(getattr(ev, name)))
    event.voting_mode, event.votes_per_voter, event.vote_credits = ev.voting_mode, ev.votes_per_voter, ev.vote_credits

    async def owner_check(model, ids: list[str], label: str):
        """An id that already exists under a different event must not be overwritten."""
        if not ids:
            return {}
        found = {r.id: r for r in (await db.execute(select(model).where(model.id.in_(ids)))).scalars().all()}
        for i, row in found.items():
            if getattr(row, "event_id", eid) != eid:
                conflicts.append(f"{label} {i} already exists in a different event")
        return found

    # --- tracks
    tracks = await owner_check(Track, [t.id for t in dump.tracks], "track")
    for t in dump.tracks:
        row = tracks.get(t.id)
        if row is None:
            db.add(Track(id=t.id, event_id=eid, name=t.name, description=t.description)); tally.created["tracks"] += 1
        else:
            row.name, row.description = t.name, t.description; tally.updated["tracks"] += 1
    # --- criteria
    crits = await owner_check(RubricCriterion, [c.id for c in dump.criteria], "criterion")
    for c in dump.criteria:
        row = crits.get(c.id)
        vals = dict(name=c.name, description=c.description, weight=c.weight, scale_min=c.scale_min,
                    scale_max=c.scale_max, track_id=c.track_id)
        if row is None:
            db.add(RubricCriterion(id=c.id, event_id=eid, **vals)); tally.created["criteria"] += 1
        else:
            for k, v in vals.items():
                setattr(row, k, v)
            tally.updated["criteria"] += 1
    # --- teams (+ memberships)
    teams = await owner_check(Team, [t.id for t in dump.teams], "team")
    for t in dump.teams:
        row = teams.get(t.id)
        if row is None:
            db.add(Team(id=t.id, event_id=eid, name=t.name, invite_code=t.invite_code, created_at=_dt(t.created_at) or datetime.now(timezone.utc)))
            tally.created["teams"] += 1
        else:
            row.name = t.name; tally.updated["teams"] += 1
    await db.flush()
    have_members = {(m.team_id, m.user_id) for m in (await db.execute(
        select(TeamMembership).where(TeamMembership.team_id.in_([t.id for t in dump.teams] or [""])))).scalars().all()}
    # a user can be in one team per event: never let a dump violate the rule the API enforces
    for t in dump.teams:
        for m in t.members:
            key = (t.id, uid[m.user_id])
            if key in have_members:
                tally.updated["memberships"] += 1
                continue
            db.add(TeamMembership(team_id=t.id, user_id=uid[m.user_id], role_in_team=TeamRoleType(m.role_in_team)))
            have_members.add(key); tally.created["memberships"] += 1
    # --- roles
    have_roles = {(r.user_id, r.role) for r in (await db.execute(select(EventRole).where(EventRole.event_id == eid))).scalars().all()}
    skipped_admin = 0
    for r in dump.roles:
        key = (uid[r.user_id], EventRoleType(r.role))
        if key[1] == EventRoleType.ADMIN and not actor_is_admin and key not in have_roles:
            skipped_admin += 1  # the admin role is accepted everywhere: an import must not be a way to mint admins
            continue
        if key in have_roles:
            tally.updated["roles"] += 1
            continue
        db.add(EventRole(user_id=key[0], event_id=eid, role=key[1])); have_roles.add(key); tally.created["roles"] += 1
    if skipped_admin:
        warnings.append(f"{skipped_admin} admin role(s) were not restored: only an admin can grant the admin role")
    # --- submissions
    subs = await owner_check(Submission, [s.id for s in dump.submissions], "submission")
    for s in dump.submissions:
        vals = dict(team_id=s.team_id, track_id=s.track_id, name=s.name, tagline=s.tagline, description_md=s.description_md,
                    thumbnail_url=s.thumbnail_url, gallery_image_urls=s.gallery_image_urls, demo_video_url=s.demo_video_url,
                    repo_url=s.repo_url, live_url=s.live_url, tech_tags=s.tech_tags, custom_answers=s.custom_answers,
                    status=SubmissionStatus(s.status), submitted_at=_dt(s.submitted_at), last_edited_at=_dt(s.last_edited_at))
        row = subs.get(s.id)
        if row is None:
            db.add(Submission(id=s.id, event_id=eid, created_at=_dt(s.created_at) or datetime.now(timezone.utc), **vals))
            tally.created["submissions"] += 1
        else:
            for k, v in vals.items():
                setattr(row, k, v)
            tally.updated["submissions"] += 1
    if conflicts:
        raise DumpError(409, conflicts[:20])
    await db.flush()

    sub_ids = [s.id for s in dump.submissions]
    # --- assignments (natural key: judge + submission)
    have_a = {(a.judge_id, a.submission_id): a for a in (await db.execute(
        select(JudgeAssignment).where(JudgeAssignment.submission_id.in_(sub_ids or [""])))).scalars().all()}
    taken = {i for (i,) in (await db.execute(select(JudgeAssignment.id).where(JudgeAssignment.id.in_([a.id for a in dump.assignments] or [""])))).all()}
    for a in dump.assignments:
        key = (uid[a.judge_id], a.submission_id)
        row = have_a.get(key)
        if row is None:
            db.add(JudgeAssignment(id=a.id if a.id not in taken else str(uuid.uuid4()), judge_id=key[0], submission_id=key[1],
                                   batch_id=a.batch_id, status=AssignmentStatus(a.status),
                                   assigned_at=_dt(a.assigned_at) or datetime.now(timezone.utc)))
            tally.created["assignments"] += 1
        else:
            row.status = AssignmentStatus(a.status); tally.updated["assignments"] += 1
    # --- scores (natural key: judge + submission + criterion)
    have_s = {(s.judge_id, s.submission_id, s.criterion_id): s for s in (await db.execute(
        select(Score).where(Score.submission_id.in_(sub_ids or [""])))).scalars().all()}
    taken = {i for (i,) in (await db.execute(select(Score.id).where(Score.id.in_([s.id for s in dump.scores] or [""])))).all()}
    overwrites: list[tuple[Score, float]] = []
    for s in dump.scores:
        key = (uid[s.judge_id], s.submission_id, s.criterion_id)
        row = have_s.get(key)
        if row is None:
            db.add(Score(id=s.id if s.id not in taken else str(uuid.uuid4()), judge_id=key[0], submission_id=key[1],
                         criterion_id=key[2], raw_value=s.raw_value, comment=s.comment,
                         created_at=_dt(s.created_at) or datetime.now(timezone.utc),
                         updated_at=_dt(s.updated_at) or datetime.now(timezone.utc)))
            tally.created["scores"] += 1
        else:
            if row.raw_value != s.raw_value:
                overwrites.append((row, row.raw_value))
            row.raw_value, row.comment = s.raw_value, s.comment
            tally.updated["scores"] += 1
    # --- votes (natural key: submission + fingerprint)
    have_v = {(v.submission_id, v.voter_fingerprint): v for v in (await db.execute(
        select(Vote).where(Vote.submission_id.in_(sub_ids or [""])))).scalars().all()}
    taken = {i for (i,) in (await db.execute(select(Vote.id).where(Vote.id.in_([v.id for v in dump.votes] or [""])))).all()}
    for v in dump.votes:
        row = have_v.get((v.submission_id, v.voter_fingerprint))
        if row is None:
            db.add(Vote(id=v.id if v.id not in taken else str(uuid.uuid4()), submission_id=v.submission_id, event_id=eid,
                        voter_fingerprint=v.voter_fingerprint, ip_hash=v.ip_hash, weight=v.weight,
                        created_at=_dt(v.created_at) or datetime.now(timezone.utc)))
            tally.created["votes"] += 1
        else:
            row.weight = v.weight; tally.updated["votes"] += 1
    # --- comments (by id)
    have_c = {c.id: c for c in (await db.execute(select(Comment).where(Comment.id.in_([c.id for c in dump.comments] or [""])))).scalars().all()}
    for c in dump.comments:
        row = have_c.get(c.id)
        if row is None:
            db.add(Comment(id=c.id, submission_id=c.submission_id, author_id=uid.get(c.author_id) if c.author_id else None,
                           body=c.body, created_at=_dt(c.created_at) or datetime.now(timezone.utc)))
            tally.created["comments"] += 1
        elif row.submission_id != c.submission_id:
            conflicts.append(f"comment {c.id} already exists on a different submission")
        else:
            tally.updated["comments"] += 1
    # --- audit history: only back into the event it came from; append-only and tagged as imported
    if dump.audit and not same_event:
        warnings.append("audit history was not imported: the dump comes from a different event")
    elif dump.audit:
        have_au = {i for (i,) in (await db.execute(select(AuditLog.id).where(AuditLog.id.in_([a.id for a in dump.audit] or [""])))).all()}
        for a in dump.audit:
            if a.id in have_au:
                tally.updated["audit"] += 1
                continue
            db.add(AuditLog(id=a.id, actor_id=uid.get(a.actor_id) if a.actor_id else None, event_id=eid, action=a.action,
                            target_type=a.target_type, target_id=a.target_id,
                            extra_data={**a.extra_data, "imported": True, "imported_by": str(actor_id)},
                            created_at=_dt(a.created_at) or datetime.now(timezone.utc)))
            tally.created["audit"] += 1
    if conflicts:
        raise DumpError(409, conflicts[:20])
    await db.flush()

    imported, created, updated = tally.out()
    if savepoint is not None:
        await savepoint.rollback()
    else:
        for row, old in overwrites:
            await create_audit_log(db, "score.update", "score", row.id, actor_id=actor_id, event_id=eid,
                                   extra_data={"role": "organizer", "old": old, "new": row.raw_value, "via": "import",
                                               "detail": f"import overwrote {old} -> {row.raw_value}"})
        await create_audit_log(
            db, "event.import", "event", eid, actor_id=actor_id, event_id=eid,
            extra_data={"role": "organizer", "detail": "restored from JSON dump", "source_event_id": dump.event.id,
                        "checksum": dump.checksum, "checksum_verified": verified, "imported": imported},
        )
    return {"dry_run": dry_run, "checksum_verified": verified, "imported": imported,
            "created": created, "updated": updated, "warnings": warnings}
