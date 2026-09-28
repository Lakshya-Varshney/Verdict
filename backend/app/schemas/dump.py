"""JSON dump/restore format for a whole event (`POST /events/{id}/export` and `/import`).

Format `dogfood-event-dump`, version 1. Designed to be readable, diffable and forward compatible:
unknown keys are ignored on import, optional sections default to empty, and `checksum` (sha256 of the
canonical JSON of everything else) detects hand edits and truncated downloads.

Deliberately NOT in a dump: password hashes and tokens (users are matched by email on import),
normalized scores (recomputed from raw scores), and certificates (re-issued from the restored data).
"""

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

DUMP_FORMAT = "dogfood-event-dump"
DUMP_VERSION = 1


class _Row(BaseModel):
    model_config = ConfigDict(extra="ignore")


class DumpEvent(_Row):
    id: str
    name: str
    slug: Optional[str] = None
    description: Optional[str] = None
    status: str = "draft"
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    submission_deadline: Optional[str] = None
    judging_opens_at: Optional[str] = None
    judging_closes_at: Optional[str] = None
    voting_opens_at: Optional[str] = None
    voting_closes_at: Optional[str] = None
    team_formation_start: Optional[str] = None
    team_formation_end: Optional[str] = None
    voting_mode: str = "auth"
    votes_per_voter: int = 1
    vote_credits: int = 25
    created_at: Optional[str] = None


class DumpUser(_Row):
    id: str
    email: str = Field(description="Users are matched by email on import; unknown emails get a new account with no usable password")
    name: str


class DumpRole(_Row):
    user_id: str
    role: str


class DumpTrack(_Row):
    id: str
    name: str
    description: Optional[str] = None


class DumpCriterion(_Row):
    id: str
    name: str
    description: Optional[str] = None
    weight: float = 1.0
    scale_min: float = 1.0
    scale_max: float = 5.0
    track_id: Optional[str] = None


class DumpMember(_Row):
    user_id: str
    role_in_team: str = "member"


class DumpTeam(_Row):
    id: str
    name: str
    invite_code: str
    created_at: Optional[str] = None
    members: list[DumpMember] = []


class DumpSubmission(_Row):
    id: str
    team_id: str
    track_id: Optional[str] = None
    name: str
    tagline: Optional[str] = None
    description_md: Optional[str] = None
    thumbnail_url: Optional[str] = None
    gallery_image_urls: list[str] = []
    demo_video_url: Optional[str] = None
    repo_url: Optional[str] = None
    live_url: Optional[str] = None
    tech_tags: list[str] = []
    custom_answers: dict[str, Any] = {}
    status: str = "draft"
    submitted_at: Optional[str] = None
    last_edited_at: Optional[str] = None
    created_at: Optional[str] = None


class DumpAssignment(_Row):
    id: str
    judge_id: str
    submission_id: str
    batch_id: Optional[str] = None
    status: str = "pending"
    assigned_at: Optional[str] = None


class DumpScore(_Row):
    id: str
    judge_id: str
    submission_id: str
    criterion_id: str
    raw_value: float
    comment: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class DumpVote(_Row):
    id: str
    submission_id: str
    voter_fingerprint: str = Field(description="Already a SHA-256 of the voter identity; never a raw email/IP")
    ip_hash: Optional[str] = None
    weight: int = 1
    created_at: Optional[str] = None


class DumpComment(_Row):
    id: str
    submission_id: str
    author_id: Optional[str] = None
    body: str
    created_at: Optional[str] = None


class DumpAudit(_Row):
    id: str
    actor_id: Optional[str] = None
    action: str
    target_type: str
    target_id: str
    extra_data: dict[str, Any] = {}
    created_at: Optional[str] = None


class EventDump(BaseModel):
    """A complete, restorable snapshot of one event."""
    model_config = ConfigDict(extra="ignore")

    format: str = Field(DUMP_FORMAT, description=f"Always `{DUMP_FORMAT}`")
    version: int = Field(DUMP_VERSION, description="Dump format version")
    exported_at: Optional[str] = None
    checksum: Optional[str] = Field(None, description="sha256 over the canonical JSON of the rest of the document")
    event: DumpEvent
    users: list[DumpUser] = []
    roles: list[DumpRole] = []
    tracks: list[DumpTrack] = []
    criteria: list[DumpCriterion] = []
    teams: list[DumpTeam] = []
    submissions: list[DumpSubmission] = []
    assignments: list[DumpAssignment] = []
    scores: list[DumpScore] = []
    votes: list[DumpVote] = []
    comments: list[DumpComment] = []
    audit: list[DumpAudit] = []


class ImportResultOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    dry_run: bool = Field(description="True: everything was validated and counted, nothing was written")
    checksum_verified: bool = Field(description="False when the dump carried no checksum")
    imported: dict[str, int] = Field(description="Rows applied per section (created + updated)")
    created: dict[str, int]
    updated: dict[str, int]
    warnings: list[str] = []
