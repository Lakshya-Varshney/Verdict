/* In-browser mock of the FastAPI contract. Mirrors paths, verbs, role checks and status codes,
   so the UI you build against this is the UI that ships against the real backend. */
import { getDb, saveDb, uid, nowIso, resetDb, type Db, type DbUser } from "./db";
import type {
  Role, EventT, Submission, Team, Results, ResultRow, JudgeBias, Assignment, Progress, AuditEntry, Certificate, VotingMode,
} from "../types";
import { hashStr, mulberry } from "../utils";

export class HttpError extends Error {
  constructor(public status: number, public detail: string) { super(detail); }
}
interface Ctx { db: Db; user: DbUser | null; params: Record<string, string>; query: URLSearchParams; body: any; }
type Handler = (c: Ctx) => any;
const routes: { method: string; re: RegExp; h: Handler }[] = [];
function route(method: string, pattern: string, h: Handler) {
  const re = new RegExp("^" + pattern.replace(/\{(\w+)\}/g, "(?<$1>[^/]+)") + "$");
  routes.push({ method, re, h });
}
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const bad = (detail: string, status = 422) => new HttpError(status, detail);

// ---------- roles / guards ----------
function roleOf(db: Db, user: DbUser | null, eventId: string): Role {
  if (!user) return "visitor";
  if (user.is_admin) return "admin";
  const rs = db.roles.filter((r) => r.event_id === eventId && r.user_id === user.id).map((r) => r.role);
  if (rs.includes("organizer")) return "organizer";
  if (rs.includes("judge")) return "judge";
  return "participant";
}
function log(c: Ctx, action: string, target: string, outcome: "ok" | "denied" = "ok", detail = "", eventId: string | null = null) {
  const role = eventId ? roleOf(c.db, c.user, eventId) : c.user ? (c.user.is_admin ? "admin" : "participant") : "visitor";
  const e: AuditEntry = {
    id: uid("au"), at: nowIso(), actor_id: c.user?.id ?? null, actor_name: c.user?.name ?? "anonymous", actor_role: role,
    action, target, outcome, detail, ip: "127.0.0.1", event_id: eventId,
  };
  c.db.audit.unshift(e);
}
/** The one reusable guard — mirrors the backend's require_role(event_id, allowed=[...]). */
function require_role(c: Ctx, eventId: string, allowed: Role[], what: string): Role {
  if (!c.db.events.find((e) => e.id === eventId)) throw new HttpError(404, "Event not found");
  const role = roleOf(c.db, c.user, eventId);
  if (!c.user && !allowed.includes("visitor")) throw new HttpError(401, "Not authenticated");
  if (role === "admin" || allowed.includes(role)) return role;
  log(c, what, `denied for role ${role}`, "denied", `403 — ${what} requires ${allowed.join("/")}`, eventId);
  saveDb();
  throw new HttpError(403, `Role '${role}' may not ${what}`);
}
const needUser = (c: Ctx) => { if (!c.user) throw new HttpError(401, "Not authenticated"); return c.user; };
const getEvent = (c: Ctx, id: string) => { const e = c.db.events.find((x) => x.id === id); if (!e) throw new HttpError(404, "Event not found"); return e; };
const getSub = (c: Ctx, id: string) => { const s = c.db.subs.find((x) => x.id === id); if (!s) throw new HttpError(404, "Submission not found"); return s; };
const memberOf = (c: Ctx, teamId: string) => !!c.user && c.db.members.some((m) => m.team_id === teamId && m.user_id === c.user!.id);
const userName = (db: Db, id: string) => db.users.find((u) => u.id === id)?.name ?? id;
const pastDeadline = (e: EventT) => Date.now() > new Date(e.deadline_at).getTime();

function teamOut(db: Db, t: { id: string; event_id: string; name: string; invite_code: string }, showCode: boolean): Team {
  const ms = db.members.filter((m) => m.team_id === t.id).map((m) => { const u = db.users.find((x) => x.id === m.user_id)!; return { user_id: u.id, name: u.name, email: u.email, is_lead: m.is_lead }; });
  return { id: t.id, event_id: t.event_id, name: t.name, invite_code: showCode ? t.invite_code : "", members: ms, submission_id: db.subs.find((s) => s.team_id === t.id)?.id ?? null };
}
function subOut(db: Db, s: Submission, withMembers = false): Submission {
  if (!withMembers) return s;
  const ms = db.members.filter((m) => m.team_id === s.team_id).map((m) => { const u = db.users.find((x) => x.id === m.user_id)!; return { user_id: u.id, name: u.name, email: "", is_lead: m.is_lead }; });
  return { ...s, members: ms };
}
function paginate<T>(arr: T[], q: URLSearchParams, def = 60) {
  const page = Math.max(1, Number(q.get("page") || 1)); const limit = Math.min(200, Math.max(1, Number(q.get("limit") || def)));
  return { items: arr.slice((page - 1) * limit, page * limit), total: arr.length, page, limit };
}

