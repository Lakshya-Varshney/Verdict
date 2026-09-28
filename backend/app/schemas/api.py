"""Typed response models for the OpenAPI contract.

These mirror what the routes actually return (verified against live payloads). They exist so
`/openapi.json` describes every response; ``extra="allow"`` guarantees typing can never silently
drop a field the UI already relies on, and fields whose presence depends on data are Optional.
"""

from datetime import datetime
from typing import Annotated, Any, Optional
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from app.schemas.submission import SubmissionResponse


def _to_str(v: Any) -> Any:
    return v if v is None or isinstance(v, str) else str(v)


# UUID primary keys: handlers may hand back `uuid.UUID` or `str`; the wire format is always a string
Id = Annotated[str, BeforeValidator(_to_str), Field(description="UUID", json_schema_extra={"format": "uuid"})]


class _Out(BaseModel):
    model_config = ConfigDict(extra="allow", from_attributes=True)


# ------------------------------------------------------------------ events / teams

class EventOut(_Out):
    id: Id
    name: str
    slug: str
    organizer_id: Id
    tagline: str = Field("", description="First paragraph of the stored description")
    description: str = ""
    status: str = Field(description="UI status: draft | open | judging | voting | published")
    starts_at: Optional[str] = None
    start_date: Optional[str] = None
    deadline_at: Optional[str] = Field(None, description="Submission deadline (ISO 8601, UTC)")
    submission_deadline: Optional[str] = None
    team_formation_start: Optional[str] = None
    team_formation_end: Optional[str] = None
    voting_opens_at: Optional[str] = None
    voting_closes_at: Optional[str] = None
    voting_mode: str = Field("auth", description="open | email | auth | quadratic")
    votes_per_voter: int = Field(1, description="Approval-voting budget per person for the whole event")
    vote_credits: int = Field(25, description="Quadratic-voting credits per person (n votes cost n²)")
    team_size_max: int = 4
    prizes: list[Any] = []
    custom_questions: list[Any] = []
    submission_count: int = 0
    team_count: int = 0
    created_at: Optional[str] = None


class TeamMemberOut(_Out):
    user_id: Id
    name: str
    email: str
    is_lead: bool
    role_in_team: str = Field(description="leader | member")


class TeamDetailOut(_Out):
    id: Id
    event_id: Id
    name: str
    invite_code: str = Field(description="Share `/join/{team_id}?code={invite_code}` with teammates")
    created_at: Optional[str] = None
    members: list[TeamMemberOut] = []
    submission_id: Optional[Id] = None


# ------------------------------------------------------------------ submissions

class SubmissionView(SubmissionResponse):
    """Submission with the UI alias fields (`description`, `images`, `video_url`, `tags`, ...)."""
    model_config = ConfigDict(extra="allow", from_attributes=True)
    description: str = ""
    images: list[str] = []
    video_url: str = ""
    tags: list[str] = []
    updated_at: Optional[str] = None
    team_name: str = ""
    track_name: Optional[str] = None


# ------------------------------------------------------------------ rubric / judging

class CriterionOut(_Out):
    id: Id
    event_id: Id
    name: str
    description: Optional[str] = None
    weight: float
    scale_min: float
    scale_max: float
    max_score: Optional[float] = Field(None, description="Alias of scale_max (UI)")
    track_id: Optional[Id] = None


class AssignmentBrief(_Out):
    id: Id
    judge_id: Id
    submission_id: Id
    batch_id: Optional[Id] = None
    status: str
    assigned_at: Optional[datetime] = None


class AssignResult(_Out):
    ok: bool
    assignments: list[AssignmentBrief]


class AssignmentRow(_Out):
    id: Id
    event_id: Id
    submission_id: Id
    judge_id: Id
    judge_name: Optional[str] = None
    submission_name: str
    team_name: str = ""
    track_name: Optional[str] = None
    scored_criteria: int
    total_criteria: int
    complete: bool
    status: str
    assigned_at: Optional[datetime] = None


class AssignmentSetOut(_Out):
    assignments: list[AssignmentRow]


class JudgeProgress(_Out):
    judge_id: Id
    judge_name: str
    assigned: int
    complete: int
    started: int


