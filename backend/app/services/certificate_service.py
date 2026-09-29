"""Certificates and signed judge participation records (T4).

Kinds
  participant  member of a team with a submitted project in the event
  judge        judge who submitted scores: a *participation record* (counts and period only, never the scores)
  winner       member of a team whose project finished in the normalized top 3 (published results only)

Rules
  * issued only once the event is closed, so winners and review counts are final;
  * issued lazily and once: the stored, signed document is returned on every later request (stable `issued_at`,
    stable verification code), so a certificate can never silently change;
  * the signed payload holds ids, names, the detail line and counts: no emails, no scores.

`build_score_attestation` (below) is a related but separate, unstored document: a judge's signed
proof of their *actual scores*, available any time (not gated on the event closing).
"""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.certificate import Certificate
from app.models.event import Event, EventRole, EventRoleType, EventStatus
from app.models.judging import RubricCriterion, Score
from app.models.submission import Submission, SubmissionStatus
from app.models.team import Team, TeamMembership
from app.models.user import User
from app.services import signing

KINDS = ("winner", "judge", "participant")  # priority when the caller does not pick one
PAYLOAD_VERSION = 1


class CertError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


async def entitlements(db: AsyncSession, event: Event, user_id: str) -> dict[str, dict]:
    """Which certificate kinds this user has earned in this event -> {kind: {"detail": str, "record": dict}}."""
    eid, uid = str(event.id), str(user_id)
    out: dict[str, dict] = {}

    mine = (
        await db.execute(
            select(Submission.id, Submission.name)
            .join(Team, Team.id == Submission.team_id)
            .join(TeamMembership, TeamMembership.team_id == Team.id)
            .where(Team.event_id == eid, TeamMembership.user_id == uid, Submission.status == SubmissionStatus.SUBMITTED)
            .order_by(Submission.created_at)
        )
    ).all()
    if mine:
        out["participant"] = {"detail": f"Built and submitted “{mine[0][1]}”", "record": {}}

    is_judge = (
        await db.execute(
            select(EventRole.id).where(EventRole.event_id == eid, EventRole.user_id == uid, EventRole.role == EventRoleType.JUDGE)
        )
    ).first()
    if is_judge:
        n_sub, n_scores, first, last = (
            await db.execute(
                select(func.count(func.distinct(Score.submission_id)), func.count(Score.id), func.min(Score.created_at), func.max(Score.created_at))
                .join(Submission, Submission.id == Score.submission_id)
                .where(Submission.event_id == eid, Score.judge_id == uid)
            )
        ).one()
        if n_scores:
            out["judge"] = {
                "detail": f"Served on the judging panel and reviewed {n_sub} project{'s' if n_sub != 1 else ''}",
                "record": {
                    "projects_reviewed": int(n_sub),
                    "criterion_scores": int(n_scores),
                    "first_review": _iso(first),
                    "last_review": _iso(last),
                },
            }

    if mine and event.status == EventStatus.CLOSED:
        from app.api.judging import _compute_results  # local import: api layer imports services

        rows = (await _compute_results(db, event.id))["rows"]
        mine_ids = {m[0] for m in mine}
        best = min((r for r in rows if r["submission_id"] in mine_ids and r["norm_rank"]), key=lambda r: r["norm_rank"], default=None)
        if best and best["norm_rank"] <= 3:
            place = {1: "1st", 2: "2nd", 3: "3rd"}[best["norm_rank"]]
            out["winner"] = {
                "detail": f"Placed {place} of {len(rows)} with “{best['name']}”",
                "record": {"place": int(best["norm_rank"]), "projects_ranked": len(rows)},
            }
    return out


