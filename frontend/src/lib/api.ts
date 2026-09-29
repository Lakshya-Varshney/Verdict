import type * as T from "./types";

export const USE_MOCK = process.env.NEXT_PUBLIC_MOCK !== "false";
const BASE = process.env.NEXT_PUBLIC_API_URL || "/api";
const TOKEN_KEY = "verdict.token";

export class ApiError extends Error {
  constructor(public status: number, public detail: string) { super(detail); this.name = "ApiError"; }
}
export const getToken = () => (typeof window === "undefined" ? null : localStorage.getItem(TOKEN_KEY));
export const setToken = (t: string | null) => { if (t) localStorage.setItem(TOKEN_KEY, t); else localStorage.removeItem(TOKEN_KEY); };

type Opts = { body?: unknown; query?: Record<string, string | number | undefined | null>; raw?: boolean };

async function request<R>(method: string, path: string, opts: Opts = {}): Promise<R> {
  const query: Record<string, string> = {};
  Object.entries(opts.query ?? {}).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") query[k] = String(v); });
  const token = getToken();

  if (USE_MOCK) {
    const { mockFetch } = await import("./mock/router");
    const res = await mockFetch(method, path, { body: opts.body, token, query });
    if (res.status >= 400) throw new ApiError(res.status, res.data?.detail ?? "Request failed");
    return (opts.raw ? (new Blob([res.text ?? ""], { type: "text/csv" }) as unknown as R) : (res.data as R));
  }

  const qs = Object.keys(query).length ? "?" + new URLSearchParams(query).toString() : "";
  const res = await fetch(`${BASE}${path}${qs}`, {
    method,
    headers: { ...(opts.body !== undefined ? { "Content-Type": "application/json" } : {}), ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const j = await res.json();
      detail = typeof j.detail === "string" ? j.detail
        : Array.isArray(j.detail) ? j.detail.map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).filter((x) => x !== "body").join(".")}: ${d.msg ?? "invalid"}`).join("; ")
        : JSON.stringify(j.detail ?? j);
    } catch { /* not json */ }
    throw new ApiError(res.status, detail);
  }
  if (opts.raw) return (await res.blob()) as unknown as R;
  if (res.status === 204) return undefined as R;
  return (await res.json()) as R;
}

const g = <R,>(p: string, query?: Opts["query"]) => request<R>("GET", p, { query });
const post = <R,>(p: string, body?: unknown) => request<R>("POST", p, { body });
const patch = <R,>(p: string, body?: unknown) => request<R>("PATCH", p, { body });
const del = <R,>(p: string) => request<R>("DELETE", p);

type Dict = Record<string, unknown>;
const live = !USE_MOCK;

const str = (v: unknown, d = ""): string => (typeof v === "string" ? v : d);
const num = (v: unknown, d = 0): number => (typeof v === "number" ? v : d);
const list = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const strOrNull = (v: unknown): string | null => (typeof v === "string" ? v : null);

const UI_STATUSES = new Set(["draft", "open", "judging", "voting", "published", "archived"]);
const STATUS_FROM_API: Record<string, T.EventStatus> = {
  draft: "draft", live: "open", judging: "judging", voting: "voting", closed: "published",
};
const STATUS_TO_API: Record<string, string> = {
  open: "live", published: "closed", archived: "closed",
  draft: "draft", judging: "judging", voting: "voting",
};

export const fromApiStatus = (v: string): T.EventStatus =>
  UI_STATUSES.has(v) ? (v as T.EventStatus) : (STATUS_FROM_API[v] ?? "draft");
export const toApiStatus = (v: string): string => STATUS_TO_API[v] ?? v;

function toEvent(r: Dict): T.EventT {
  return {
    id: str(r.id),
    name: str(r.name),
    tagline: str(r.tagline),
    description: str(r.description),
    status: fromApiStatus(str(r.status, "draft")),
    starts_at: str(r.starts_at) || str(r.start_date),
    deadline_at: str(r.deadline_at) || str(r.submission_deadline),
    voting_opens_at: strOrNull(r.voting_opens_at),
    voting_closes_at: strOrNull(r.voting_closes_at),
    voting_mode: (str(r.voting_mode, "auth") as T.VotingMode),
    votes_per_voter: num(r.votes_per_voter, 1),
    vote_credits: num(r.vote_credits, 25),
    team_size_max: num(r.team_size_max, 4),
    prizes: (r.prizes as T.Prize[]) ?? [],
    custom_questions: (r.custom_questions as T.EventT["custom_questions"]) ?? [],
    submission_count: typeof r.submission_count === "number" ? r.submission_count : undefined,
    team_count: typeof r.team_count === "number" ? r.team_count : undefined,
  };
}

function toWebhook(r: Dict): T.Webhook {
  return {
    id: str(r.id), url: str(r.url), event_types: list(r.event_types).map(String), active: r.active !== false,
    created_at: str(r.created_at), event_id: strOrNull(r.event_id), disabled_reason: strOrNull(r.disabled_reason),
    last_status: strOrNull(r.last_status), consecutive_failures: num(r.consecutive_failures),
  };
}

function toSubmission(r: Dict): T.Submission {
  const images = list(r.images).length > 0 ? list(r.images) : list(r.gallery_image_urls);
  const tags = list(r.tags).length > 0 ? list(r.tags) : list(r.tech_tags);
  return {
    id: str(r.id),
    event_id: str(r.event_id),
    team_id: str(r.team_id),
    team_name: str(r.team_name),
    track_id: strOrNull(r.track_id),
    track_name: strOrNull(r.track_name),
    name: str(r.name),
    tagline: str(r.tagline),
    description: str(r.description) || str(r.description_md),
    thumbnail_url: strOrNull(r.thumbnail_url),
    images: images as string[],
    video_url: str(r.video_url) || str(r.demo_video_url),
    repo_url: str(r.repo_url),
    live_url: str(r.live_url),
    tags: tags as string[],
    custom_answers: (r.custom_answers as Record<string, string>) ?? {},
    status: r.status === "submitted" ? "submitted" : "draft",
    submitted_at: strOrNull(r.submitted_at),
    updated_at: str(r.updated_at) || str(r.last_edited_at) || str(r.created_at),
  };
}

function toApiSubmissionInput(b: T.SubmissionInput): Dict {
  const out: Dict = { ...b };
  if (b.description !== undefined) { out.description_md = b.description; delete out.description; }
  if (b.images !== undefined) { out.gallery_image_urls = b.images; delete out.images; }
  if (b.video_url !== undefined) { out.demo_video_url = b.video_url; delete out.video_url; }
  if (b.tags !== undefined) { out.tech_tags = b.tags; delete out.tags; }
  return out;
}

function toTeam(r: Dict): T.Team {
  return {
    id: str(r.id),
    event_id: str(r.event_id),
    name: str(r.name),
    invite_code: str(r.invite_code),
    members: list(r.members).map((m) => {
      const d = m as Dict;
      return { user_id: str(d.user_id), name: str(d.name), email: str(d.email), is_lead: d.is_lead === true };
    }),
    submission_id: strOrNull(r.submission_id),
  };
}

function toAssignment(r: Dict): T.Assignment {
  return {
    id: str(r.id),
    event_id: str(r.event_id),
    submission_id: str(r.submission_id),
    judge_id: str(r.judge_id),
    submission_name: str(r.submission_name),
    team_name: str(r.team_name),
    track_name: strOrNull(r.track_name),
    scored_criteria: num(r.scored_criteria),
    total_criteria: num(r.total_criteria),
    complete: r.complete === true,
  };
}

function toComment(r: Dict): T.Comment {
  return {
    id: str(r.id),
    submission_id: str(r.submission_id),
    user_id: str(r.user_id) || str(r.author_id),
    user_name: str(r.user_name) || str(r.author_name) || "Anonymous",
    body: str(r.body),
    created_at: str(r.created_at),
  };
}

function toAuditEntry(r: Dict): T.AuditEntry {
  const outcome = str(r.outcome, "ok");
  return {
    id: str(r.id),
    at: str(r.at) || str(r.created_at),
    actor_id: strOrNull(r.actor_id),
    actor_name: str(r.actor_name, "system"),
    actor_role: str(r.actor_role, "participant"),
    action: str(r.action),
    target: str(r.target),
    outcome: outcome === "denied" ? "denied" : "ok",
    detail: str(r.detail),
    ip: str(r.ip, "127.0.0.1"),
    event_id: strOrNull(r.event_id),
  };
}

function toCriterion(r: Dict): T.Criterion {
  return {
    id: str(r.id),
    event_id: str(r.event_id),
    name: str(r.name),
    description: str(r.description),
    weight: num(r.weight, 1),
    max_score: num(r.max_score, 10),
  };
}

function toEventRole(r: Dict): T.EventRole {
  const out: T.EventRole = { event_id: str(r.event_id), role: str(r.role) as T.EventRole["role"] };
  if (typeof r.user_id === "string") out.user_id = r.user_id;
  if (typeof r.user_name === "string") out.user_name = r.user_name;
  if (typeof r.user_email === "string") out.user_email = r.user_email;
  return out;
}

function toMe(r: Dict): T.Me {
  const rawRoles = list(r.event_roles);
  const is_admin = rawRoles.some((x) => str((x as Dict).role) === "admin");
  const roles: T.EventRole[] = rawRoles
    .filter((x) => {
      const role = str((x as Dict).role);
      return role !== "admin" && role !== "visitor";
    })
    .map((x) => {
      const d = x as Dict;
      const out: T.EventRole = { event_id: str(d.event_id), role: str(d.role) as T.EventRole["role"] };
      if (typeof d.user_name === "string") out.user_name = d.user_name;
      if (typeof d.user_email === "string") out.user_email = d.user_email;
      return out;
    });
  return {
    user: { id: str(r.id), email: str(r.email), name: str(r.name), is_admin },
    roles,
  };
}

function toAuthResult(r: Dict): T.AuthResult {
  const u = (r.user ?? {}) as Dict;
  return {
    user: { id: str(u.id), email: str(u.email), name: str(u.name), is_admin: false },
    token: str(r.token),
  };
}

function page<U>(items: U[], pageNum = 1, limitNum = 100): T.Page<U> {
  return { items, total: items.length, page: pageNum, limit: limitNum };
}

export const api = {
  auth: {
    signup: async (b: { email: string; password: string; name: string }): Promise<T.AuthResult> => {
      const data = await post<Dict>("/auth/signup", b);
      return live ? toAuthResult(data) : (data as unknown as T.AuthResult);
    },
    login: async (b: { email: string; password: string }): Promise<T.AuthResult> => {
      const data = await post<Dict>("/auth/login", b);
      return live ? toAuthResult(data) : (data as unknown as T.AuthResult);
    },
    logout: async (): Promise<{ ok: boolean }> => {
      if (!live) return post<{ ok: boolean }>("/auth/logout");
      await post("/auth/logout");
      return { ok: true };
    },
    me: async (): Promise<T.Me> => {
      const data = await g<Dict>("/auth/me");
      return live ? toMe(data) : (data as unknown as T.Me);
    },
  },
  events: {
    list: async (status?: string): Promise<T.Page<T.EventT>> => {
      const data = await g<unknown>("/events", { status, limit: 100 });
      if (!live) return data as unknown as T.Page<T.EventT>;
      const items = list(data).map((e) => toEvent(e as Dict));
      return page(items, 1, 100);
    },
    get: async (id: string): Promise<T.EventT> => {
      const data = await g<Dict>(`/events/${id}`);
      return live ? toEvent(data) : (data as unknown as T.EventT);
    },
    create: async (b: Partial<T.EventT> & { tracks?: { name: string; description?: string }[] }): Promise<T.EventT> => {
      const body: Dict = { ...b };
      if (typeof b.status === "string") body.status = toApiStatus(b.status);
      const data = await post<Dict>("/events", body);
      return live ? toEvent(data) : (data as unknown as T.EventT);
    },
    update: async (id: string, b: Partial<T.EventT>): Promise<T.EventT> => {
      const body: Dict = { ...b };
      if (typeof b.status === "string") body.status = toApiStatus(b.status);
      const data = await patch<Dict>(`/events/${id}`, body);
      return live ? toEvent(data) : (data as unknown as T.EventT);
    },
    tracks: async (id: string): Promise<T.Track[]> => {
      const data = await g<unknown>(`/events/${id}/tracks`);
      if (!live) return data as unknown as T.Track[];
      return list(data).map((t) => {
        const d = t as Dict;
        return { id: str(d.id), event_id: str(d.event_id), name: str(d.name), description: str(d.description) };
      });
    },
    addTrack: async (id: string, b: { name: string; description?: string }): Promise<T.Track> => {
      const data = await post<Dict>(`/events/${id}/tracks`, b);
      if (!live) return data as unknown as T.Track;
      return { id: str(data.id), event_id: str(data.event_id), name: str(data.name), description: str(data.description) };
    },
    roles: async (id: string): Promise<T.EventRole[]> => {
      const data = await g<unknown>(`/events/${id}/roles`);
      if (!live) return data as unknown as T.EventRole[];
      return list(data).map((r) => toEventRole(r as Dict));
    },
    addRole: async (id: string, b: { email: string; role: string }): Promise<T.EventRole> => {
      const data = await post<Dict>(`/events/${id}/roles`, b);
      return live ? toEventRole(data) : (data as unknown as T.EventRole);
    },
  },
  teams: {
    create: async (eventId: string, name: string): Promise<T.Team> => {
      const data = await post<Dict>(`/events/${eventId}/teams`, { name });
      return live ? toTeam(data) : (data as unknown as T.Team);
    },
    join: async (teamId: string, invite_code: string): Promise<T.Team> => {
      if (!live) return post<T.Team>(`/teams/${teamId}/join`, { invite_code });
      await post(`/teams/${teamId}/join`, { invite_code });
      return toTeam(await g<Dict>(`/teams/${teamId}`));
    },
    get: async (teamId: string): Promise<T.Team> => {
      const data = await g<Dict>(`/teams/${teamId}`);
      return live ? toTeam(data) : (data as unknown as T.Team);
    },
    mine: async (eventId: string): Promise<T.Team[]> => {
      const data = await g<unknown>(`/events/${eventId}/teams/mine`);
      if (!live) return data as unknown as T.Team[];
      return list(data).map((t) => toTeam(t as Dict));
    },
  },
  subs: {
    create: async (teamId: string): Promise<T.Submission> => {
      if (!live) return post<T.Submission>(`/teams/${teamId}/submissions`);
      const data = await post<Dict>(`/teams/${teamId}/submissions`, { name: "Untitled" });
      return toSubmission(data);
    },
    get: async (id: string): Promise<T.Submission> => {
      const data = await g<Dict>(`/submissions/${id}`);
      return live ? toSubmission(data) : (data as unknown as T.Submission);
    },
    update: async (id: string, b: T.SubmissionInput): Promise<T.Submission> => {
      if (!live) return patch<T.Submission>(`/submissions/${id}`, b);
      const data = await patch<Dict>(`/submissions/${id}`, toApiSubmissionInput(b));
      return toSubmission(data);
    },
    submit: async (id: string): Promise<T.Submission> => {
      const data = await post<Dict>(`/submissions/${id}/submit`);
      return live ? toSubmission(data) : (data as unknown as T.Submission);
    },
    gallery: async (
      eventId: string,
      p: { q?: string; track?: string; tag?: string; sort?: string; page?: number; limit?: number; include_drafts?: number } = {},
    ): Promise<T.Page<T.Submission>> => {
      if (!live) return g<T.Page<T.Submission>>(`/events/${eventId}/submissions`, p);
      const data = await g<unknown>(`/events/${eventId}/submissions`, {
        search: p.q,
        track_id: p.track,
        tag: p.tag,
        page: p.page,
        limit: p.limit,
      });
      const items = list(data).map((s) => toSubmission(s as Dict));
      return page(items, p.page ?? 1, p.limit ?? 20);
    },
  },
  judging: {
    criteria: async (eventId: string): Promise<T.Criterion[]> => {
      const data = await g<unknown>(`/events/${eventId}/rubric/criteria`);
      if (!live) return data as unknown as T.Criterion[];
      return list(data).map((c) => toCriterion(c as Dict));
    },
    addCriterion: async (eventId: string, b: { name: string; description?: string; weight: number }): Promise<T.Criterion> => {
      const data = await post<Dict>(`/events/${eventId}/rubric/criteria`, b);
      return live ? toCriterion(data) : (data as unknown as T.Criterion);
    },
    deleteCriterion: async (eventId: string, cid: string): Promise<{ ok: boolean }> => {
      if (!live) return del<{ ok: boolean }>(`/events/${eventId}/rubric/criteria/${cid}`);
      await del(`/events/${eventId}/rubric/criteria/${cid}`);
      return { ok: true };
    },
    assign: async (eventId: string, b: { strategy: T.AssignStrategy; reviews_per_submission: number }): Promise<T.AssignmentSet> => {
      if (!live) return post<T.AssignmentSet>(`/events/${eventId}/judging/assign`, b);
      await post(`/events/${eventId}/judging/assign`, b);
      return api.judging.allAssignments(eventId);
    },
    allAssignments: async (eventId: string): Promise<T.AssignmentSet> => {
      const data = await g<Dict>(`/events/${eventId}/judging/assignments`);
      if (!live) return data as unknown as T.AssignmentSet;
      return { assignments: list(data.assignments).map((a) => toAssignment(a as Dict)) };
    },
    mine: async (eventId: string): Promise<T.Assignment[]> => {
      const data = await g<unknown>(`/events/${eventId}/judging/assignments/mine`);
      if (!live) return data as unknown as T.Assignment[];
      return list(data).map((a) => toAssignment(a as Dict));
    },
    progress: async (eventId: string): Promise<T.Progress> => {
      const data = await g<Dict>(`/events/${eventId}/judging/progress`);
      if (!live) return data as unknown as T.Progress;
      return {
        event_id: str(data.event_id),
        judges: list(data.judges).map((j) => {
          const d = j as Dict;
          return {
            judge_id: str(d.judge_id),
            judge_name: str(d.judge_name),
            assigned: num(d.assigned),
            complete: num(d.complete),
            started: num(d.started),
          };
        }),
        total_assignments: num(data.total_assignments),
        total_complete: num(data.total_complete),
      };
    },
    score: (sid: string, b: { criterion_id: string; value: number; comment?: string }) =>
      post<{ ok: boolean }>(`/submissions/${sid}/scores`, b),
    myScores: (sid: string) => g<T.JudgeScores>(`/submissions/${sid}/scores/mine`),
    allScores: (sid: string) => g<T.JudgeScores[]>(`/submissions/${sid}/scores`),
    normalize: async (eventId: string): Promise<T.Results> => {
      if (!live) return post<T.Results>(`/events/${eventId}/judging/normalize`);
      await post(`/events/${eventId}/judging/normalize`);
      return api.judging.results(eventId);
    },
    results: (eventId: string) => g<T.Results>(`/events/${eventId}/judging/results`),
    duelNext: async (eventId: string): Promise<T.DuelNext> => {
      if (!live) return g<T.DuelNext>(`/events/${eventId}/judging/pairwise/next`);
      return { done: 0, total: 0, a: null, b: null };
    },
    duelVote: async (eventId: string, b: { a: string; b: string; winner_id: string }): Promise<{ ok: boolean }> => {
      if (!live) return post<{ ok: boolean }>(`/events/${eventId}/judging/pairwise/vote`, b);
      throw new ApiError(501, "Pairwise judging is not available yet");
    },
    duelRanking: async (eventId: string): Promise<T.PairwiseRanking> => {
      if (!live) return g<T.PairwiseRanking>(`/events/${eventId}/judging/pairwise/ranking`);
      return { comparisons: 0, judges: 0, rows: [] };
    },
    exportCsv: (eventId: string) => request<Blob>("GET", `/events/${eventId}/judging/export.csv`, { raw: true }),
    attestation: (eventId: string, judgeId?: string): Promise<T.Attestation> =>
      g<T.Attestation>(`/events/${eventId}/judging/attestation`, judgeId ? { judge_id: judgeId } : undefined),
  },
  vote: {
    cast: async (sid: string, b: { fingerprint: string; email?: string; votes?: number }): Promise<{ ok: boolean; votes?: number; votes_left?: number; credits_left?: number }> => {
      if (!live) return post<{ ok: boolean; votes?: number; votes_left?: number; credits_left?: number }>(`/submissions/${sid}/vote`, b);
      const r = await post<Dict>(`/submissions/${sid}/vote`, b);
      return { ok: true, votes: num(r.votes, 1), votes_left: typeof r.votes_left === "number" ? r.votes_left : undefined, credits_left: typeof r.credits_left === "number" ? r.credits_left : undefined };
    },
    /** Server-shuffled ballot (per-session order) + the caller's remaining budget. */
    ballot: (eventId: string, email?: string) => g<T.Ballot>(`/events/${eventId}/ballot`, email ? { email } : {}),
    count: async (sid: string): Promise<T.VoteCount> => {
      const data = await g<Dict>(`/submissions/${sid}/votes/count`);
      if (!live) return data as unknown as T.VoteCount;
      return {
        submission_id: str(data.submission_id),
        hidden: data.hidden === true,
        count: typeof data.count === "number" ? data.count : null,
      };
    },
  },
  comments: {
    list: async (sid: string): Promise<T.Comment[]> => {
      const data = await g<unknown>(`/submissions/${sid}/comments`);
      if (!live) return data as unknown as T.Comment[];
      return list(data).map((c) => toComment(c as Dict));
    },
    add: async (sid: string, body: string): Promise<T.Comment> => {
      const data = await post<Dict>(`/submissions/${sid}/comments`, { body });
      return live ? toComment(data) : (data as unknown as T.Comment);
    },
  },
  audit: {
    list: async (p: { page?: number; limit?: number; action?: string; actor?: string; outcome?: string; event_id?: string }): Promise<T.Page<T.AuditEntry>> => {
      const data = await g<Dict>("/admin/audit", {
        page: p.page,
        limit: p.limit,
        action: p.action,
        actor_id: p.actor,
        event_id: p.event_id,
      });
      if (!live) return data as unknown as T.Page<T.AuditEntry>;
      return {
        items: list(data.items).map((e) => toAuditEntry(e as Dict)),
        total: num(data.total),
        page: num(data.page, 1),
        limit: num(data.limit, 50),
      };
    },
  },
  hooks: {
    list: async (eventId?: string): Promise<T.Webhook[]> => {
      const d = await g<unknown>("/webhooks", eventId ? { event_id: eventId } : {});
      if (!live) return d as T.Webhook[];
      return list(d).map((x) => toWebhook(x as Dict));
    },
    /** The signing `secret` comes back only in this response. */
    subscribe: async (b: { url: string; event_types: string[]; event_id?: string }): Promise<T.Webhook> => {
      const d = await post<Dict>("/webhooks/subscribe", b);
      return live ? { ...toWebhook(d), secret: str(d.secret) || undefined } : (d as unknown as T.Webhook);
    },
    remove: (id: string): Promise<{ ok: boolean }> => del<{ ok: boolean }>(`/webhooks/${id}`),
    /** Queue a `webhook.ping` to check an endpoint. */
    ping: (id: string) => post<Dict>(`/webhooks/${id}/ping`),
    deliveries: async (id: string): Promise<T.WebhookDelivery[]> => {
      const d = await g<unknown>(`/webhooks/${id}/deliveries`, { limit: 20 });
      return list(d).map((x) => { const r = x as Dict; return { id: str(r.id), event_type: str(r.event_type), status: str(r.status), attempts: num(r.attempts), response_status: typeof r.response_status === "number" ? r.response_status : null, last_error: strOrNull(r.last_error), created_at: strOrNull(r.created_at), delivered_at: strOrNull(r.delivered_at) }; });
    },
  },
  data: {
    export: (eventId: string): Promise<Record<string, unknown>> => post<Record<string, unknown>>(`/events/${eventId}/export`),
    /** Restore a dump into this event. `dryRun` validates and counts without writing. */
    import: async (eventId: string, dump: unknown, dryRun = false): Promise<T.ImportResult> => {
      const r = await post<Dict>(`/events/${eventId}/import${dryRun ? "?dry_run=true" : ""}`, dump);
      if (!live) return r as unknown as T.ImportResult;
      const counts = (x: unknown) => Object.fromEntries(Object.entries((x ?? {}) as Dict).map(([k, v]) => [k, num(v)]));
      return { imported: counts(r.imported), created: counts(r.created), updated: counts(r.updated), warnings: list(r.warnings).map(String), dry_run: r.dry_run === true, checksum_verified: r.checksum_verified === true };
    },
    certificate: async (eventId: string, userId: string): Promise<T.Certificate> => {
      const d = await g<Dict>(`/events/${eventId}/certificates/${userId}`);
      if (!live) return d as unknown as T.Certificate;
      return {
        event_id: str(d.event_id), event_name: str(d.event_name), user_id: str(d.user_id), user_name: str(d.user_name),
        kind: (str(d.kind, "participant") as T.Certificate["kind"]), detail: str(d.detail), issued_at: str(d.issued_at),
        verify_hash: str(d.verify_hash), signature: str(d.signature), key_id: str(d.key_id), algorithm: str(d.algorithm), verify_url: str(d.verify_url),
      };
    },
    /** The signed PDF or verifiable-HTML form of a certificate. */
    certificateFile: (eventId: string, userId: string, format: "pdf" | "html") =>
      request<Blob>("GET", `/events/${eventId}/certificates/${userId}`, { raw: true, query: { format } }),
    /** Public: verify a certificate by its code. */
    verify: (code: string) => g<T.VerifyResult>(`/verify/${code}`),
    embed: async (eventId: string): Promise<T.EmbedGallery> => {
      if (!live) return g<T.EmbedGallery>(`/embed/${eventId}/gallery`);
      const d = await g<Dict>(`/embed/${eventId}/gallery`, { limit: 100 });
      const ev = (d.event ?? {}) as Dict;
      return { event: { id: str(ev.id), name: str(ev.name) }, items: list(d.items).map((s) => toSubmission(s as Dict)) };
    },
  },
  dev: { resetMock: () => post<{ ok: boolean }>("/__mock/reset") },
};