class ProgressOut(_Out):
    event_id: Id
    judges: list[JudgeProgress]
    total_assignments: int
    total_complete: int
    total_submissions: Optional[int] = None
    total_judges: Optional[int] = None
    assignments_total: Optional[int] = None
    assignments_completed: Optional[int] = None
    completion_percentage: Optional[float] = None


class OkOut(_Out):
    ok: bool = True


class ScoreItemOut(_Out):
    criterion_id: Id
    value: float
    comment: Optional[str] = None


class JudgeScoresOut(_Out):
    judge_id: Id
    judge_name: str
    scores: list[ScoreItemOut]


class ResultRowOut(_Out):
    submission_id: Id
    name: str
    team_name: str = ""
    track_name: Optional[str] = None
    judge_count: int = Field(description="Reviews counted for this project (partial reviews included)")
    raw_mean: float
    norm_z: float = Field(description="Mean per-judge z-score")
    norm_mean: Optional[float] = Field(None, description="norm_z re-expressed in raw points")
    raw_rank: int
    norm_rank: Optional[int] = None
    scores: list[Any] = Field([], description="Always empty here; per-judge scores are organizer-only elsewhere")


class JudgeBiasOut(_Out):
    judge_id: Id
    judge_name: str
    n: int = Field(description="Number of projects this judge scored")
    mean: float
    sd: float
    offset: float = Field(description="Judge mean minus the pooled mean (harsh < 0 < generous)")
    zero_variance: bool = Field(description="sd == 0: standardised against the pooled mean/sd instead")
    single_review: bool = False


class ResultsOut(_Out):
    event_id: Id
    normalized: bool
    normalized_at: Optional[str] = None
    method: str = Field(description="per_judge_z_score")
    published: bool
    rows: list[ResultRowOut]
    judges: list[JudgeBiasOut]
    zero_variance_judges: list[str] = []
    single_review_judges: list[str] = []
    spread_raw: Optional[float] = None
    spread_norm: Optional[float] = None


class NormalizeOut(_Out):
    message: str
    submissions_normalized: int
    zero_variance_judges: list[str] = []


# ------------------------------------------------------------------ voting

class VoteOut(_Out):
    ok: bool = True
    id: Id
    submission_id: Id
    created_at: Optional[str] = None
    votes: int = Field(description="Votes now allocated to this project (1 for approval voting)")
    votes_left: Optional[int] = Field(None, description="Remaining approval votes (null in quadratic mode)")
    credits_left: Optional[int] = Field(None, description="Remaining credits (quadratic mode only)")
    mode: str


class VoteCountOut(_Out):
    submission_id: Id
    hidden: bool = Field(description="True while the event is in `voting` and the caller is not an organizer")
    count: Optional[int] = None
    vote_count: Optional[int] = None


class VoterStateOut(_Out):
    mode: str
    my_votes: dict[str, int] = Field({}, description="submission_id -> votes you allocated")
    votes_used: int
    votes_left: Optional[int] = None
    credits_total: Optional[int] = None
    credits_left: Optional[int] = None


class BallotItemOut(_Out):
    id: Id
    name: str
    tagline: Optional[str] = None
    thumbnail_url: Optional[str] = None
    tech_tags: list[str] = []
    team_name: str = ""
    track_name: Optional[str] = None


class BallotOut(_Out):
    event_id: Id
    voting_mode: str
    votes_per_voter: int
    vote_credits: int
    open: bool
    closed_reason: Optional[str] = None
    requires_auth: bool
    requires_email: bool
    voter: Optional[VoterStateOut] = Field(None, description="null until the voter's identity is known")
    items: list[BallotItemOut] = Field(description="Submitted projects in a per-voter randomized order; no tallies")


class CommentOut(_Out):
    id: Id
    submission_id: Id
    user_id: Optional[Id] = None
    author_id: Optional[Id] = None
    user_name: str
    author_name: str
    body: str
    created_at: Optional[str] = None


# ------------------------------------------------------------------ audit

class AuditEntryOut(_Out):
    id: Id
    at: str
    created_at: str
    actor_id: Optional[Id] = None
    actor_name: str
    actor_role: str
    action: str = Field(description="e.g. vote.cast, score.update, role.grant, event.status_change")
    target: str
    target_type: str
    target_id: Id
    outcome: str = Field(description="ok | denied")
    detail: str = ""
    ip: str = ""
    event_id: Optional[Id] = None
    extra_data: dict[str, Any] = {}