// ---------- scoring maths ----------
/** Smoothly keeps a normalised score inside (1, 5) — no artificial pile-up at exactly 5.00. */
const soft = (v: number) => 3 + 2 * Math.tanh((v - 3) / 2);
const mean = (a: number[]) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0);
const sd = (a: number[]) => { if (a.length < 2) return 0; const m = mean(a); return Math.sqrt(mean(a.map((x) => (x - m) ** 2))); };
function computeResults(db: Db, eventId: string, full: boolean): Results {
  const crits = db.criteria.filter((c) => c.event_id === eventId);
  const wsum = crits.reduce((a, c) => a + c.weight, 0) || 1;
  const totals: { sid: string; jid: string; t: number }[] = [];
  db.assigns.filter((a) => a.event_id === eventId).forEach((a) => {
    const sc = db.scores.filter((s) => s.submission_id === a.submission_id && s.judge_id === a.judge_id);
    if (crits.length && crits.every((c) => sc.some((s) => s.criterion_id === c.id))) {
      totals.push({ sid: a.submission_id, jid: a.judge_id, t: crits.reduce((acc, c) => acc + sc.find((s) => s.criterion_id === c.id)!.value * c.weight, 0) / wsum });
    }
  });
  const gAll = totals.map((x) => x.t); const gMu = mean(gAll); const gSd = sd(gAll) || 1;
  const byJudge = new Map<string, number[]>();
  totals.forEach((x) => byJudge.set(x.jid, [...(byJudge.get(x.jid) ?? []), x.t]));
  const judges: JudgeBias[] = [...byJudge.entries()].map(([jid, arr]) => ({ judge_id: jid, judge_name: userName(db, jid), n: arr.length, mean: mean(arr), sd: sd(arr), offset: mean(arr) - gMu })).sort((a, b) => a.offset - b.offset);
  const normalizedAt = db.normalized[eventId] ?? null;
  const norm = (jid: string, t: number) => {
    const j = judges.find((x) => x.judge_id === jid)!;
    if (j.n < 3 || j.sd < 0.05) return soft(t - j.offset);
    return soft(gMu + ((t - j.mean) / j.sd) * gSd);
  };
  const rows: ResultRow[] = [];
  db.subs.filter((s) => s.event_id === eventId && s.status === "submitted").forEach((s) => {
    const mine = totals.filter((x) => x.sid === s.id);
    if (!mine.length) return;
    const scores = mine.map((x) => ({ judge_id: x.jid, judge_name: userName(db, x.jid), raw: x.t, norm: normalizedAt ? norm(x.jid, x.t) : null }));
    rows.push({
      submission_id: s.id, name: s.name, team_name: s.team_name, track_name: s.track_name, judge_count: mine.length,
      raw_mean: mean(scores.map((x) => x.raw)), norm_mean: normalizedAt ? mean(scores.map((x) => x.norm as number)) : null,
      raw_rank: 0, norm_rank: null, scores: full ? scores : [],
    });
  });
  [...rows].sort((a, b) => b.raw_mean - a.raw_mean || a.name.localeCompare(b.name)).forEach((r, i) => (r.raw_rank = i + 1));
  if (normalizedAt) [...rows].sort((a, b) => (b.norm_mean as number) - (a.norm_mean as number) || a.name.localeCompare(b.name)).forEach((r, i) => (r.norm_rank = i + 1));
  const spreadOf = (pick: (s: { raw: number; norm: number | null }) => number) => {
    const per = db.subs.filter((s) => s.event_id === eventId && s.status === "submitted").map((s) => {
      const m = totals.filter((x) => x.sid === s.id).map((x) => pick({ raw: x.t, norm: normalizedAt ? norm(x.jid, x.t) : null }));
      return m.length > 1 ? sd(m) : null;
    }).filter((x): x is number => x !== null);
    return per.length ? mean(per) : null;
  };
  const ev = getEventRaw(db, eventId);
  return {
    event_id: eventId, normalized: !!normalizedAt, normalized_at: normalizedAt,
    method: "Per-judge z-score, re-scaled to the pooled mean and spread, soft-limited (tanh) to stay inside 1–5. Judges with fewer than 3 scored projects (or ~zero spread) get a mean-offset only. Final score = mean across judges.",
    published: ev?.status === "published", rows: rows.sort((a, b) => (a.norm_rank ?? a.raw_rank) - (b.norm_rank ?? b.raw_rank)),
    judges: full ? judges : [], spread_raw: spreadOf((s) => s.raw), spread_norm: normalizedAt ? spreadOf((s) => s.norm as number) : null,
  };
}
const getEventRaw = (db: Db, id: string) => db.events.find((e) => e.id === id);

// ================= ROUTES =================
// ---- auth
route("POST", "/auth/signup", (c) => {
  const { email, password, name } = c.body ?? {};
  if (!email || !/^\S+@\S+\.\S+$/.test(email)) throw bad("A valid email is required");
  if (!password || password.length < 6) throw bad("Password must be at least 6 characters");
  if (!name || !String(name).trim()) throw bad("Name is required");
  if (c.db.users.some((u) => u.email.toLowerCase() === String(email).toLowerCase())) throw new HttpError(409, "That email is already registered");
  const user: DbUser = { id: uid("u"), email, name: String(name).trim(), is_admin: false, password };
  c.db.users.push(user); c.user = user; log(c, "auth.signup", "new account");
  return { user: { id: user.id, email, name: user.name, is_admin: false }, token: `mock.${user.id}` };
});
route("POST", "/auth/login", (c) => {
  const { email, password } = c.body ?? {};
  const u = c.db.users.find((x) => x.email.toLowerCase() === String(email ?? "").toLowerCase());
  if (!u || u.password !== password) throw new HttpError(401, "Incorrect email or password");
  c.user = u; log(c, "auth.login", "session");
  return { user: { id: u.id, email: u.email, name: u.name, is_admin: u.is_admin }, token: `mock.${u.id}` };
});
route("POST", "/auth/logout", () => ({ ok: true }));
route("GET", "/auth/me", (c) => {
  const u = needUser(c);
  const seen = new Set<string>();
  const roles = c.db.roles.filter((r) => r.user_id === u.id).filter((r) => { const k = r.event_id + r.role; if (seen.has(k)) return false; seen.add(k); return true; }).map((r) => ({ event_id: r.event_id, role: r.role }));
  return { user: { id: u.id, email: u.email, name: u.name, is_admin: u.is_admin }, roles };
});

