"""Normalization algorithm tests with synthetic proof."""

import pytest

from app.services.judging_engine import normalize_scores_z_score


def test_z_score_normalization_proof():
    """
    Synthetic proof: Two judges, one harsh, one lenient.
    Same underlying quality submissions should rank differently with raw average
    but correctly with z-score normalization.
    """
    # Judge 1: Lenient (scores everything high: 8-10)
    # Judge 2: Harsh (scores everything low: 4-6)
    # Both judges agree on relative quality: sub_A > sub_B > sub_C

    judge_scores = {
        "judge_lenient": [
            {"submission_id": "sub_A", "weighted_score": 10.0},
            {"submission_id": "sub_B", "weighted_score": 9.0},
            {"submission_id": "sub_C", "weighted_score": 8.0},
        ],
        "judge_harsh": [
            {"submission_id": "sub_A", "weighted_score": 6.0},
            {"submission_id": "sub_B", "weighted_score": 5.0},
            {"submission_id": "sub_C", "weighted_score": 4.0},
        ],
    }

    normalized = normalize_scores_z_score(judge_scores)

    # Raw averages would be:
    # sub_A: (10 + 6) / 2 = 8.0
    # sub_B: (9 + 5) / 2 = 7.0
    # sub_C: (8 + 4) / 2 = 6.0

    # Z-score normalization should preserve ranking but center around 0
    assert normalized["sub_A"] > normalized["sub_B"]
    assert normalized["sub_B"] > normalized["sub_C"]

    # The lenient judge's scores should be normalized down
    # The harsh judge's scores should be normalized up
    # This proves the normalization is working correctly


def test_zero_variance_fallback():
    """A judge who scores everything identically has no spread: flag them and keep
    their score on the same scale as the other judges' z-scores."""
    from app.services.judging_engine import normalize_with_meta

    judge_scores = {
        "judge_consistent": [
            {"submission_id": "sub_A", "weighted_score": 7.0},
            {"submission_id": "sub_B", "weighted_score": 7.0},
            {"submission_id": "sub_C", "weighted_score": 7.0},
        ],
    }

    normalized, meta = normalize_with_meta(judge_scores)

    # only judge, pooled sd is 0 too -> contributes 0.0 for everything
    assert normalized["sub_A"] == normalized["sub_B"] == normalized["sub_C"] == 0.0
    assert meta["zero_variance_judges"] == ["judge_consistent"]


def test_zero_variance_judge_does_not_swamp_z_scores():
    """Regression: raw fallback (~3.0) averaged with z-scores (~0) made every
    project the flat judge reviewed jump the rankings."""
    from app.services.judging_engine import normalize_with_meta

    judge_scores = {
        "spread": [
            {"submission_id": "A", "weighted_score": 5.0},
            {"submission_id": "B", "weighted_score": 3.0},
            {"submission_id": "C", "weighted_score": 1.0},
        ],
        "flat": [
            {"submission_id": "A", "weighted_score": 3.0},
            {"submission_id": "B", "weighted_score": 3.0},
            {"submission_id": "C", "weighted_score": 3.0},
        ],
    }
    normalized, meta = normalize_with_meta(judge_scores)

    assert meta["zero_variance_judges"] == ["flat"]
    assert normalized["A"] > normalized["B"] > normalized["C"]
    # everything stays on a z-like scale, nowhere near raw points
    assert all(abs(v) < 2.5 for v in normalized.values())


def test_single_judge():
    """Single judge should just use raw scores normalized."""
    judge_scores = {
        "judge1": [
            {"submission_id": "sub_A", "weighted_score": 9.0},
            {"submission_id": "sub_B", "weighted_score": 7.0},
        ],
    }

    normalized = normalize_scores_z_score(judge_scores)

    # With single judge, z-scores should center around 0
    assert abs(normalized["sub_A"] + normalized["sub_B"]) < 0.001


def test_empty_scores():
    """Empty scores should return empty dict."""
    assert normalize_scores_z_score({}) == {}
    assert normalize_scores_z_score({"judge1": []}) == {}


def test_normalization_changes_the_ranking_vs_raw_average():
    """The numbers quoted in JUDGING.md ("Proof where the rankings differ").

    Harsh judge H reviews A, C, D; lenient judge L reviews B, C, E. A is H's best
    project, B is L's worst, yet the raw average ranks B (8.0) above A (6.0).
    """
    from app.services.judging_engine import normalize_with_meta

    judge_scores = {
        "H": [
            {"submission_id": "A", "weighted_score": 6.0},
            {"submission_id": "C", "weighted_score": 5.0},
            {"submission_id": "D", "weighted_score": 2.0},
        ],
        "L": [
            {"submission_id": "B", "weighted_score": 8.0},
            {"submission_id": "C", "weighted_score": 10.0},
            {"submission_id": "E", "weighted_score": 9.0},
        ],
    }
    raw = {"A": 6.0, "B": 8.0, "C": 7.5, "D": 2.0, "E": 9.0}
    normalized, meta = normalize_with_meta(judge_scores)

    raw_order = sorted(raw, key=lambda s: -raw[s])
    norm_order = sorted(normalized, key=lambda s: -normalized[s])
    assert raw_order == ["E", "B", "C", "A", "D"]
    assert norm_order == ["A", "C", "E", "B", "D"]
    assert normalized["A"] == pytest.approx(0.800, abs=1e-3)
    assert normalized["B"] == pytest.approx(-1.000, abs=1e-3)
    assert normalized["C"] == pytest.approx(0.660, abs=1e-3)
    assert normalized["D"] == pytest.approx(-1.121, abs=1e-3)
    assert normalized["E"] == pytest.approx(0.000, abs=1e-3)
    assert meta["zero_variance_judges"] == []
