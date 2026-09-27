"""Judging engine: assignment algorithm, scoring, and normalization."""

import statistics
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.judging import (
    RubricCriterion,
    JudgeAssignment,
    Score,
    NormalizedScore,
    AssignmentStatus,
)
from app.models.submission import Submission
from app.models.user import User
from app.models.event import EventRole, EventRoleType


def assign_reviewers(
    submissions: list[dict],
    judges: list[dict],
    reviews_per_submission: int = 3,
) -> list[dict]:
    """
    Balanced assignment of judges to submissions (pure, DB-free).

    Args:
        submissions: dicts with 'id' and 'team_id'
        judges: dicts with 'id' and optionally 'team_ids' (teams the judge belongs to)
        reviews_per_submission: target number of distinct judges per submission (R)

    Returns:
        List of {'judge_id', 'submission_id'}.

    Guarantees:
      * a judge is never assigned a submission from a team they belong to;
      * a judge is never assigned the same submission twice;
      * each submission gets min(R, eligible judges) reviewers - R is capped, never
        satisfied by repeating a judge;
      * greedy least-loaded choice (ties broken by judge order) keeps batch sizes
        within 1 of each other whenever there are no conflicts; with conflicts it is
        best effort, and the most constrained submissions are placed first.
    """
    if not submissions or not judges or reviews_per_submission <= 0:
        return []

    order = {j["id"]: i for i, j in enumerate(judges)}
    teams = {j["id"]: set(j.get("team_ids") or ()) for j in judges}
    load = {j["id"]: 0 for j in judges}

    def eligible(sub: dict) -> list[str]:
        return [j["id"] for j in judges if sub["team_id"] not in teams[j["id"]]]

    # most constrained first, then input order (stable)
    queue = sorted(
        enumerate(submissions), key=lambda item: (len(eligible(item[1])), item[0])
    )

    chosen_by_sub: dict[str, list[str]] = {}
    for _, sub in queue:
        pool = eligible(sub)
        pool.sort(key=lambda jid: (load[jid], order[jid]))
        picked = pool[: min(reviews_per_submission, len(pool))]
        for jid in picked:
            load[jid] += 1
        chosen_by_sub[sub["id"]] = picked

    return [
        {"judge_id": jid, "submission_id": sub["id"]}
        for sub in submissions
        for jid in chosen_by_sub[sub["id"]]
    ]


def calculate_raw_weighted_score(
    scores: list[dict],
    criteria: list[dict],
) -> float:
    """
    Calculate raw weighted score from criterion scores.

    Args:
        scores: List of dicts with 'criterion_id' and 'raw_value'
        criteria: List of dicts with 'id' and 'weight'

    Returns:
        Weighted score as float
    """
    criteria_map = {c["id"]: c["weight"] for c in criteria}

    total_weighted = 0
    total_weight = 0

    for score in scores:
        criterion_id = score["criterion_id"]
        raw_value = score["raw_value"]
        weight = criteria_map.get(criterion_id, 1.0)

        total_weighted += raw_value * weight
        total_weight += weight

    if total_weight == 0:
        return 0.0

    return total_weighted / total_weight


def normalize_with_meta(
    judge_scores: dict[str, list[dict]],
) -> tuple[dict[str, float], dict]:
    """
    Per-judge z-score normalization, plus the numbers used to get there.

    Args:
        judge_scores: Dict mapping judge_id to list of score dicts
                     Each score dict has 'submission_id' and 'weighted_score'

    Returns:
        (normalized, meta) where normalized maps submission_id to the mean z-score
        across the judges who scored it, and meta holds pooled mean/sd, per-judge
        stats and the ids of judges that hit the zero-variance fallback.

    Zero-variance fallback: a judge with sigma == 0 (identical scores everywhere, or
    a single review) has no spread to divide by. Averaging their raw score straight
    in would mix raw points with z-scores, so the raw score is instead standardised
    against the pooled mean/sd of *all* raw weighted scores. It stays a function of
    their raw score, lands on the same scale as everyone else's z-scores, and the
    judge is reported in ``meta["zero_variance_judges"]`` (audit-logged by the API).
    If the pooled sd is also 0 the judge contributes 0.0.
    """
    pooled = [
        s["weighted_score"] for scores in judge_scores.values() for s in scores
    ]
    pooled_mu = statistics.mean(pooled) if pooled else 0.0
    pooled_sd = statistics.stdev(pooled) if len(pooled) > 1 else 0.0

    per_judge: dict[str, dict] = {}
    zero_variance: list[str] = []
    submission_z: dict[str, list[float]] = {}

    for judge_id, scores in judge_scores.items():
        if not scores:
            continue

        values = [s["weighted_score"] for s in scores]
        mu = statistics.mean(values)
        sigma = statistics.stdev(values) if len(values) > 1 else 0.0
        flat = sigma < 1e-12
        per_judge[judge_id] = {"n": len(values), "mean": mu, "sd": sigma, "zero_variance": flat}
        if flat:
            zero_variance.append(judge_id)

        for score in scores:
            if not flat:
                z = (score["weighted_score"] - mu) / sigma
            elif pooled_sd > 1e-12:
                z = (score["weighted_score"] - pooled_mu) / pooled_sd
            else:
                z = 0.0
            submission_z.setdefault(score["submission_id"], []).append(z)

    normalized = {sid: statistics.mean(zs) for sid, zs in submission_z.items()}
    meta = {
        "pooled_mean": pooled_mu,
        "pooled_sd": pooled_sd,
        "per_judge": per_judge,
        "zero_variance_judges": zero_variance,
    }
    return normalized, meta


def normalize_scores_z_score(
    judge_scores: dict[str, list[dict]],
) -> dict[str, float]:
    """Per-judge z-score normalization (see ``normalize_with_meta``)."""
    return normalize_with_meta(judge_scores)[0]