// ---- events
const eventOut = (db: Db, e: EventT): EventT => ({ ...e, submission_count: db.subs.filter((s) => s.event_id === e.id && s.status === "submitted").length, team_count: db.teams.filter((t) => t.event_id === e.id).length });
route("GET", "/events", (c) => {
  const st = c.query.get("status");
  const items = c.db.events.filter((e) => !st || e.status === st).map((e) => eventOut(c.db, e));
  return { ...paginate(items, c.query, 50) };
});
route("GET", "/events/{event_id}", (c) => eventOut(c.db, getEvent(c, c.params.event_id)));
route("POST", "/events", (c) => {
  const u = needUser(c);
  if (!u.is_admin && !c.db.roles.some((r) => r.user_id === u.id && r.role === "organizer")) { log(c, "event.create", "denied", "denied", "403 — organizer/admin only"); saveDb(); throw new HttpError(403, "Only organizers or admins can create events"); }
  const b = c.body ?? {};
  if (!b.name || String(b.name).trim().length < 3) throw bad("Event name must be at least 3 characters");
  if (!b.deadline_at) throw bad("A submission deadline is required");
  const e: EventT = {
    id: uid("evt"), name: b.name.trim(), tagline: b.tagline ?? "", description: b.description ?? "", status: "draft",
    starts_at: b.starts_at ?? nowIso(), deadline_at: b.deadline_at, voting_opens_at: b.voting_opens_at ?? null, voting_closes_at: b.voting_closes_at ?? null,
    voting_mode: (b.voting_mode as VotingMode) ?? "auth", team_size_max: b.team_size_max ?? 4, prizes: b.prizes ?? [], custom_questions: b.custom_questions ?? [],
  };
  c.db.events.unshift(e); c.db.roles.push({ event_id: e.id, user_id: u.id, role: "organizer" }); c.db.normalized[e.id] = null;
  (b.tracks ?? []).forEach((t: { name: string; description?: string }, i: number) => c.db.tracks.push({ id: uid("trk") + i, event_id: e.id, name: t.name, description: t.description ?? "" }));
  log(c, "event.create", e.name, "ok", "", e.id);
  return eventOut(c.db, e);
});
route("PATCH", "/events/{event_id}", (c) => {
  const e = getEvent(c, c.params.event_id); require_role(c, e.id, ["organizer"], "event.update");
  const b = c.body ?? {}; const before = e.status;
  (["name", "tagline", "description", "status", "starts_at", "deadline_at", "voting_opens_at", "voting_closes_at", "voting_mode", "team_size_max", "prizes", "custom_questions"] as const).forEach((k) => { if (k in b) (e as any)[k] = b[k]; });
  if (b.status && b.status !== before) log(c, b.status === "published" ? "results.publish" : "event.status", `${before} → ${b.status}`, "ok", "", e.id);
  else log(c, "event.update", e.name, "ok", "", e.id);
  return eventOut(c.db, e);
});
route("GET", "/events/{event_id}/tracks", (c) => { getEvent(c, c.params.event_id); return c.db.tracks.filter((t) => t.event_id === c.params.event_id); });
route("POST", "/events/{event_id}/tracks", (c) => {
  require_role(c, c.params.event_id, ["organizer"], "track.create");
  if (!c.body?.name) throw bad("Track name is required");
  const t = { id: uid("trk"), event_id: c.params.event_id, name: c.body.name, description: c.body.description ?? "" };
  c.db.tracks.push(t); log(c, "track.create", t.name, "ok", "", t.event_id); return t;
});
route("GET", "/events/{event_id}/roles", (c) => {
  require_role(c, c.params.event_id, ["organizer"], "roles.read");
  const seen = new Set<string>();
  return c.db.roles.filter((r) => r.event_id === c.params.event_id && r.role !== "participant" || (r.event_id === c.params.event_id && r.role === "participant")).filter((r) => { const k = r.user_id + r.role; if (seen.has(k)) return false; seen.add(k); return true; })
    .map((r) => { const u = c.db.users.find((x) => x.id === r.user_id)!; return { event_id: r.event_id, user_id: r.user_id, role: r.role, user_name: u.name, user_email: u.email }; });
});
route("POST", "/events/{event_id}/roles", (c) => {
  require_role(c, c.params.event_id, ["organizer"], "role.grant");
  const { email, role } = c.body ?? {};
  if (!email) throw bad("Email is required"); if (!["judge", "organizer", "participant"].includes(role)) throw bad("Role must be judge, organizer or participant");
  let u = c.db.users.find((x) => x.email.toLowerCase() === String(email).toLowerCase());
  if (!u) { u = { id: uid("u"), email, name: String(email).split("@")[0], is_admin: false, password: "verdict" }; c.db.users.push(u); }
  c.db.roles = c.db.roles.filter((r) => !(r.event_id === c.params.event_id && r.user_id === u!.id && r.role !== "participant"));
  c.db.roles.push({ event_id: c.params.event_id, user_id: u.id, role });
  log(c, "role.grant", `${u.name} → ${role}`, "ok", "", c.params.event_id);
  return { event_id: c.params.event_id, user_id: u.id, role, user_name: u.name, user_email: u.email };
});

// ---- teams
route("POST", "/events/{event_id}/teams", (c) => {
  const u = needUser(c); const e = getEvent(c, c.params.event_id);
  const name = String(c.body?.name ?? "").trim(); if (name.length < 2) throw bad("Team name must be at least 2 characters");
  if (e.status === "archived" || e.status === "published") throw new HttpError(403, "Registration is closed for this event");
  const mine = c.db.teams.filter((t) => t.event_id === e.id && c.db.members.some((m) => m.team_id === t.id && m.user_id === u.id));
  if (mine.length) throw new HttpError(409, "You are already on a team in this event");
  const t = { id: uid("team"), event_id: e.id, name, invite_code: (name.replace(/[^A-Za-z]/g, "").slice(0, 3).toUpperCase() || "TEA") + Math.floor(Math.random() * 9000 + 1000) };
  c.db.teams.push(t); c.db.members.push({ team_id: t.id, user_id: u.id, is_lead: true });
  if (!c.db.roles.some((r) => r.event_id === e.id && r.user_id === u.id)) c.db.roles.push({ event_id: e.id, user_id: u.id, role: "participant" });
  log(c, "team.create", name, "ok", "", e.id);
  return teamOut(c.db, t, true);
});
route("GET", "/teams/{team_id}", (c) => {
  needUser(c); const t = c.db.teams.find((x) => x.id === c.params.team_id); if (!t) throw new HttpError(404, "Team not found");
  const role = roleOf(c.db, c.user, t.event_id);
  return teamOut(c.db, t, memberOf(c, t.id) || role === "organizer" || role === "admin");
});
route("POST", "/teams/{team_id}/join", (c) => {
  const u = needUser(c); const t = c.db.teams.find((x) => x.id === c.params.team_id); if (!t) throw new HttpError(404, "Team not found");
  if (c.body?.invite_code !== t.invite_code) { log(c, "team.join", t.name, "denied", "403 — wrong invite code", t.event_id); saveDb(); throw new HttpError(403, "That invite code is not valid for this team"); }
  const e = getEvent(c, t.event_id);
  if (c.db.members.some((m) => m.team_id === t.id && m.user_id === u.id)) return teamOut(c.db, t, true);
  if (c.db.teams.some((x) => x.event_id === t.event_id && c.db.members.some((m) => m.team_id === x.id && m.user_id === u.id))) throw new HttpError(409, "You are already on a team in this event");
  if (c.db.members.filter((m) => m.team_id === t.id).length >= e.team_size_max) throw new HttpError(409, `This team is full (max ${e.team_size_max})`);
  c.db.members.push({ team_id: t.id, user_id: u.id, is_lead: false });
  if (!c.db.roles.some((r) => r.event_id === e.id && r.user_id === u.id)) c.db.roles.push({ event_id: e.id, user_id: u.id, role: "participant" });
  log(c, "team.join", t.name, "ok", "", e.id);
  return teamOut(c.db, t, true);
});
route("GET", "/events/{event_id}/teams/mine", (c) => {
  const u = needUser(c);
  return c.db.teams.filter((t) => t.event_id === c.params.event_id && c.db.members.some((m) => m.team_id === t.id && m.user_id === u.id)).map((t) => teamOut(c.db, t, true));
});

