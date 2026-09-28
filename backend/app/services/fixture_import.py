"""Import a DOGFOOD ``fixtures.json`` into the normal schema.

The shape is fixed by the spec (event, tracks, judges, teams, projects, scores).
Mapping and tolerance rules are documented in DATA-MODEL.md; the short version:

* every fixture id becomes a deterministic UUID (``stable_ids.stable_id``);
* ``scores[].criteria`` is a free-form dict, so a ``RubricCriterion`` is created the
  first time a criterion name is seen (weight 1.0, scale 0-5, widened if a value
  exceeds 5);
* review counts may be uneven - nothing assumes a fixed reviews-per-project;
* duplicate projects are last-write-wins (same id, or same team + same title);
* the import is idempotent: if the fixture event already exists it is skipped.
"""

import hashlib
import json
import math
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import Event, EventRole, EventRoleType, EventStatus, Track
from app.models.judging import AssignmentStatus, JudgeAssignment, RubricCriterion, Score
from app.models.submission import Submission, SubmissionStatus
from app.models.team import Team, TeamMembership, TeamRoleType
from app.models.user import User
from app.services.stable_ids import stable_id, user_id_for_email
from app.utils.security import get_password_hash

ORGANIZER_EMAIL = "organizer@dogfoodhack.com"
PROBE_PARTICIPANT_EMAIL = "participant1@dogfoodhack.com"
FALLBACK_JUDGE_EMAILS = ("judge1@dogfoodhack.com", "judge2@dogfoodhack.com")
DEFAULT_SCALE_MAX = 5.0


def load_fixtures(path: str) -> Optional[dict]:
    """Read fixtures.json, or return None if the file is not there."""
    if not path or not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return json.load(f)


def parse_ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "event"


def _norm_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().lower())


def _judge_email(j: dict) -> str:
    return (j.get("email") or f"{j['id']}@fixtures.invalid").strip().lower()


def resolve_projects(data: dict) -> tuple[dict[str, dict], dict[str, str]]:
    """Collapse duplicate projects. Returns (projects by canonical id, alias -> canonical id).

    Last write wins, both for a repeated id and for a repeated (team, title) under a
    new id. The first-seen id stays canonical so routes/ids do not move.
    """
    projects: dict[str, dict] = {}
    canon: dict[str, str] = {}
    by_team_title: dict[tuple, str] = {}
    for p in data.get("projects", []):
        pid = str(p["id"])
        key = (str(p.get("team")), _norm_title(p.get("title", "")))
        if pid in canon:
            target = canon[pid]
        elif key in by_team_title:
            target = by_team_title[key]
        else:
            target = pid
        canon[pid] = target
        by_team_title[key] = target
        projects[target] = {**p, "id": target}
    return projects, canon


def checker_plan(data: dict) -> dict[str, Any]:
    """Pure function of the fixtures: which users / routes the checker should use.

    judge_a / judge_b are the first two fixture judges (so judge_a really has
    scores); if the file has fewer than two, the seeded judge1/judge2 stand in.
    ``participant`` is always a dedicated user that holds no judge role.
    """
    judges = data.get("judges", [])
    judge_emails = [_judge_email(j) for j in judges]
    for fb in FALLBACK_JUDGE_EMAILS:
        if len(judge_emails) < 2 and fb not in judge_emails:
            judge_emails.append(fb)
    judge_a, judge_b = judge_emails[0], judge_emails[1]

    projects, canon = resolve_projects(data)
    judge_a_id = next((j["id"] for j in judges if _judge_email(j) == judge_a), None)
    scored = [
        canon.get(str(s["project"]), str(s["project"]))
        for s in data.get("scores", [])
        if s.get("judge") == judge_a_id
    ]
    first_project = next((p for p in scored if p in projects), None) or next(iter(projects), None)

    event_id = stable_id("event", str(data["event"]["id"]))
    return {
        "event_id": event_id,
        "judge_a_email": judge_a,
        "judge_b_email": judge_b,
        "organizer_email": ORGANIZER_EMAIL,
        "participant_email": PROBE_PARTICIPANT_EMAIL,
        "probe_team_id": stable_id("probe-team", str(data["event"]["id"])),
        "project_id": stable_id("project", first_project) if first_project else None,
    }


async def _get_or_create_user(
    db: AsyncSession, email: str, name: str, password: str, cache: dict[str, User]
) -> User:
    email = email.strip().lower()
    if email in cache:
        return cache[email]
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        user = User(
            id=user_id_for_email(email),
            email=email,
            name=name,
            password_hash=get_password_hash(password),
        )
        db.add(user)
        await db.flush()
    cache[email] = user
    return user


