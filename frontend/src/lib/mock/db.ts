import { mulberry } from "../utils";
import type {
  User, EventT, Track, Submission, Criterion, Comment, AuditEntry, Webhook, EventRole,
} from "../types";

export interface DbUser extends User { password: string; }
export interface DbRole { event_id: string; user_id: string; role: EventRole["role"]; }
export interface DbTeam { id: string; event_id: string; name: string; invite_code: string; }
export interface DbMember { team_id: string; user_id: string; is_lead: boolean; }
export interface DbAssign { id: string; event_id: string; submission_id: string; judge_id: string; }
export interface DbScore { submission_id: string; judge_id: string; criterion_id: string; value: number; comment?: string; }
export interface DbVote { submission_id: string; fp: string; count: number; at: string; }
export interface DbDuel { event_id: string; judge_id: string; a: string; b: string; winner: string; }
export interface Db {
  v: number;
  duels: DbDuel[];
  users: DbUser[]; events: EventT[]; tracks: Track[]; roles: DbRole[];
  teams: DbTeam[]; members: DbMember[]; subs: Submission[]; criteria: Criterion[];
  assigns: DbAssign[]; scores: DbScore[]; votes: DbVote[]; voteBase: Record<string, number>;
  comments: Comment[]; audit: AuditEntry[]; webhooks: Webhook[];
  normalized: Record<string, string | null>;
}

const KEY = "verdict.mock.db";
const VERSION = 6;
export const DEMO_PASSWORD = "verdict";

export const DEMO_ACCOUNTS = [
  { id: "u_mira", label: "Participant", email: "mira@demo.dev", name: "Mira Okafor" },
  { id: "u_dev", label: "Judge", email: "judge@demo.dev", name: "Dev Anand" },
  { id: "u_ines", label: "Organizer", email: "organizer@demo.dev", name: "Ines Marquez" },
  { id: "u_root", label: "Admin", email: "admin@demo.dev", name: "Root Operator" },
];

export const uid = (p: string) => `${p}_${Math.random().toString(36).slice(2, 9)}`;
export const nowIso = () => new Date().toISOString();

let cache: Db | null = null;
export function getDb(): Db {
  if (cache) return cache;
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) { const parsed = JSON.parse(raw) as Db; if (parsed.v === VERSION) { cache = parsed; return cache; } }
  } catch { /* fall through */ }
  cache = seed(); saveDb(); return cache;
}
export function saveDb() { try { localStorage.setItem(KEY, JSON.stringify(cache)); } catch { /* quota */ } }
export function resetDb() { cache = seed(); saveDb(); return cache; }

// ---------------------------------------------------------------------------
const NAMES = ["Gavelbird","Plumbline","Ballast","Quorum","Scrutiny","Ledgerline","Ironbark","Nightjar","Cairn","Sextant","Tribune","Oystercourt","Tallyman","Brindle","Marrow","Kestrel","Lodestar","Foxglove","Palisade","Umbra","Wrenfield","Argent","Corvid","Halyard","Ossuary","Tessera","Vellum","Benchmark","Pillory","Redoubt","Lantern Court","Cinder","Mistral","Obol","Parley","Rookery","Sable","Thimble","Vigil","Wicker","Yarrow","Assay","Bellwether","Chancery","Dovetail","Errata","Fathom","Gnomon"];
const TAGLINES = ["Weighted rubrics, judged in the open.","Every score signed and auditable.","Judges never see each other. Ever.","Normalisation you can explain to a statistician.","One command. Seeded. Running.","Ballots that cannot be stuffed.","Pairwise duels, Bradley–Terry ranked.","Role isolation enforced below the UI.","A submission portal that respects deadlines.","Quadratic votes for a quieter crowd.","Self-hosted, exportable, leave any time.","Audit trails organisers can actually read."];
const TAGS = ["fastapi","postgres","nextjs","rust","go","sqlite","htmx","typescript","python","docker","svelte","redis","bradley-terry","z-score","openapi","webhooks"];
const TEAMS = ["Null Pointers","Off By One","Segfault Society","Dangling Refs","Rubber Ducks","Hot Reload","Cold Start","Tab Stops","Merge Conflict","Race Condition","Dead Letter","Heap Dump","Stack Trace","Yak Shavers","Bit Rot","Bare Metal","Idle Loop","Deep Copy","Soft Delete","Hard Fork","Green Build","Red Herring","Lazy Init","Zero Day"];
const FIRST = ["Aiko","Bruno","Chidi","Dalia","Emeka","Farah","Goran","Hana","Ilya","Jun","Kavya","Leon","Mateo","Noor","Omar","Petra","Quinn","Rosa","Sven","Tariq","Uma","Vera","Wei","Xavi","Yusuf","Zoe"];
const LAST = ["Abara","Brandt","Castillo","Dietrich","Esposito","Fofana","Grieg","Haddad","Ivanov","Jansen","Kobayashi","Lindqvist","Moreau","Nakamura","Oyelaran","Petrov","Quist","Rahman","Silva","Tanaka","Uddin","Volkov","Winter","Xu","Yilmaz","Zhang"];

