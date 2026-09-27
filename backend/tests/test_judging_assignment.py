"""Judging assignment algorithm tests."""

import pytest

from app.services.judging_engine import assign_reviewers


def test_basic_assignment():
    submissions = [
        {"id": "sub1", "team_id": "team1"},
        {"id": "sub2", "team_id": "team2"},
        {"id": "sub3", "team_id": "team3"},
    ]
    judges = [
        {"id": "judge1"},
        {"id": "judge2"},
    ]

    assignments = assign_reviewers(submissions, judges, reviews_per_submission=2)

    # Each submission should have exactly 2 judges
    sub_counts = {}
    for a in assignments:
        sub_id = a["submission_id"]
        sub_counts[sub_id] = sub_counts.get(sub_id, 0) + 1

    for sub_id in ["sub1", "sub2", "sub3"]:
        assert sub_counts.get(sub_id) == 2


def test_no_self_assignment():
    submissions = [
        {"id": "sub1", "team_id": "team1"},  # judge1 is a member of team1
        {"id": "sub2", "team_id": "team2"},
    ]
    judges = [
        {"id": "judge1", "team_ids": {"team1"}},
        {"id": "judge2"},
    ]

    assignments = assign_reviewers(submissions, judges, reviews_per_submission=2)

    # Judge1 must not review their own team's submission
    assert {"judge_id": "judge1", "submission_id": "sub1"} not in assignments
    # ... and sub1 is capped at the one eligible judge rather than repeating anyone
    assert [a for a in assignments if a["submission_id"] == "sub1"] == [
        {"judge_id": "judge2", "submission_id": "sub1"}
    ]


def test_balanced_distribution():
    submissions = [{"id": f"sub{i}", "team_id": f"team{i}"} for i in range(10)]
    judges = [{"id": f"judge{i}"} for i in range(3)]

    assignments = assign_reviewers(submissions, judges, reviews_per_submission=3)

    # Count assignments per judge
    judge_counts = {}
    for a in assignments:
        judge_id = a["judge_id"]
        judge_counts[judge_id] = judge_counts.get(judge_id, 0) + 1

    # Each judge should have roughly equal assignments
    counts = list(judge_counts.values())
    assert max(counts) - min(counts) <= 1


def test_exact_reviews_per_submission():
    submissions = [{"id": f"sub{i}", "team_id": f"team{i}"} for i in range(5)]
    judges = [{"id": f"judge{i}"} for i in range(3)]

    for r in [1, 2, 3]:
        assignments = assign_reviewers(submissions, judges, reviews_per_submission=r)
        sub_counts = {}
        for a in assignments:
            sub_id = a["submission_id"]
            sub_counts[sub_id] = sub_counts.get(sub_id, 0) + 1

        for sub_id in [f"sub{i}" for i in range(5)]:
            assert sub_counts.get(sub_id) == r

    # R larger than the judge pool is capped; a judge is never repeated on a submission
    assignments = assign_reviewers(submissions, judges, reviews_per_submission=4)
    pairs = [(a["judge_id"], a["submission_id"]) for a in assignments]
    assert len(pairs) == len(set(pairs)) == 5 * 3


def test_empty_inputs():
    assert assign_reviewers([], [{"id": "judge1"}]) == []
    assert assign_reviewers([{"id": "sub1", "team_id": "t1"}], []) == []


def test_balanced_with_uneven_totals():
    submissions = [{"id": f"sub{i}", "team_id": f"team{i}"} for i in range(7)]
    judges = [{"id": f"judge{i}"} for i in range(4)]
    assignments = assign_reviewers(submissions, judges, reviews_per_submission=2)
    counts = {}
    for a in assignments:
        counts[a["judge_id"]] = counts.get(a["judge_id"], 0) + 1
    assert sum(counts.values()) == 14
    assert max(counts.values()) - min(counts.values()) <= 1