// ---- submissions
route("POST", "/teams/{team_id}/submissions", (c) => {
  needUser(c); const t = c.db.teams.find((x) => x.id === c.params.team_id); if (!t) throw new HttpError(404, "Team not found");
  if (!memberOf(c, t.id)) throw new HttpError(403, "Only team members can create a submission");
  const e = getEvent(c, t.event_id); if (pastDeadline(e)) throw new HttpError(403, "The submission deadline has passed");
  const ex = c.db.subs.find((s) => s.team_id === t.id); if (ex) throw new HttpError(409, "This team already has a submission");
  const s: Submission = { id: uid("sub"), event_id: e.id, team_id: t.id, team_name: t.name, track_id: null, track_name: null, name: "", tagline: "", description: "", thumbnail_url: null, images: [], video_url: "", repo_url: "", live_url: "", tags: [], custom_answers: {}, status: "draft", submitted_at: null, updated_at: nowIso() };
  c.db.subs.push(s); log(c, "submission.create", "draft", "ok", "", e.id); return s;
});
route("GET", "/submissions/{submission_id}", (c) => {
  const s = getSub(c, c.params.submission_id); const role = roleOf(c.db, c.user, s.event_id);
  if (s.status === "draft" && !(memberOf(c, s.team_id) || role === "organizer" || role === "admin")) throw new HttpError(404, "Submission not found");
  return subOut(c.db, s, true);
});
route("PATCH", "/submissions/{submission_id}", (c) => {
  const s = getSub(c, c.params.submission_id); needUser(c); const role = roleOf(c.db, c.user, s.event_id);
  if (!(memberOf(c, s.team_id) || role === "organizer" || role === "admin")) { log(c, "submission.update", s.name || "draft", "denied", "403 — not on this team", s.event_id); saveDb(); throw new HttpError(403, "Only the owning team can edit this submission"); }
  const e = getEvent(c, s.event_id);
  if (pastDeadline(e)) { log(c, "submission.update", s.name || "draft", "denied", "403 — past deadline", s.event_id); saveDb(); throw new HttpError(403, "The submission deadline has passed — edits are locked"); }
  const b = c.body ?? {};
  (["name", "tagline", "description", "thumbnail_url", "images", "video_url", "repo_url", "live_url", "tags", "custom_answers", "track_id"] as const).forEach((k) => { if (k in b) (s as any)[k] = b[k]; });
  if ("track_id" in b) s.track_name = c.db.tracks.find((t) => t.id === b.track_id)?.name ?? null;
  s.updated_at = nowIso(); return s;
});
route("POST", "/submissions/{submission_id}/submit", (c) => {
  const s = getSub(c, c.params.submission_id); needUser(c);
  if (!memberOf(c, s.team_id)) throw new HttpError(403, "Only team members can submit");
  const e = getEvent(c, s.event_id);
  if (pastDeadline(e)) { log(c, "submission.submit", s.name, "denied", "403 — past deadline", s.event_id); saveDb(); throw new HttpError(403, "The submission deadline has passed"); }
  const miss: string[] = [];
  if (!s.name.trim()) miss.push("name"); if (!s.tagline.trim()) miss.push("tagline"); if (s.description.trim().length < 40) miss.push("description (40+ chars)"); if (!s.repo_url.trim()) miss.push("repository URL"); if (!s.track_id && c.db.tracks.some((t) => t.event_id === e.id)) miss.push("track");
  e.custom_questions.filter((q) => q.required).forEach((q) => { if (!(s.custom_answers[q.id] ?? "").trim()) miss.push(`answer: ${q.label.slice(0, 32)}…`); });
  if (miss.length) throw bad(`Missing: ${miss.join(", ")}`);
  s.status = "submitted"; s.submitted_at = nowIso(); log(c, "submission.submit", s.name, "ok", "", e.id); return s;
});
route("GET", "/events/{event_id}/submissions", (c) => {
  const e = getEvent(c, c.params.event_id); const q = (c.query.get("q") ?? "").toLowerCase(); const track = c.query.get("track"); const tag = c.query.get("tag");
  const inc = c.query.get("include_drafts") === "1";
  if (inc) require_role(c, e.id, ["organizer"], "drafts.read");
  let items = c.db.subs.filter((s) => s.event_id === e.id && (inc || s.status === "submitted"));
  if (q) items = items.filter((s) => (s.name + s.tagline + s.team_name + s.tags.join(" ")).toLowerCase().includes(q));
  if (track) items = items.filter((s) => s.track_id === track);
  if (tag) items = items.filter((s) => s.tags.includes(tag));
  const sort = c.query.get("sort");
  items = sort === "name" ? [...items].sort((a, b) => a.name.localeCompare(b.name)) : [...items].sort((a, b) => (b.submitted_at ?? b.updated_at).localeCompare(a.submitted_at ?? a.updated_at));
  return paginate(items, c.query, 60);
});

// ---- rubric
route("GET", "/events/{event_id}/rubric/criteria", (c) => { getEvent(c, c.params.event_id); return c.db.criteria.filter((x) => x.event_id === c.params.event_id); });
route("POST", "/events/{event_id}/rubric/criteria", (c) => {
  require_role(c, c.params.event_id, ["organizer"], "rubric.configure");
  const b = c.body ?? {}; if (!b.name) throw bad("Criterion name is required"); if (!(b.weight > 0)) throw bad("Weight must be greater than 0");
  const cr = { id: uid("crit"), event_id: c.params.event_id, name: b.name, description: b.description ?? "", weight: Number(b.weight), max_score: 5 };
  c.db.criteria.push(cr); log(c, "rubric.criterion.create", cr.name, "ok", "", c.params.event_id); return cr;
});
route("DELETE", "/events/{event_id}/rubric/criteria/{criterion_id}", (c) => { // ASSUMED endpoint
  require_role(c, c.params.event_id, ["organizer"], "rubric.configure");
  c.db.criteria = c.db.criteria.filter((x) => x.id !== c.params.criterion_id); c.db.scores = c.db.scores.filter((s) => s.criterion_id !== c.params.criterion_id);
  log(c, "rubric.criterion.delete", c.params.criterion_id, "ok", "", c.params.event_id); return { ok: true };
});