export function seed(): Db {
  const r = mulberry(20260925);
  const pick = <T,>(a: T[]) => a[Math.floor(r() * a.length)];
  const now = Date.now();
  const H = 3600_000, D = 24 * H;
  const iso = (ms: number) => new Date(ms).toISOString();

  const users: DbUser[] = [
    { id: "u_mira", email: "mira@demo.dev", name: "Mira Okafor", is_admin: false, password: DEMO_PASSWORD },
    { id: "u_dev", email: "judge@demo.dev", name: "Dev Anand", is_admin: false, password: DEMO_PASSWORD },
    { id: "u_ines", email: "organizer@demo.dev", name: "Ines Marquez", is_admin: false, password: DEMO_PASSWORD },
    { id: "u_root", email: "admin@demo.dev", name: "Root Operator", is_admin: true, password: DEMO_PASSWORD },
  ];
  const judgeNames = ["Kenji Watanabe", "Priya Raman", "Tomasz Lewandowski", "Amara Diallo", "Lars Nilsson"];
  judgeNames.forEach((n, i) => users.push({ id: `u_j${i + 1}`, email: `j${i + 1}@demo.dev`, name: n, is_admin: false, password: DEMO_PASSWORD }));
  for (let i = 0; i < 48; i++) {
    const n = `${FIRST[i % FIRST.length]} ${LAST[(i * 7 + 3) % LAST.length]}`;
    users.push({ id: `u_p${i}`, email: `p${i}@demo.dev`, name: n, is_admin: false, password: DEMO_PASSWORD });
  }
  const judgeIds = ["u_dev", "u_j1", "u_j2", "u_j3", "u_j4", "u_j5"];

  const events: EventT[] = [
    {
      id: "evt_dogfood", name: "Dogfood 2026", tagline: "Build the platform that will judge you.",
      description: "Seventy-two hours. One product. Every team builds the same submission-and-judging portal against a published spec and a shared acceptance suite. The winner is the one we run.\n\nNo cloud accounts, no hosted services. If it does not come up with one command on a laptop with the network off, it does not count.",
      status: "open", starts_at: iso(now - 30 * H), deadline_at: iso(now + 2 * D + 4 * H + 17 * 60_000),
      voting_opens_at: null, voting_closes_at: null, voting_mode: "auth", team_size_max: 4,
      prizes: [{ place: "1st", name: "Grand Prize", amount: 800 }, { place: "2nd", name: "Runner-Up", amount: 500 }, { place: "3rd", name: "Third Place", amount: 350 }, { place: "★", name: "Best Judging Engine", amount: 100 }],
      custom_questions: [{ id: "cq1", label: "Which tier did you reach — and what is the honest gap?", required: true }, { id: "cq2", label: "What would you redo with 24 more hours?", required: false }],
    },
    {
      id: "evt_portmortem", name: "Port Mortem 2026", tagline: "Resurrect the dead side-project. Ship it properly.",
      description: "A hackathon about finishing things. Bring the repo you abandoned; leave with something you would put your name on.",
      status: "judging", starts_at: iso(now - 9 * D), deadline_at: iso(now - 5 * D),
      voting_opens_at: null, voting_closes_at: null, voting_mode: "open", team_size_max: 3,
      prizes: [{ place: "1st", name: "Grand Prize", amount: 600 }, { place: "2nd", name: "Runner-Up", amount: 300 }, { place: "3rd", name: "Third Place", amount: 150 }],
      custom_questions: [],
    },
    {
      id: "evt_slopscan", name: "Slop Scan 2026", tagline: "Detect it. Prove it. Show your working.",
      description: "Build the tool that tells human-written software from generated slop — and defend your false-positive rate in public.",
      status: "voting", starts_at: iso(now - 12 * D), deadline_at: iso(now - 6 * D),
      voting_opens_at: iso(now - 1 * D), voting_closes_at: iso(now + 2 * D), voting_mode: "quadratic", team_size_max: 4,
      prizes: [{ place: "1st", name: "Grand Prize", amount: 500 }, { place: "★", name: "Community Pick", amount: 150 }],
      custom_questions: [],
    },
    {
      id: "evt_zerodep", name: "Zero Dependency 2026", tagline: "Standard library only. Nothing to install.",
      description: "Four days, one rule: no third-party packages. The winners are the teams that discovered how much the standard library already does.",
      status: "published", starts_at: iso(now - 40 * D), deadline_at: iso(now - 36 * D),
      voting_opens_at: null, voting_closes_at: null, voting_mode: "open", team_size_max: 4,
      prizes: [{ place: "1st", name: "Grand Prize", amount: 700 }, { place: "2nd", name: "Runner-Up", amount: 350 }, { place: "3rd", name: "Third Place", amount: 200 }],
      custom_questions: [],
    },
  ];

  const trackDefs: Record<string, [string, string][]> = {
    evt_dogfood: [["Full-Stack", "Whole product, end to end."], ["Backend & API", "Isolation, assignment, exports."], ["Judging Engine", "Normalisation & pairwise."]],
    evt_portmortem: [["Revival", "Resurrected projects."], ["Rewrite", "Same idea, better foundations."]],
    evt_slopscan: [["Detection", "Classifiers and heuristics."], ["Provenance", "Signing and attestation."], ["UX", "Explaining a verdict to humans."]],
    evt_zerodep: [["Tools", "CLIs and utilities."], ["Servers", "Network and web."], ["Games", "Just for the joy of it."]],
  };
  const tracks: Track[] = [];
  Object.entries(trackDefs).forEach(([eid, t]) => t.forEach(([name, description], i) => tracks.push({ id: `trk_${eid}_${i}`, event_id: eid, name, description })));

  const criteriaDefs: [string, string, number][] = [
    ["Tier Completion & Correctness", "How far up the ladder — verified by the acceptance suite, not the README.", 40],
    ["Judging Integrity", "Role isolation, normalisation, audit trail, abuse resistance.", 25],
    ["Adoptability & Operability", "One command to running. Docs a stranger can follow.", 20],
    ["Code Quality & Innovation", "Idiomatic code, a defensible schema, one decision worth stealing.", 15],
  ];
  const criteria: Criterion[] = [];
  events.forEach((e) => criteriaDefs.forEach(([name, description, weight], i) => criteria.push({ id: `crit_${e.id}_${i}`, event_id: e.id, name, description, weight, max_score: 5 })));

  const roles: DbRole[] = [];
  const teams: DbTeam[] = []; const members: DbMember[] = []; const subs: Submission[] = [];
  const assigns: DbAssign[] = []; const scores: DbScore[] = []; const voteBase: Record<string, number> = {};
  events.forEach((e) => {
    roles.push({ event_id: e.id, user_id: "u_ines", role: "organizer" });
    roles.push({ event_id: e.id, user_id: "u_dev", role: "judge" });
    ["u_j1", "u_j2", "u_j3", "u_j4", "u_j5"].forEach((j) => { if (e.id === "evt_portmortem" || e.id === "evt_zerodep") roles.push({ event_id: e.id, user_id: j, role: "judge" }); });
  });

  const desc = (name: string) =>
    `${name} is a self-hostable judging portal built around one idea: the API is the product and the UI is a client.\n\nScores are captured per-criterion, weighted by the organiser's rubric, and normalised across judges so a harsh reviewer and a generous one land in the same place. Every mutation writes to an audit log that reads like a sentence, not a stack trace.\n\nWhat works: auth, roles, event lifecycle, drafts with hard deadlines, assignment, scoring, exports.\nWhat does not yet: signed judge records and the embeddable widget — we started them and cut them.`;

  let p = 0;
  const build = (eid: string, nSubmitted: number, nDraft: number) => {
    const trs = tracks.filter((t) => t.event_id === eid);
    const ev = events.find((e) => e.id === eid)!;
    const total = nSubmitted + nDraft;
    for (let i = 0; i < total; i++) {
      const teamId = `team_${eid}_${i}`;
      const tn = TEAMS[(i * 5 + eid.length) % TEAMS.length] + (i >= TEAMS.length ? " II" : "");
      teams.push({ id: teamId, event_id: eid, name: tn, invite_code: `${tn.split(" ")[0].slice(0, 3).toUpperCase()}${Math.floor(r() * 9000 + 1000)}` });
      const size = 1 + Math.floor(r() * Math.min(3, ev.team_size_max));
      for (let m = 0; m < size; m++) {
        const uid_ = `u_p${(p++) % 48}`;
        members.push({ team_id: teamId, user_id: uid_, is_lead: m === 0 });
        roles.push({ event_id: eid, user_id: uid_, role: "participant" });
      }
      const name = NAMES[(i * 5 + eid.length * 7) % NAMES.length];
      const tr = trs[i % trs.length];
      const tags = [pick(TAGS), pick(TAGS), pick(TAGS)].filter((v, k, a) => a.indexOf(v) === k);
      const submitted = i < nSubmitted;
      const t0 = ev.deadline_at ? new Date(ev.deadline_at).getTime() : now;
      subs.push({
        id: `sub_${eid}_${i}`, event_id: eid, team_id: teamId, team_name: tn,
        track_id: tr.id, track_name: tr.name, name, tagline: pick(TAGLINES), description: desc(name),
        thumbnail_url: null, images: [], video_url: `https://video.example.dev/${name.toLowerCase()}`,
        repo_url: `https://github.com/${tn.toLowerCase().replace(/\s+/g, "-")}/${name.toLowerCase().replace(/\s+/g, "-")}`,
        live_url: r() > 0.5 ? `https://${name.toLowerCase().replace(/\s+/g, "")}.example.dev` : "",
        tags, custom_answers: eid === "evt_dogfood" ? { cq1: "Reached T2 cleanly; T3 voting is half-built.", cq2: "Redo the schema for audit events." } : {},
        status: submitted ? "submitted" : "draft", submitted_at: submitted ? iso(t0 - Math.floor(r() * 20) * H) : null,
        updated_at: iso(now - Math.floor(r() * 30) * 3600_000),
      });
      if (eid === "evt_slopscan") voteBase[`sub_${eid}_${i}`] = 12 + Math.floor(r() * 230);
    }
  };
  build("evt_dogfood", 9, 3);
  build("evt_portmortem", 18, 0);
  build("evt_slopscan", 10, 0);
  build("evt_zerodep", 14, 0);

  // Mira leads a team in the open event with a half-finished draft, and appears in a past event.
  const miraTeam = "team_evt_dogfood_9";
  const mt = teams.find((t) => t.id === miraTeam)!; mt.name = "Null Pointers"; mt.invite_code = "NULL4242";
  members.splice(0, members.length, ...members.filter((m) => m.team_id !== miraTeam));
  members.push({ team_id: miraTeam, user_id: "u_mira", is_lead: true }, { team_id: miraTeam, user_id: "u_p3", is_lead: false });
  roles.push({ event_id: "evt_dogfood", user_id: "u_mira", role: "participant" });
  const ms = subs.find((s) => s.team_id === miraTeam)!;
  ms.team_name = "Null Pointers"; ms.name = "Plumbline"; ms.tagline = "Weighted rubrics, judged in the open."; ms.description = "Work in progress — auth, roles, and event lifecycle are done. Judging next.";
  ms.repo_url = ""; ms.live_url = ""; ms.video_url = ""; ms.tags = ["fastapi", "nextjs"]; ms.custom_answers = {};
  const zt = teams.find((t) => t.event_id === "evt_zerodep")!;
  members.push({ team_id: zt.id, user_id: "u_mira", is_lead: false });
  roles.push({ event_id: "evt_zerodep", user_id: "u_mira", role: "participant" });

  // --- assignments + scores (biased judges so normalisation has something to fix)
  const judgeModel: Record<string, { bias: number; scale: number }> = {
    u_dev: { bias: 0, scale: 1 }, u_j1: { bias: -0.9, scale: 1 }, u_j2: { bias: 0.9, scale: 0.85 },
    u_j3: { bias: 0, scale: 0.25 }, u_j4: { bias: -0.3, scale: 1.5 }, u_j5: { bias: 0.5, scale: 1 },
  };
  const latent: Record<string, number> = {};
  const assignFor = (eid: string, fillRate: number) => {
    const es = subs.filter((s) => s.event_id === eid && s.status === "submitted");
    const crits = criteria.filter((c) => c.event_id === eid);
    let devCount = 0;
    es.forEach((s, idx) => {
      latent[s.id] = 2 + r() * 2.7;
      for (let k = 0; k < 3; k++) {
        const j = judgeIds[(idx * 3 + k) % 6];
        assigns.push({ id: `as_${s.id}_${j}`, event_id: eid, submission_id: s.id, judge_id: j });
        const m = judgeModel[j];
        let willScore = r() < fillRate;
        let partial = false;
        if (eid === "evt_portmortem" && j === "u_dev") { devCount++; willScore = devCount <= 4; partial = devCount === 5; if (partial) willScore = true; }
        if (!willScore) continue;
        const base = 3 + (latent[s.id] - 3) * m.scale + m.bias + (r() - 0.5) * 0.6;
        crits.forEach((c, ci) => {
          if (partial && ci >= 2) return;
          const v = Math.round(Math.max(1, Math.min(5, base + (r() - 0.5) * 1.6)));
          scores.push({ submission_id: s.id, judge_id: j, criterion_id: c.id, value: v });
        });
      }
    });
  };
  assignFor("evt_portmortem", 0.6);
  assignFor("evt_zerodep", 1);

  // seeded pairwise duels (Port Mortem) — judges other than Dev, outcomes follow latent quality
  const duels: DbDuel[] = [];
  ["u_j1", "u_j2", "u_j3", "u_j4", "u_j5"].forEach((j) => {
    const mine = assigns.filter((a) => a.event_id === "evt_portmortem" && a.judge_id === j).map((a) => a.submission_id);
    for (let n = 0; n < 12; n++) {
      const a = mine[Math.floor(r() * mine.length)], b = mine[Math.floor(r() * mine.length)]; if (a === b) continue;
      const pa = 1 / (1 + Math.exp(-(latent[a] - latent[b]) * 1.4));
      duels.push({ event_id: "evt_portmortem", judge_id: j, a, b, winner: r() < pa ? a : b });
    }
  });

  const normalized: Record<string, string | null> = { evt_dogfood: null, evt_portmortem: null, evt_slopscan: null, evt_zerodep: iso(now - 35 * D) };

  const comments: Comment[] = [];
  const cm = ["Role isolation held up when I curl'd another judge's scores — nice.", "The audit trail reads like a diary. I mean that as a compliment.", "Would love to see the normalisation maths in JUDGING.md.", "One command really did bring it up. Rare.", "Quadratic credits UI is clever. Took me a minute."];
  subs.filter((s) => s.status === "submitted" && (s.event_id === "evt_slopscan" || s.event_id === "evt_zerodep")).slice(0, 14).forEach((s, i) => {
    const u = users[8 + (i % 20)];
    comments.push({ id: `cm_${i}`, submission_id: s.id, user_id: u.id, user_name: u.name, body: cm[i % cm.length], created_at: iso(now - (i + 1) * 5 * H) });
  });

  const audit: AuditEntry[] = [];
  const evName = (eid: string) => events.find((e) => e.id === eid)!.name;
  const subOf = (eid: string) => { const l = subs.filter((x) => x.event_id === eid && x.status === "submitted"); return l[Math.floor(r() * l.length)]; };
  type Tpl = { role: "organizer" | "admin" | "judge" | "participant"; action: string; denied?: boolean; target: (eid: string) => string; detail?: string };
  const tpls: Tpl[] = [
    { role: "organizer", action: "event.update", target: evName },
    { role: "organizer", action: "rubric.criterion.create", target: () => "Judging Integrity (weight 25)" },
    { role: "organizer", action: "role.grant", target: () => `${judgeNames[Math.floor(r() * judgeNames.length)]} → judge` },
    { role: "organizer", action: "judging.assign", target: () => "round_robin × 3 reviews" },
    { role: "organizer", action: "judging.normalize", target: () => "per-judge z-score" },
    { role: "organizer", action: "export.csv", target: evName },
    { role: "admin", action: "event.status", target: (e) => `${evName(e)}: open → judging` },
    { role: "judge", action: "score.upsert", target: (e) => subOf(e)?.name ?? "a project" },
    { role: "judge", action: "score.upsert", target: (e) => subOf(e)?.name ?? "a project" },
    { role: "judge", action: "auth.login", target: () => "session" },
    { role: "participant", action: "submission.submit", target: (e) => subOf(e)?.name ?? "a project" },
    { role: "participant", action: "team.create", target: () => "a new team" },
    { role: "participant", action: "vote.cast", target: (e) => subOf(e)?.name ?? "a project" },
    { role: "judge", action: "scores.read", denied: true, target: (e) => `another judge's scores on ${subOf(e)?.name ?? "a project"}`, detail: "403 — a judge may only read their own scores" },
    { role: "judge", action: "rubric.configure", denied: true, target: evName, detail: "403 — rubric configuration is organiser-only" },
    { role: "participant", action: "results.read", denied: true, target: (e) => `${evName(e)} (sealed)`, detail: "403 — results are sealed until published" },
    { role: "participant", action: "audit.read", denied: true, target: () => "the audit log", detail: "403 — organiser/admin only" },
  ];
  for (let i = 0; i < 46; i++) {
    const t = tpls[Math.floor(r() * tpls.length)];
    const actorId = t.role === "organizer" ? "u_ines" : t.role === "admin" ? "u_root" : t.role === "judge" ? judgeIds[Math.floor(r() * judgeIds.length)] : `u_p${Math.floor(r() * 48)}`;
    const u = users.find((x) => x.id === actorId)!;
    const eid = t.action === "vote.cast" ? "evt_slopscan" : t.action === "score.upsert" || t.action === "scores.read" ? (r() > 0.5 ? "evt_portmortem" : "evt_zerodep") : events[Math.floor(r() * 4)].id;
    audit.push({
      id: `au_${i}`, at: iso(now - i * 47 * 60_000 - Math.floor(r() * 20) * 60_000), actor_id: u.id, actor_name: u.name, actor_role: t.role,
      action: t.action, target: t.target(eid), outcome: t.denied ? "denied" : "ok", detail: t.detail ?? "", ip: `10.0.${Math.floor(r() * 9)}.${Math.floor(r() * 250)}`, event_id: eid,
    });
  }

  const webhooks: Webhook[] = [{ id: "wh_1", url: "https://hooks.example.dev/verdict", event_types: ["submission.submitted", "results.published"], active: true, created_at: iso(now - 3 * D) }];

  return { v: VERSION, duels, users, events, tracks, roles, teams, members, subs, criteria, assigns, scores, votes: [], voteBase, comments, audit, webhooks, normalized };
}