async def _ensure_role(db: AsyncSession, user_id: str, event_id: str, role: EventRoleType, seen: set):
    key = (user_id, event_id, role)
    if key in seen:
        return
    seen.add(key)
    exists = await db.execute(
        select(EventRole).where(
            EventRole.user_id == user_id,
            EventRole.event_id == event_id,
            EventRole.role == role,
        )
    )
    if not exists.first():
        db.add(EventRole(user_id=user_id, event_id=event_id, role=role))


async def import_fixtures(db: AsyncSession, data: dict) -> Optional[dict]:
    """Load fixtures into the DB. Returns a summary, or None if already imported."""
    ev = data["event"]
    event_id = stable_id("event", str(ev["id"]))
    existing = await db.execute(select(Event).where(Event.id == event_id))
    if existing.scalar_one_or_none():
        return None

    users: dict[str, User] = {}
    seen_roles: set = set()
    notes: list[str] = []

    organizer = await _get_or_create_user(
        db, ORGANIZER_EMAIL, "Event Organizer", "organizer123", users
    )

    close = parse_ts(ev.get("submissions_close")) or datetime.now(timezone.utc)
    db.add(
        Event(
            id=event_id,
            organizer_id=organizer.id,
            name=ev.get("name", ev["id"]),
            slug=f"{_slug(ev.get('name', ev['id']))}-{event_id[:8]}",
            description=f"Imported from fixtures ({ev['id']}).",
            start_date=close - timedelta(days=7),
            end_date=close + timedelta(days=14),
            submission_deadline=close,
            judging_opens_at=close,
            judging_closes_at=close + timedelta(days=7),
            voting_opens_at=close + timedelta(days=7),
            voting_closes_at=close + timedelta(days=14),
            # Submissions are closed, so the event sits in the judging phase.
            status=EventStatus.JUDGING,
        )
    )
    await db.flush()
    await _ensure_role(db, organizer.id, event_id, EventRoleType.ORGANIZER, seen_roles)

    # tracks
    track_ids: dict[str, str] = {}
    for t in data.get("tracks", []):
        tid = stable_id("track", str(t["id"]))
        db.add(Track(id=tid, event_id=event_id, name=t["name"], description=t.get("description")))
        track_ids[str(t["id"])] = tid

    # judges (judge.tracks has no counterpart in the schema and is not stored)
    judge_user: dict[str, str] = {}
    for j in data.get("judges", []):
        u = await _get_or_create_user(db, _judge_email(j), j.get("name", j["id"]), "judge123", users)
        judge_user[str(j["id"])] = u.id
        await _ensure_role(db, u.id, event_id, EventRoleType.JUDGE, seen_roles)

    # teams
    team_ids: dict[str, str] = {}
    for tm in data.get("teams", []):
        tid = stable_id("team", str(tm["id"]))
        team_ids[str(tm["id"])] = tid
        db.add(
            Team(
                id=tid,
                event_id=event_id,
                name=tm["name"],
                invite_code=hashlib.sha256(tid.encode()).hexdigest()[:32],
            )
        )
        await db.flush()
        for idx, email in enumerate(tm.get("members", [])):
            u = await _get_or_create_user(
                db, email, email.split("@")[0].title(), "participant123", users
            )
            await _ensure_role(db, u.id, event_id, EventRoleType.PARTICIPANT, seen_roles)
            already = await db.execute(
                select(TeamMembership).where(
                    TeamMembership.team_id == tid, TeamMembership.user_id == u.id
                )
            )
            if not already.first():
                db.add(
                    TeamMembership(
                        team_id=tid,
                        user_id=u.id,
                        role_in_team=TeamRoleType.LEADER if idx == 0 else TeamRoleType.MEMBER,
                    )
                )

    # projects (duplicates collapsed: last write wins)
    projects, canon = resolve_projects(data)
    total_rows = len(data.get("projects", []))
    if total_rows != len(projects):
        notes.append(f"{total_rows - len(projects)} duplicate project row(s) merged")
    base = datetime.now(timezone.utc).replace(microsecond=0)
    project_ids: dict[str, str] = {}
    for i, (pid, p) in enumerate(projects.items()):
        team_key = str(p.get("team"))
        if team_key not in team_ids:
            # Tolerate a project pointing at an unknown team with a placeholder team.
            tid = stable_id("team", team_key)
            db.add(
                Team(
                    id=tid,
                    event_id=event_id,
                    name=f"Team {team_key}",
                    invite_code=hashlib.sha256(tid.encode()).hexdigest()[:32],
                )
            )
            await db.flush()
            team_ids[team_key] = tid
            notes.append(f"project {pid}: unknown team {team_key}, placeholder created")
        sid = stable_id("project", pid)
        project_ids[pid] = sid
        db.add(
            Submission(
                id=sid,
                team_id=team_ids[team_key],
                event_id=event_id,
                track_id=track_ids.get(str(p.get("track"))),
                name=(p.get("title") or pid).strip(),
                tagline=p.get("summary"),
                repo_url=p.get("repo_url"),
                status=SubmissionStatus.SUBMITTED,
                submitted_at=parse_ts(p.get("submitted_at")),
                # explicit, strictly increasing: the gallery orders by created_at
                created_at=base + timedelta(milliseconds=i),
            )
        )
    await db.flush()

    # scores -> criteria + scores + assignments; last write wins per (judge, project, criterion)
    crit_ids: dict[str, str] = {}
    crit_max: dict[str, float] = {}
    rows: dict[tuple, dict] = {}
    pairs: set[tuple] = set()
    skipped = 0
    for s in data.get("scores", []):
        jkey = str(s["judge"])
        if jkey not in judge_user:
            email = f"{jkey}@fixtures.invalid"
            u = await _get_or_create_user(db, email, jkey, "judge123", users)
            judge_user[jkey] = u.id
            await _ensure_role(db, u.id, event_id, EventRoleType.JUDGE, seen_roles)
            notes.append(f"score references unknown judge {jkey}, placeholder created")
        pkey = canon.get(str(s["project"]), str(s["project"]))
        if pkey not in project_ids:
            skipped += 1
            continue
        pairs.add((judge_user[jkey], project_ids[pkey]))
        for cname, value in (s.get("criteria") or {}).items():
            try:
                value = float(value)
            except (TypeError, ValueError):
                skipped += 1
                continue
            if cname not in crit_ids:
                crit_ids[cname] = stable_id("criterion", f"{event_id}:{cname}")
                crit_max[cname] = DEFAULT_SCALE_MAX
            crit_max[cname] = max(crit_max[cname], math.ceil(value))
            rows[(judge_user[jkey], project_ids[pkey], crit_ids[cname])] = {
                "raw_value": value,
                "comment": s.get("comment") or None,
            }
    if skipped:
        notes.append(f"{skipped} score entr(ies) skipped (unknown project or non-numeric value)")

    for cname, cid in crit_ids.items():
        db.add(
            RubricCriterion(
                id=cid,
                event_id=event_id,
                name=cname,
                weight=1.0,
                scale_min=0.0,
                scale_max=crit_max[cname],
            )
        )
    await db.flush()

    for (jid, sid, cid), r in rows.items():
        db.add(
            Score(judge_id=jid, submission_id=sid, criterion_id=cid, **r)
        )
    for jid, sid in pairs:
        db.add(
            JudgeAssignment(
                judge_id=jid,
                submission_id=sid,
                batch_id="fixtures",
                status=AssignmentStatus.COMPLETED,
            )
        )

    # Checker identities need roles on the fixture event too.
    plan = checker_plan(data)
    for email in (plan["judge_a_email"], plan["judge_b_email"]):
        u = await _get_or_create_user(db, email, email.split("@")[0], "judge123", users)
        await _ensure_role(db, u.id, event_id, EventRoleType.JUDGE, seen_roles)

    probe = await _get_or_create_user(
        db, PROBE_PARTICIPANT_EMAIL, "Alice Participant", "participant123", users
    )
    await _ensure_role(db, probe.id, event_id, EventRoleType.PARTICIPANT, seen_roles)
    db.add(
        Team(
            id=plan["probe_team_id"],
            event_id=event_id,
            name="Checker Probe Team",
            invite_code=hashlib.sha256(plan["probe_team_id"].encode()).hexdigest()[:32],
        )
    )
    await db.flush()
    db.add(
        TeamMembership(
            team_id=plan["probe_team_id"], user_id=probe.id, role_in_team=TeamRoleType.LEADER
        )
    )

    await db.commit()
    return {
        "event_id": event_id,
        "tracks": len(track_ids),
        "judges": len(judge_user),
        "teams": len(team_ids),
        "projects": len(projects),
        "criteria": len(crit_ids),
        "scores": len(rows),
        "notes": notes,
    }