// ---- judging
route("POST", "/events/{event_id}/judging/assign", (c) => {
  const eid = c.params.event_id; require_role(c, eid, ["organizer"], "judging.assign");
  const strategy = c.body?.strategy ?? "round_robin"; const k = Number(c.body?.reviews_per_submission ?? 3);
  const judges = [...new Set(c.db.roles.filter((r) => r.event_id === eid && r.role === "judge").map((r) => r.user_id))];
  const subs = c.db.subs.filter((s) => s.event_id === eid && s.status === "submitted");
  if (!judges.length) throw bad("Invite at least one judge first"); if (!subs.length) throw bad("There are no submitted projects to assign");
  if (!(k >= 1) || k > judges.length) throw bad(`Reviews per project must be between 1 and ${judges.length} (number of judges)`);
  c.db.assigns = c.db.assigns.filter((a) => a.event_id !== eid); c.db.scores = c.db.scores.filter((s) => !subs.some((x) => x.id === s.submission_id));
  const load: Record<string, number> = Object.fromEntries(judges.map((j) => [j, 0]));
  subs.forEach((s, i) => {
    let chosen: string[];
    if (strategy === "balanced") chosen = [...judges].sort((a, b) => load[a] - load[b] || (hashStr(a + s.id) - hashStr(b + s.id))).slice(0, k);
    else chosen = Array.from({ length: k }, (_, x) => judges[(i * k + x) % judges.length]);
    chosen.forEach((j) => { load[j]++; c.db.assigns.push({ id: `as_${s.id}_${j}`, event_id: eid, submission_id: s.id, judge_id: j }); });
  });
  log(c, "judging.assign", `${strategy} × ${k} reviews`, "ok", `${c.db.assigns.filter((a) => a.event_id === eid).length} assignments`, eid);
  return { assignments: assignmentRows(c, eid, null) };
});
function assignmentRows(c: Ctx, eid: string, judgeId: string | null): Assignment[] {
  const crits = c.db.criteria.filter((x) => x.event_id === eid);
  return c.db.assigns.filter((a) => a.event_id === eid && (!judgeId || a.judge_id === judgeId)).map((a) => {
    const s = c.db.subs.find((x) => x.id === a.submission_id)!;
    const done = c.db.scores.filter((x) => x.submission_id === a.submission_id && x.judge_id === a.judge_id).length;
    return { id: a.id, event_id: eid, submission_id: a.submission_id, judge_id: a.judge_id, submission_name: s.name, team_name: s.team_name, track_name: s.track_name, scored_criteria: done, total_criteria: crits.length, complete: crits.length > 0 && done >= crits.length };
  });
}
route("GET", "/events/{event_id}/judging/assignments/mine", (c) => { require_role(c, c.params.event_id, ["judge", "organizer"], "assignments.read"); return assignmentRows(c, c.params.event_id, c.user!.id); });
route("GET", "/events/{event_id}/judging/assignments", (c) => { require_role(c, c.params.event_id, ["organizer"], "assignments.read"); return { assignments: assignmentRows(c, c.params.event_id, null) }; }); // ASSUMED (organizer matrix view)
route("GET", "/events/{event_id}/judging/progress", (c) => {
  const eid = c.params.event_id; require_role(c, eid, ["organizer"], "progress.read");
  const rows = assignmentRows(c, eid, null); const ids = [...new Set(c.db.roles.filter((r) => r.event_id === eid && r.role === "judge").map((r) => r.user_id))];
  const p: Progress = { event_id: eid, judges: ids.map((j) => { const mine = rows.filter((r) => r.judge_id === j); return { judge_id: j, judge_name: userName(c.db, j), assigned: mine.length, complete: mine.filter((r) => r.complete).length, started: mine.filter((r) => r.scored_criteria > 0).length }; }), total_assignments: rows.length, total_complete: rows.filter((r) => r.complete).length };
  return p;
});
route("POST", "/submissions/{submission_id}/scores", (c) => {
  const s = getSub(c, c.params.submission_id); const u = needUser(c); const e = getEvent(c, s.event_id);
  const role = roleOf(c.db, u, s.event_id);
  const assigned = c.db.assigns.some((a) => a.submission_id === s.id && a.judge_id === u.id);
  if (role !== "judge" || !assigned) { log(c, "score.upsert", s.name, "denied", "403 — not assigned to this submission", s.event_id); saveDb(); throw new HttpError(403, "You are not assigned to this submission"); }
  if (e.status !== "judging") throw new HttpError(403, "Judging is not open for this event");
  const list = Array.isArray(c.body?.scores) ? c.body.scores : [c.body];
  list.forEach((b: any) => {
    const cr = c.db.criteria.find((x) => x.id === b?.criterion_id && x.event_id === s.event_id); if (!cr) throw bad("Unknown criterion");
    const v = Number(b.value); if (!Number.isInteger(v) || v < 1 || v > cr.max_score) throw bad(`Score must be a whole number 1–${cr.max_score}`);
    const ex = c.db.scores.find((x) => x.submission_id === s.id && x.judge_id === u.id && x.criterion_id === cr.id);
    if (ex) { ex.value = v; if ("comment" in b) ex.comment = b.comment; } else c.db.scores.push({ submission_id: s.id, judge_id: u.id, criterion_id: cr.id, value: v, comment: b.comment });
  });
  log(c, "score.upsert", s.name, "ok", "", s.event_id);
  return { ok: true };
});
route("GET", "/submissions/{submission_id}/scores/mine", (c) => {
  const s = getSub(c, c.params.submission_id); const u = needUser(c); const role = roleOf(c.db, u, s.event_id);
  if (role !== "judge") throw new HttpError(403, "Only judges have personal scores");
  return { judge_id: u.id, judge_name: u.name, scores: c.db.scores.filter((x) => x.submission_id === s.id && x.judge_id === u.id).map((x) => ({ criterion_id: x.criterion_id, value: x.value, comment: x.comment })) };
});
route("GET", "/submissions/{submission_id}/scores", (c) => {
  const s = getSub(c, c.params.submission_id); require_role(c, s.event_id, ["organizer"], "scores.read");
  const ids = [...new Set(c.db.scores.filter((x) => x.submission_id === s.id).map((x) => x.judge_id))];
  return ids.map((j) => ({ judge_id: j, judge_name: userName(c.db, j), scores: c.db.scores.filter((x) => x.submission_id === s.id && x.judge_id === j).map((x) => ({ criterion_id: x.criterion_id, value: x.value, comment: x.comment })) }));
});
route("GET", "/events/{event_id}/judging/attestation", (c) => {
  // Mock stand-in only: a fake signature, not real Ed25519 (the real maths lives in the backend -
  // see frontend/README.md). Good enough to demo the UI with no backend.
  const eid = c.params.event_id; const u = needUser(c); const e = getEvent(c, eid);
  const targetId = c.query.get("judge_id") || u.id;
  if (targetId !== u.id) require_role(c, eid, ["organizer", "admin"], "attestation.read");
  const target = c.db.users.find((x) => x.id === targetId); if (!target) throw new HttpError(404, "User not found");
  const subs = c.db.subs.filter((s) => s.event_id === eid);
  const mine = c.db.scores.filter((x) => x.judge_id === targetId && subs.some((s) => s.id === x.submission_id));
  if (!mine.length) throw new HttpError(404, "You have not scored any submissions in this event yet");
  const scores = mine.map((x) => {
    const sub = subs.find((s) => s.id === x.submission_id)!;
    const crit = c.db.criteria.find((cr) => cr.id === x.criterion_id);
    return { submission_id: sub.id, submission_name: sub.name, criterion_id: x.criterion_id, criterion_name: crit?.name ?? x.criterion_id, value: x.value, comment: x.comment ?? "", updated_at: nowIso() };
  });
  const payload = { v: 1, issuer: "DOGFOOD", kind: "judge_score_attestation", event: { id: eid, name: e.name }, recipient: { id: target.id, name: target.name },
    detail: `Signed record of ${scores.length} score${scores.length !== 1 ? "s" : ""} submitted for ${e.name}, as of this moment`,
    issued_at: nowIso(), record: { scores } };
  log(c, "judging.attestation_issued", target.name, "ok", `${scores.length} scores`, eid);
  return { payload, signature: "mock-signature-not-cryptographically-real", key_id: "mock0000", algorithm: "Ed25519", verify_hash: hashStr(JSON.stringify(payload)).toString(16).padStart(16, "0") };
});
route("POST", "/events/{event_id}/judging/normalize", (c) => {
  const eid = c.params.event_id; require_role(c, eid, ["organizer"], "judging.normalize");
  const r0 = computeResults(c.db, eid, true); if (!r0.rows.length) throw bad("No fully-scored reviews to normalise yet");
  c.db.normalized[eid] = nowIso(); log(c, "judging.normalize", "per-judge z-score", "ok", "", eid);
  return computeResults(c.db, eid, true);
});
route("GET", "/events/{event_id}/judging/results", (c) => {
  const eid = c.params.event_id; const e = getEvent(c, eid); const role = roleOf(c.db, c.user, eid);
  const privileged = role === "organizer" || role === "admin";
  if (!privileged && e.status !== "published") { log(c, "results.read", "sealed results", "denied", "403 — results are sealed until published", eid); saveDb(); throw new HttpError(403, "Results are sealed until the organizer publishes them"); }
  return computeResults(c.db, eid, privileged);
});
route("GET", "/events/{event_id}/judging/export.csv", (c) => {
  const eid = c.params.event_id; require_role(c, eid, ["organizer"], "export.csv");
  const r = computeResults(c.db, eid, true); const esc = (v: string | number | null) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  const lines = [["rank", "raw_rank", "submission", "team", "track", "judges", "raw_mean", "norm_mean"].join(",")];
  r.rows.forEach((x) => lines.push([x.norm_rank ?? x.raw_rank, x.raw_rank, esc(x.name), esc(x.team_name), esc(x.track_name), x.judge_count, x.raw_mean.toFixed(3), x.norm_mean?.toFixed(3) ?? ""].join(",")));
  log(c, "export.csv", "results", "ok", "", eid);
  return { __text: lines.join("\n"), type: "text/csv" };
});


