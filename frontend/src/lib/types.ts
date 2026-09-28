// ---------------------------------------------------------------------------
// Types mirror the API contract (docs/api-contract.md).
// Once the FastAPI backend is live, regenerate exact types with:
//   npm run gen:api     (openapi-typescript against /openapi.json)
// and swap these imports. Anything marked ASSUMED is not in the contract yet.
// ---------------------------------------------------------------------------

export type Role = "visitor" | "participant" | "judge" | "organizer" | "admin";

// ASSUMED status values — confirm with backend.
export type EventStatus = "draft" | "open" | "judging" | "voting" | "published" | "archived";
export const EVENT_STATUSES: EventStatus[] = ["draft", "open", "judging", "voting", "published", "archived"];

export type VotingMode = "open" | "email" | "auth" | "quadratic";

export interface User { id: string; email: string; name: string; is_admin: boolean; }
export interface EventRole { event_id: string; user_id?: string; role: Exclude<Role, "visitor" | "admin">; user_name?: string; user_email?: string; }
export interface Me { user: User; roles: EventRole[]; }
export interface AuthResult { user: User; token: string; }

export interface Prize { place: string; name: string; amount: number; }
export interface EventT {
  id: string; name: string; tagline: string; description: string;
  status: EventStatus;
  starts_at: string; deadline_at: string;
  voting_opens_at: string | null; voting_closes_at: string | null;
  voting_mode: VotingMode; votes_per_voter?: number; vote_credits?: number; team_size_max: number;
  prizes: Prize[];
  custom_questions: { id: string; label: string; required: boolean }[];
  submission_count?: number; team_count?: number;
}
export interface Track { id: string; event_id: string; name: string; description: string; }

export interface Member { user_id: string; name: string; email: string; is_lead: boolean; }
export interface Team { id: string; event_id: string; name: string; invite_code: string; members: Member[]; submission_id: string | null; }

export type SubStatus = "draft" | "submitted";
export interface Submission {
  id: string; event_id: string; team_id: string; team_name: string;
  track_id: string | null; track_name: string | null;
  name: string; tagline: string; description: string;
  thumbnail_url: string | null; images: string[];
  video_url: string; repo_url: string; live_url: string;
  tags: string[]; custom_answers: Record<string, string>;
  status: SubStatus; submitted_at: string | null; updated_at: string;
  members?: Member[];
}
export type SubmissionInput = Partial<Omit<Submission, "id" | "event_id" | "team_id" | "team_name" | "track_name" | "status" | "submitted_at" | "updated_at" | "members">>;

export interface Criterion { id: string; event_id: string; name: string; description: string; weight: number; max_score: number; }
export type AssignStrategy = "round_robin" | "balanced";
export interface Assignment { id: string; event_id: string; submission_id: string; judge_id: string; submission_name: string; team_name: string; track_name: string | null; scored_criteria: number; total_criteria: number; complete: boolean; }
export interface AssignmentSet { assignments: Assignment[]; }
export interface JudgeProgress { judge_id: string; judge_name: string; assigned: number; complete: number; started: number; }
export interface Progress { event_id: string; judges: JudgeProgress[]; total_assignments: number; total_complete: number; }
export interface ScoreRow { criterion_id: string; value: number; comment?: string; }
export interface JudgeScores { judge_id: string; judge_name: string; scores: ScoreRow[]; }

export interface ResultScore { judge_id: string; judge_name: string; raw: number; norm: number | null; }
export interface ResultRow {
  submission_id: string; name: string; team_name: string; track_name: string | null;
  judge_count: number; raw_mean: number; norm_mean: number | null;
  raw_rank: number; norm_rank: number | null; scores: ResultScore[];
}
export interface JudgeBias { judge_id: string; judge_name: string; n: number; mean: number; sd: number; offset: number; zero_variance?: boolean; single_review?: boolean; }
export interface Results {
  event_id: string; normalized: boolean; normalized_at: string | null; method: string;
  published: boolean; rows: ResultRow[]; judges: JudgeBias[]; zero_variance_judges?: string[]; single_review_judges?: string[];
  spread_raw: number | null; spread_norm: number | null;
}

export interface VoterState { mode: VotingMode; my_votes: Record<string, number>; votes_used: number; votes_left: number | null; credits_total: number | null; credits_left: number | null; }
export interface Ballot {
  event_id: string; voting_mode: VotingMode; votes_per_voter: number; vote_credits: number;
  open: boolean; closed_reason: string | null; requires_auth: boolean; requires_email: boolean;
  voter: VoterState | null; items: { id: string; name: string }[];
}
export interface VoteCount { submission_id: string; hidden: boolean; count: number | null; }
export interface Comment { id: string; submission_id: string; user_id: string; user_name: string; body: string; created_at: string; }
export interface AuditEntry { id: string; at: string; actor_id: string | null; actor_name: string; actor_role: string; action: string; target: string; outcome: "ok" | "denied"; detail: string; ip: string; event_id: string | null; }
export interface Page<T> { items: T[]; total: number; page: number; limit: number; }
export interface Webhook { id: string; url: string; event_types: string[]; active: boolean; created_at: string; event_id?: string | null; secret?: string; disabled_reason?: string | null; last_status?: string | null; consecutive_failures?: number; }
export interface WebhookDelivery { id: string; event_type: string; status: string; attempts: number; response_status: number | null; last_error: string | null; created_at: string | null; delivered_at: string | null; }
export interface Certificate { event_id: string; event_name: string; user_id: string; user_name: string; kind: "participant" | "judge" | "winner"; detail: string; issued_at: string; verify_hash: string; signature?: string; key_id?: string; algorithm?: string; verify_url?: string; }
export interface VerifyResult { valid: boolean; issued_by_this_server?: boolean | null; verify_hash: string | null; key_id: string; algorithm: string;
  certificate: { kind: string; detail: string; issued_at: string; event: { id: string; name: string }; recipient: { id: string; name: string } } | null; }
export interface ImportResult { imported: Record<string, number>; created?: Record<string, number>; updated?: Record<string, number>; warnings?: string[]; dry_run?: boolean; checksum_verified?: boolean; }
export interface EmbedGallery { event: { id: string; name: string }; items: Submission[]; }

export interface DuelNext { done: number; total: number; a: Submission | null; b: Submission | null; }
export interface PairwiseRanking { comparisons: number; judges: number; rows: { submission_id: string; name: string; team_name: string; strength: number; wins: number; losses: number }[]; }