class AuditPageOut(_Out):
    items: list[AuditEntryOut]
    total: int
    page: int
    limit: int


class EmbedItemOut(_Out):
    id: Id
    event_id: Id
    team_id: Id
    team_name: str = ""
    track_id: Optional[Id] = None
    track_name: Optional[str] = None
    name: str
    tagline: str = ""
    description: str = ""
    thumbnail_url: Optional[str] = None
    images: list[str] = []
    video_url: str = ""
    repo_url: str = ""
    live_url: str = ""
    tags: list[str] = []
    status: str = "submitted"
    submitted_at: Optional[str] = None
    updated_at: Optional[str] = None
    url: str = Field(description="Public project page")


class EmbedEventOut(_Out):
    id: Id
    name: str
    status: str
    tagline: str = ""


class EmbedGalleryOut(_Out):
    event: EmbedEventOut
    items: list[EmbedItemOut]
    total: int
    page: int
    limit: int
    iframe_url: str = Field(description="Drop into an <iframe src>")
    snippet: str = Field(description="One-line <script> embed")


# ------------------------------------------------------------------ certificates

class CertificateOut(_Out):
    event_id: Id
    event_name: str
    user_id: Id
    user_name: str
    kind: str = Field(description="participant | judge | winner")
    detail: str
    issued_at: str
    verify_hash: str = Field(description="Public verification code: sha256 of the canonical signed payload")
    signature: str = Field(description="Ed25519 signature over the canonical payload, base64url")
    key_id: str
    algorithm: str = "Ed25519"
    payload: dict[str, Any] = Field(description="The exact signed document")
    verify_url: str = Field(description="Public web page that verifies this certificate")
    api_verify_url: str


class VerifyRequest(BaseModel):
    payload: dict[str, Any] = Field(description="The signed document, exactly as issued")
    signature: str = Field(description="base64url Ed25519 signature")


class VerifyOut(_Out):
    valid: bool = Field(description="The signature is a valid Ed25519 signature of the payload under this server's public key")
    issued_by_this_server: Optional[bool] = Field(None, description="The document also matches a record in this server's database")
    certificate: Optional[dict[str, Any]] = Field(None, description="The signed payload (recipient, event, kind, detail, issued_at)")
    verify_hash: Optional[str] = None
    key_id: str
    algorithm: str = "Ed25519"


class SigningKeyOut(_Out):
    algorithm: str = "Ed25519"
    key_id: str
    public_key: str = Field(description="Raw 32-byte public key, base64url")
    canonicalization: str = "UTF-8 JSON, keys sorted, separators (',', ':'), ensure_ascii=false"
    how_to_verify: str


# ------------------------------------------------------------------ webhooks

class WebhookOut(_Out):
    id: Id
    url: str
    event_types: list[str]
    active: bool
    created_at: str
    event_id: Optional[Id] = Field(None, description="null = every event you organize")
    disabled_reason: Optional[str] = Field(None, description="Why an endpoint was switched off automatically")
    last_status: Optional[str] = Field(None, description="success | failing")
    last_delivery_at: Optional[str] = None
    consecutive_failures: int = 0


class WebhookCreated(WebhookOut):
    secret: str = Field(description="HMAC signing key. Shown ONCE; store it. See README for how receivers verify `X-Dogfood-Signature`.")


class DeliveryOut(_Out):
    id: Id
    event_type: str
    status: str = Field(description="pending | sending | retry | success | dead")
    attempts: int
    response_status: Optional[int] = None
    last_error: Optional[str] = None
    created_at: Optional[str] = None
    next_attempt_at: Optional[str] = None
    delivered_at: Optional[str] = None


class EventTypeOut(_Out):
    name: str
    description: str


class HealthOut(_Out):
    status: str = Field(description="`healthy` when the API can serve requests")
    version: str


class MessageOut(_Out):
    message: str


class ErrorOut(BaseModel):
    """Every non-2xx response from the API has this body."""
    detail: Any = Field(description="Human-readable message (string), or a list of validation errors for 422")

    model_config = ConfigDict(json_schema_extra={"example": {"detail": "Not enough permissions"}})