// ---- pairwise duels (ASSUMED endpoints — Pairwise Mode bonus)
route("GET", "/events/{event_id}/judging/pairwise/next", (c) => {
  const eid = c.params.event_id; require_role(c, eid, ["judge"], "pairwise.read"); const me = c.user!.id;
  const mine = c.db.assigns.filter((a) => a.event_id === eid && a.judge_id === me).map((a) => a.submission_id);
  const done = c.db.duels.filter((d) => d.event_id === eid && d.judge_id === me); const key = (a: string, b: string) => [a, b].sort().join("|");
  const seen = new Set(done.map((d) => key(d.a, d.b))); const appear: Record<string, number> = {}; done.forEach((d) => { appear[d.a] = (appear[d.a] ?? 0) + 1; appear[d.b] = (appear[d.b] ?? 0) + 1; });
  const pairs: [string, string][] = []; for (let i = 0; i < mine.length; i++) for (let j = i + 1; j < mine.length; j++) if (!seen.has(key(mine[i], mine[j]))) pairs.push([mine[i], mine[j]]);
  const total = Math.min(12, mine.length * (mine.length - 1) / 2);
  if (done.length >= total || !pairs.length) return { done: done.length, total, a: null, b: null };
  pairs.sort((p, q) => ((appear[p[0]] ?? 0) + (appear[p[1]] ?? 0)) - ((appear[q[0]] ?? 0) + (appear[q[1]] ?? 0)) || hashStr(p.join() + done.length) - hashStr(q.join() + done.length));
  const [a, b] = pairs[0]; const flip = hashStr(a + b + done.length) % 2 === 0;
  return { done: done.length, total, a: getSub(c, flip ? a : b), b: getSub(c, flip ? b : a) };
});
route("POST", "/events/{event_id}/judging/pairwise/vote", (c) => {
  const eid = c.params.event_id; require_role(c, eid, ["judge"], "pairwise.vote"); const { a, b, winner_id } = c.body ?? {};
  if (getEvent(c, eid).status !== "judging") throw new HttpError(403, "Judging is not open for this event");
  const mine = c.db.assigns.filter((x) => x.event_id === eid && x.judge_id === c.user!.id).map((x) => x.submission_id);
  if (!mine.includes(a) || !mine.includes(b) || ![a, b].includes(winner_id)) { log(c, "pairwise.vote", "duel", "denied", "403 — not your assignment", eid); saveDb(); throw new HttpError(403, "You can only compare projects assigned to you"); }
  c.db.duels.push({ event_id: eid, judge_id: c.user!.id, a, b, winner: winner_id }); log(c, "pairwise.vote", "duel", "ok", "", eid); return { ok: true };
});
route("GET", "/events/{event_id}/judging/pairwise/ranking", (c) => {
  const eid = c.params.event_id; require_role(c, eid, ["organizer"], "pairwise.read"); const ds = c.db.duels.filter((d) => d.event_id === eid);
  const ids = [...new Set(ds.flatMap((d) => [d.a, d.b]))]; const p: Record<string, number> = Object.fromEntries(ids.map((i) => [i, 1]));
  for (let it = 0; it < 120; it++) { const np: Record<string, number> = {}; ids.forEach((i) => { const W = ds.filter((d) => d.winner === i).length + 0.1; let den = 0; ds.forEach((d) => { if (d.a === i || d.b === i) { const o = d.a === i ? d.b : d.a; den += 1 / (p[i] + p[o]); } }); np[i] = W / (den || 1); }); const g = Math.exp(ids.reduce((a, i) => a + Math.log(np[i]), 0) / ids.length); ids.forEach((i) => (p[i] = np[i] / g)); }
  const rows = ids.map((i) => { const s = getSub(c, i); const w = ds.filter((d) => d.winner === i).length; const n = ds.filter((d) => d.a === i || d.b === i).length; return { submission_id: i, name: s.name, team_name: s.team_name, strength: Math.log(p[i]), wins: w, losses: n - w }; }).sort((x, y) => y.strength - x.strength);
  return { comparisons: ds.length, judges: new Set(ds.map((d) => d.judge_id)).size, rows };
});

