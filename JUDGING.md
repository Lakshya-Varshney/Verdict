# DOGFOOD Judging Engine

Assignment, scoring and normalization for hackathon submissions, plus the public-voting rules that sit next to
them. Code: `backend/app/services/judging_engine.py` (pure functions) and `backend/app/api/judging.py`
(`_compute_results` feeds `/judging/results`, `/judging/export.csv` and `/judging/normalize`,
so all three always agree). Voting: `backend/app/services/voting_service.py`.

Contents: [Assignment](#assignment-assign_reviewers) · [Scoring](#scoring) · [Normalization](#normalization-per-judge-z-score) ·
[Proof on the official data](#proof-on-the-official-fixturesjson) · [Integrity controls](#integrity-controls) ·
[Public voting](#public-voting-approval-and-quadratic) · [Not implemented](#not-implemented)

## Assignment (`assign_reviewers`)

Pure function: `assign_reviewers(submissions, judges, reviews_per_submission)`.
Submissions are `{id, team_id}`; judges are `{id, team_ids}` where `team_ids` are the teams
the judge belongs to in that event (the API fills this from `team_memberships`).

Greedy, least-loaded:

1. Order submissions most-constrained first (fewest eligible judges), then input order.
2. A judge is *eligible* for a submission unless they belong to its team.
3. For each submission take the `min(R, eligible)` least-loaded eligible judges
   (ties broken by judge order) and add one to each one's load.

Guarantees (each covered by `tests/test_judging_assignment.py`):

- a judge is never assigned their own team's submission;
- a judge is never assigned the same submission twice;
- every submission gets exactly `R` reviewers **when at least `R` judges are eligible**;
  otherwise it gets every eligible judge - `R` is capped, never met by repeating a judge;
- with no conflicts, batch sizes differ by at most 1. With conflicts it is best effort
  (the constrained submissions go first so they are not starved).

Complexity: O(S·J log J) time, O(S·R) space.

## Scoring

A judge's score for one submission is the weighted mean over the criteria **that judge
actually scored**:

```
raw_weighted_score(j, s) = Σ(value_i × weight_i) / Σ(weight_i)      i ∈ criteria j scored for s
```

Partial reviews therefore count (a judge who skipped a criterion is not dropped), and the
rubric does not have to be the same size for every judge.

**Validation (server-side).** `POST /submissions/{id}/scores` accepts a value only if the criterion belongs to the
submission's event and the value lies inside that criterion's `scale_min..scale_max` (else `400`); only an *assigned*
judge may score (`403` otherwise). A re-submitted score is an upsert, and every write, create or overwrite, is audit-logged
with the old and the new value (`score.create` / `score.update`), so scores can be changed but never silently. Example: weights 1.0 and 1.5,
scores 8 and 6 → (8·1.0 + 6·1.5) / 2.5 = 6.8.

Imported fixtures (see `DATA-MODEL.md`) carry a free-form `criteria` dict; each new name
becomes a `RubricCriterion` with weight 1.0 and scale 0-5 (widened if a value exceeds 5).

## Normalization: per-judge z-score

Judges differ in leniency and spread. For each judge `j` with scores `x` over their reviewed
submissions:

```
μ_j = mean(x)        σ_j = sample stddev(x)
z(j, s) = (x(j, s) − μ_j) / σ_j
normalized(s) = mean of z(j, s) over the judges who reviewed s
```

`NormalizedScore.method = "per_judge_z_score"`. Judges may review different numbers of
submissions and submissions may have different numbers of reviews (2 vs 5 is fine);
each submission's value is simply the mean over whoever reviewed it.

### Zero-variance judges

If `σ_j = 0` - identical scores everywhere, or a single review - there is no spread to
divide by. The judge is **flagged** (`zero_variance_judges` in the results payload, and one
`normalization.zero_variance_judge` audit-log row per judge each time `/judging/normalize`
runs) and their raw score is standardised against the **pooled** mean and stddev of every
raw weighted score in the event:

```
z(j, s) = (x(j, s) − μ_pool) / σ_pool          (0.0 if σ_pool is also 0)
```

Why not "just use the raw score"? Averaging raw points (≈3.0) with z-scores (≈0) mixes two
scales: every project a flat judge reviewed would jump the rankings by roughly their raw
score. Pooled standardisation keeps the fallback a function of the judge's raw score, on the
same scale as everyone else. Regression test:
`test_zero_variance_judge_does_not_swamp_z_scores`.

The results payload separates the two causes so the UI never mislabels them: `zero_variance_judges` lists every judge
that took the fallback, `single_review_judges` (and `single_review: true` per judge) marks those with only one review,
i.e. no spread *could* be measured. A judge in the first list but not the second genuinely scored everything the same.
On the official data that is one judge with 4/4/4 everywhere (Iva Petrova), a second whose three per-project scores are
identical after the duplicate-project merge (see `DATA-MODEL.md`), and two judges with a single review each.

### Results payload

`/judging/results` rows carry `raw_mean`, `norm_z` (the mean z-score, what ranking uses) and
`norm_mean` (= `μ_pool + norm_z · σ_pool`, the same ordering re-expressed in raw points so it
is comparable to `raw_mean`), plus `judge_count`, `raw_rank` and `norm_rank`.

## Proof where the rankings differ

Harsh judge **H** reviews A, C, D. Lenient judge **L** reviews B, C, E. A is H's best project;
B is L's *worst*.

| Judge | Scores | μ | σ | z-scores |
|-------|--------|---|---|----------|
| H | A=6, C=5, D=2 | 4.333 | 2.082 | A=+0.800, C=+0.320, D=−1.121 |
| L | B=8, C=10, E=9 | 9.000 | 1.000 | B=−1.000, C=+1.000, E=0.000 |

| Submission | Raw average | Raw rank | Normalized (mean z) | Normalized rank |
|------------|-------------|----------|---------------------|-----------------|
| A | 6.0 | 4 | **+0.800** | **1** |
| B | 8.0 | 2 | −1.000 | 4 |
| C | 7.5 | 3 | +0.660 | 2 |
| D | 2.0 | 5 | −1.121 | 5 |
| E | 9.0 | 1 | 0.000 | 3 |

Raw order `E, B, C, A, D`; normalized order `A, C, E, B, D`. The raw average puts B (the
lenient judge's lowest mark) two places above A (the harsh judge's highest mark) purely
because of who happened to review them; normalization removes that. Asserted with these exact
numbers in `test_normalization_changes_the_ranking_vs_raw_average`.

(A second, simpler case - one lenient judge 8-10, one harsh judge 4-6, agreeing on order -
shows normalization preserving a ranking that both judges agree on: `test_z_score_normalization_proof`.)

## Proof on the official `fixtures.json`

The worked example above is synthetic. This is the same engine on the official 40-project, 30-judge data set
(126 review rows, 2-6 reviews per project, judges with 1 to 11 reviews). Numbers from `GET /events/{id}/judging/results`,
independently recomputed with plain `statistics` (no application code) and equal to floating-point precision
(`backend/tests/test_real_fixtures.py`):

| | |
|--|--|
| Projects whose rank changes when normalizing | **38 of 40** |
| Rank correlation, raw vs normalized (Spearman ρ) | 0.864 |
| Judges' own means (judges with ≥ 5 reviews) | from **3.11** (Otto Brandt, σ 0.81) to **4.22** (Wei Lindqvist, σ 0.81), a full point of pure leniency |
| Top 5 by raw average | Salt Ledger, Iron Switch, Still Beacon, Dry Relay, Salt Loom |
| Top 5 normalized | Iron Switch, Slow Trail, Salt Ledger, Salt Loom, Dry Relay |

Two projects with the **identical raw average (3.44, three reviews each)** end up 23 places apart, because a raw average ignores *who* gave the scores:

| | Raw mean (rank) | Its three reviewers' own average score | This project's score vs. their own averages | Normalized rank |
|--|--|--|--|--|
| Flat Meadow | 3.44 (#24) | **3.97** (a generous panel: 4.22, 3.61, 4.08) | **−0.53** (each reviewer rated it below their usual) | **#37** (−13) |
| Glass Signal | 3.44 (#26) | 3.48 (near the pooled mean, 3.57) | −0.04 (on par with what each reviewer usually gives) | **#14** (+12) |

A 3.44 from judges who average 3.97 is a below-par verdict; the same 3.44 from judges who average 3.48 is a normal one. The raw
average cannot tell them apart; the per-judge z-score can. (Other large movers, numbers only: Deep Beacon #10 → #22,
Hollow Signal #19 → #8, North Drift #9 → #19, Dry Harbour #17 → #27.)

Sensitivity to unequal review counts is real too: 8 projects were reviewed by only 2 judges, and 7 of those 8 move. That is
why `judge_count` is exposed on every row and used in tie-breaking.

## Integrity controls

What stops judging from being manipulated, with where it is enforced and tested:

| Control | Where | Test |
|---------|-------|------|
| A judge sees **only their own** scores (`/scores/mine`); all-judges view is organizer-only; `403` for judges and participants | `deps.require_submission_role` | `test_role_isolation.py`, `test_fixture_import.py::test_peer_scores_are_isolated` |
| Roles are **scoped to the event that owns the submission**: an organizer/judge of event A has nothing on event B | same | `test_roles_are_scoped_to_the_submissions_event` |
| **No conflict of interest**: a judge is never assigned a submission from a team they belong to | `assign_reviewers` | `test_judging_assignment.py` |
| Only an **assigned** judge can score, and only inside the criterion's scale | `submit_scores` | `test_regressions.py`, `live_lifecycle.py` |
| Ranked results and CSV are **organizer-only at every stage**, including while public voting is open | `require_role` | `test_voting_abuse.py::test_results_hidden_during_voting_window` |
| **Every write** to scores, assignments, roles, votes, comments and event status writes an audit row in the same transaction; the log is append-only and readable at `GET /admin/audit` (`?format=text` for people) | `audit_service` | `test_voting_abuse.py`, `test_dump.py` |
| Normalization is **recomputed from raw scores** on demand and by export/import, never trusted from storage | `_compute_results` | `test_dump.py::test_restore_after_data_loss_reproduces_identical_results` |
| Zero-variance judges are **flagged and audit-logged**, never silently dropped or trusted at face value | `normalize_with_meta` | `test_normalization.py` |
| Deadlines are enforced in the API (`403`), not the UI | `submission_service` | `test_fixture_event_deadline_rejects_participant_submit` |

The residual risks (an organizer with database access, colluding judges, ...) are in `THREAT-MODEL.md`.

## Public voting: approval and quadratic

Separate from judging: the crowd's opinion, never mixed into the judges' ranking. Event config: `voting_mode`,
`votes_per_voter`, `vote_credits`.

| Mode | Who can vote | Voter identity (what "one person" means) |
|------|--------------|-------------------------------------------|
| `open` | anyone with the link | a signed session cookie (HMAC), plus a per-network cap |
| `email` | anyone giving an email | the **canonical** mailbox: lower-cased, `+tag` dropped, Gmail dots ignored. Not verified by a mail round-trip |
| `auth` | signed-in users | the user id |
| `quadratic` | signed-in users | the user id |

**One person, one vote by default**: `votes_per_voter = 1` for the whole event (approval voting; configurable). Enforced by
a per-event row lock (no double-vote race), a DB unique constraint on `(submission, voter)`, and a budget count on
`(event, voter)`. Votes are accepted only while the event status is `voting` and inside the optional window.

**Quadratic voting** (a documented alternative that resists whales): each voter gets `C` credits (default 25) and may put `n` votes
on a project at a cost of `n²` credits, re-allocating freely. Worked example with `C = 25`:

| Allocation | Votes | Credits spent |
|------------|------:|--------------:|
| project A: 3 | 3 | 9 |
| project B: 4 | 4 | 16 |
| project C: 1 more | rejected | would need 1 → 26 > 25 |
| re-allocate A to 1 (cost 1), then C to 2 (cost 4) | 1 + 4 + 2 | 1 + 16 + 4 = 21 |

The marginal cost of the k-th vote on one project is `2k − 1`, so spreading support is cheaper than piling it on: a
voter can push one project to 5 votes (25 credits) or support 25 projects with one vote each. The tally of a project is the
**sum of weights**. Tested in `test_voting_abuse.py::test_quadratic_voting` and live in `frontend/e2e-ui-flows.py`.

**Results are hidden** from everyone except organizers/admins while the event is in `voting` (count endpoint, embed, webhooks and
audit never carry a tally); the tally becomes public when the event closes. **Ballot order is randomized per voter**
(`GET /events/{id}/ballot`, seeded shuffle keyed by user id or session), stable across reloads, different across voters,
so no project benefits from being listed first. **Rate limits** on votes and comments (per IP + identity, plus a looser per-IP
ceiling so rotating cookies does not help) return `429` with `Retry-After`.

## Tie-breaking

Applied to both the raw and the normalized ranking (`_compute_results`):

1. higher score;
2. more judge reviews;
3. earlier `submitted_at`;
4. submission name, alphabetical.

## Edge cases

| Case | Behaviour |
|------|-----------|
| No scores | Empty results; CSV contains only the header row |
| Single judge overall | z-scores centre on 0, relative order preserved |
| Judge with one review, or identical scores | Zero-variance fallback above |
| Judge skipped a criterion | Weighted mean over the criteria they scored |
| Uneven review counts (2 vs 5) | Supported; `judge_count` is reported per submission |
| Unknown / non-numeric fixture score | Skipped on import, noted in the import summary |
| Scores on a submission not in the event | Ignored |

## Not implemented

A pairwise / Bradley-Terry judging mode is not built. The UI has a "duel" page that degrades gracefully (`501`) so nothing
breaks; normalized absolute scoring (above) is the shipped method.