async def get_or_issue(
    db: AsyncSession, event: Event, user: User, kind: Optional[str] = None
) -> tuple[Certificate, bool]:
    if event.status != EventStatus.CLOSED:
        raise CertError(403, "Certificates are issued once the event is closed")
    earned = await entitlements(db, event, user.id)
    if kind is not None and kind not in KINDS:
        raise CertError(422, f"kind must be one of {', '.join(KINDS)}")
    chosen = kind or next((k for k in KINDS if k in earned), None)
    if chosen is None or chosen not in earned:
        raise CertError(404, "No certificate for this user in this event" if kind is None else f"This user has not earned a '{kind}' certificate in this event")

    existing = (
        await db.execute(select(Certificate).where(Certificate.event_id == str(event.id), Certificate.user_id == str(user.id), Certificate.type == chosen))
    ).scalar_one_or_none()
    if existing is not None and existing.payload and existing.signature:
        return existing, False

    info = earned[chosen]
    payload = {
        "v": PAYLOAD_VERSION,
        "issuer": "DOGFOOD",
        "kind": chosen,
        "event": {"id": str(event.id), "name": event.name},
        "recipient": {"id": str(user.id), "name": user.name},
        "detail": info["detail"],
        "issued_at": _iso(datetime.now(timezone.utc)),
        **({"record": info["record"]} if info["record"] else {}),
    }
    cert = existing or Certificate(user_id=str(user.id), event_id=str(event.id), type=chosen)
    cert.payload = payload
    cert.signature = signing.sign(payload)
    cert.verification_hash = signing.payload_hash(payload)
    cert.issued_at = datetime.now(timezone.utc)
    db.add(cert)
    await db.flush()
    return cert, True


def check_record(cert: Certificate) -> bool:
    """Is the stored document intact and validly signed? (detects database tampering)"""
    return bool(
        cert.payload and cert.signature
        and signing.payload_hash(cert.payload) == cert.verification_hash
        and signing.verify(cert.payload, cert.signature)
    )


async def build_score_attestation(db: AsyncSession, event: Event, judge: User) -> dict:
    """A judge's own signed proof of exactly what they scored, right now.

    Deliberately different from the `judge` certificate above, which never includes the scores
    themselves and is only issued once the event closes: this is available the moment a judge has
    submitted anything, so they can attest "this is what I scored" *before* the window closes -
    the certificate proves participation after the fact, this proves content as of a moment in
    time. It is not stored (a judge may score again before the window closes, and a stale stored
    copy would misrepresent itself as current), so it has no short lookup code and is never
    reachable via the public `GET /verify/{code}` - only someone holding the document itself can
    verify it (`POST /verify`, `backend/scripts/verify_certificate.py`), which matters because,
    unlike a certificate, this payload carries the judge's actual per-criterion values.
    """
    rows = (
        await db.execute(
            select(Score, RubricCriterion.name, Submission.id, Submission.name)
            .join(RubricCriterion, RubricCriterion.id == Score.criterion_id)
            .join(Submission, Submission.id == Score.submission_id)
            .where(Submission.event_id == str(event.id), Score.judge_id == str(judge.id))
            .order_by(Submission.name, RubricCriterion.name)
        )
    ).all()
    if not rows:
        raise CertError(404, "You have not scored any submissions in this event yet")

    scores = [
        {
            "submission_id": sub_id,
            "submission_name": sub_name,
            "criterion_id": score.criterion_id,
            "criterion_name": crit_name,
            "value": score.raw_value,
            "comment": score.comment or "",
            "updated_at": _iso(score.updated_at),
        }
        for score, crit_name, sub_id, sub_name in rows
    ]
    now = datetime.now(timezone.utc)
    payload = {
        "v": PAYLOAD_VERSION,
        "issuer": "DOGFOOD",
        "kind": "judge_score_attestation",
        "event": {"id": str(event.id), "name": event.name},
        "recipient": {"id": str(judge.id), "name": judge.name},
        "detail": f"Signed record of {len(scores)} score{'s' if len(scores) != 1 else ''} submitted for {event.name}, as of this moment",
        "issued_at": _iso(now),
        "record": {"scores": scores},
    }
    signature = signing.sign(payload)
    return {
        "payload": payload,
        "signature": signature,
        "key_id": signing.key_id(),
        "algorithm": signing.ALGORITHM,
        "verify_hash": signing.payload_hash(payload),
    }