// ---- voting & comments
route("POST", "/submissions/{submission_id}/vote", (c) => {
  const s = getSub(c, c.params.submission_id); const e = getEvent(c, s.event_id); const b = c.body ?? {};
  if (e.status !== "voting") { log(c, "vote.cast", s.name, "denied", "403 — outside the voting window", e.id); saveDb(); throw new HttpError(403, "Voting is not open for this event"); }
  if (e.voting_mode === "auth" || e.voting_mode === "quadratic") needUser(c);
  if (e.voting_mode === "email" && !/^\S+@\S+\.\S+$/.test(b.email ?? "")) throw bad("This ballot requires a valid email");
  const fp = c.user ? `u:${c.user.id}` : String(b.fingerprint ?? ""); if (!fp) throw bad("Missing fingerprint");
  const mine = c.db.votes.filter((v) => v.fp === fp && c.db.subs.find((x) => x.id === v.submission_id)?.event_id === e.id);
  if (e.voting_mode === "quadratic") {
    const n = Math.max(0, Math.floor(Number(b.votes ?? 0))); const ex = mine.find((v) => v.submission_id === s.id);
    const spent = mine.filter((v) => v.submission_id !== s.id).reduce((a, v) => a + v.count ** 2, 0);
    if (spent + n * n > 25) { log(c, "vote.cast", s.name, "denied", "422 — credit budget exceeded", e.id); saveDb(); throw bad("Not enough credits — cost is votes² out of 25"); }
    if (ex) ex.count = n; else if (n > 0) c.db.votes.push({ submission_id: s.id, fp, count: n, at: nowIso() });
    log(c, "vote.cast", s.name, "ok", `${n} vote(s), ${n * n} credits`, e.id);
    return { ok: true, votes: n, credits_left: 25 - spent - n * n };
  }
  if (mine.some((v) => v.submission_id === s.id)) { log(c, "vote.cast", s.name, "denied", "409 — duplicate ballot", e.id); saveDb(); throw new HttpError(409, "You already voted for this project"); }
  if (mine.length >= 3) { log(c, "vote.cast", s.name, "denied", "429 — ballot limit", e.id); saveDb(); throw new HttpError(429, "Ballot limit reached — you get 3 votes"); }
  c.db.votes.push({ submission_id: s.id, fp, count: 1, at: nowIso() });
  log(c, "vote.cast", s.name, "ok", "", e.id);
  return { ok: true, votes: 1, votes_left: 3 - mine.length - 1 };
});
route("GET", "/submissions/{submission_id}/votes/count", (c) => {
  const s = getSub(c, c.params.submission_id); const e = getEvent(c, s.event_id); const role = roleOf(c.db, c.user, e.id);
  const total = (c.db.voteBase[s.id] ?? 0) + c.db.votes.filter((v) => v.submission_id === s.id).reduce((a, v) => a + v.count, 0);
  if (e.status === "voting" && role !== "organizer" && role !== "admin") return { submission_id: s.id, hidden: true, count: null };
  return { submission_id: s.id, hidden: false, count: total };
});
route("GET", "/submissions/{submission_id}/comments", (c) => { getSub(c, c.params.submission_id); return c.db.comments.filter((x) => x.submission_id === c.params.submission_id).sort((a, b) => b.created_at.localeCompare(a.created_at)); });
route("POST", "/submissions/{submission_id}/comments", (c) => {
  const s = getSub(c, c.params.submission_id); const u = needUser(c); const body = String(c.body?.body ?? "").trim();
  if (!body) throw bad("Comment cannot be empty"); if (body.length > 800) throw bad("Comment is too long (800 max)");
  const cm = { id: uid("cm"), submission_id: s.id, user_id: u.id, user_name: u.name, body, created_at: nowIso() };
  c.db.comments.push(cm); log(c, "comment.create", s.name, "ok", "", s.event_id); return cm;
});
route("GET", "/admin/audit", (c) => {
  const u = needUser(c);
  const orgEvents = new Set(c.db.roles.filter((r) => r.user_id === u.id && r.role === "organizer").map((r) => r.event_id));
  if (!u.is_admin && !orgEvents.size) { log(c, "audit.read", "audit log", "denied", "403 — organizer/admin only"); saveDb(); throw new HttpError(403, "Only organizers and admins can read the audit log"); }
  const q = c.query; let items = c.db.audit.filter((a) => u.is_admin || (a.event_id && orgEvents.has(a.event_id)));
  if (q.get("event_id")) items = items.filter((a) => a.event_id === q.get("event_id"));
  if (q.get("action")) items = items.filter((a) => a.action.startsWith(q.get("action")!));
  if (q.get("actor")) items = items.filter((a) => a.actor_name.toLowerCase().includes(q.get("actor")!.toLowerCase()));
  if (q.get("outcome")) items = items.filter((a) => a.outcome === q.get("outcome"));
  return paginate(items, q, 25);
});

// ---- stretch
route("GET", "/webhooks", (c) => { const u = needUser(c); if (!u.is_admin && !c.db.roles.some((r) => r.user_id === u.id && r.role === "organizer")) throw new HttpError(403, "Organizers only"); return c.db.webhooks; }); // ASSUMED
route("POST", "/webhooks/subscribe", (c) => {
  const u = needUser(c); if (!u.is_admin && !c.db.roles.some((r) => r.user_id === u.id && r.role === "organizer")) throw new HttpError(403, "Only organizers can register webhooks");
  const { url, event_types } = c.body ?? {}; if (!/^https?:\/\/.+/.test(url ?? "")) throw bad("Webhook URL must start with http:// or https://"); if (!Array.isArray(event_types) || !event_types.length) throw bad("Pick at least one event type");
  const w = { id: uid("wh"), url, event_types, active: true, created_at: nowIso() }; c.db.webhooks.push(w); log(c, "webhook.subscribe", url); return w;
});
route("DELETE", "/webhooks/{id}", (c) => { needUser(c); c.db.webhooks = c.db.webhooks.filter((w) => w.id !== c.params.id); return { ok: true }; }); // ASSUMED
route("GET", "/events/{event_id}/certificates/{user_id}", (c) => {
  const eid = c.params.event_id; const u = needUser(c); const e = getEvent(c, eid); const role = roleOf(c.db, u, eid);
  if (u.id !== c.params.user_id && role !== "organizer" && role !== "admin") throw new HttpError(403, "You can only view your own certificate");
  const target = c.db.users.find((x) => x.id === c.params.user_id); if (!target) throw new HttpError(404, "User not found");
  const tr = c.db.roles.filter((r) => r.event_id === eid && r.user_id === target.id).map((r) => r.role);
  if (!tr.length) throw new HttpError(404, "No participation record for this user");
  let kind: Certificate["kind"] = tr.includes("judge") ? "judge" : "participant"; let detail = kind === "judge" ? "Served on the judging panel" : "Completed a submission";
  if (kind === "participant" && e.status === "published") {
    const res = computeResults(c.db, eid, false); const team = c.db.teams.find((t) => t.event_id === eid && c.db.members.some((m) => m.team_id === t.id && m.user_id === target.id));
    const sub = team && c.db.subs.find((s) => s.team_id === team.id); const row = sub && res.rows.find((r) => r.submission_id === sub.id);
    if (row && (row.norm_rank ?? row.raw_rank) <= 3) { kind = "winner"; detail = `Placed #${row.norm_rank ?? row.raw_rank} with “${row.name}”`; }
  }
  return { event_id: eid, event_name: e.name, user_id: target.id, user_name: target.name, kind, detail, issued_at: e.deadline_at, verify_hash: (hashStr(eid + target.id + kind).toString(16) + hashStr(target.id + eid).toString(16)).padEnd(16, "0") } satisfies Certificate;
});
route("POST", "/events/{event_id}/export", (c) => {
  const eid = c.params.event_id; require_role(c, eid, ["organizer"], "export.json"); const e = getEvent(c, eid);
  log(c, "export.json", "full event dump", "ok", "", eid);
  return { format: "verdict.dump.v1", exported_at: nowIso(), event: e, tracks: c.db.tracks.filter((t) => t.event_id === eid), criteria: c.db.criteria.filter((x) => x.event_id === eid), teams: c.db.teams.filter((t) => t.event_id === eid), submissions: c.db.subs.filter((s) => s.event_id === eid), assignments: c.db.assigns.filter((a) => a.event_id === eid), scores: c.db.scores.filter((s) => c.db.subs.some((x) => x.id === s.submission_id && x.event_id === eid)) };
});
route("POST", "/events/{event_id}/import", (c) => {
  const eid = c.params.event_id; require_role(c, eid, ["organizer"], "import.json"); const d = c.body;
  if (!d || d.format !== "verdict.dump.v1") throw bad("Not a Verdict dump (expected format verdict.dump.v1)");
  const up = <T extends { id: string }>(arr: T[], items: T[] = []) => { items.forEach((it) => { const i = arr.findIndex((x) => x.id === it.id); if (i >= 0) arr[i] = it; else arr.push(it); }); return items.length; };
  const n = { tracks: up(c.db.tracks, d.tracks), criteria: up(c.db.criteria, d.criteria), teams: up(c.db.teams as any, d.teams), submissions: up(c.db.subs, d.submissions) };
  log(c, "import.json", `${n.submissions} submissions`, "ok", "", eid); return { imported: n };
});
route("GET", "/embed/{event_id}/gallery", (c) => { const e = getEvent(c, c.params.event_id); return { event: { id: e.id, name: e.name }, items: c.db.subs.filter((s) => s.event_id === e.id && s.status === "submitted") }; });
route("POST", "/__mock/reset", () => { resetDb(); return { ok: true }; });

// ================= entry =================
export interface MockRes { status: number; data: any; text?: string; }
export async function mockFetch(method: string, path: string, opts: { body?: any; token?: string | null; query?: Record<string, string> } = {}): Promise<MockRes> {
  await sleep(90 + Math.random() * 160);
  const db = getDb();
  const userId = opts.token?.startsWith("mock.") ? opts.token.slice(5) : null;
  const user = userId ? db.users.find((u) => u.id === userId) ?? null : null;
  const q = new URLSearchParams(opts.query ?? {});
  for (const rt of routes) {
    if (rt.method !== method) continue;
    const m = rt.re.exec(path); if (!m) continue;
    const ctx: Ctx = { db, user, params: { ...(m.groups ?? {}) }, query: q, body: opts.body };
    try {
      const out = rt.h(ctx);
      if (method !== "GET") saveDb();
      if (out && typeof out === "object" && "__text" in out) return { status: 200, data: null, text: out.__text };
      return { status: 200, data: out };
    } catch (e) {
      if (e instanceof HttpError) { if (method !== "GET") saveDb(); return { status: e.status, data: { detail: e.detail } }; }
      throw e;
    }
  }
  return { status: 404, data: { detail: `No mock route for ${method} ${path}` } };
}
void mulberry;
