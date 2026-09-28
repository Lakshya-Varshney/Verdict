"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Gauge, GitCompareArrows, Vote, ScrollText, Webhook, Scale, Terminal, ShieldCheck } from "lucide-react";
import { api, USE_MOCK } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { DEMO_PASSWORD } from "@/lib/mock/db";
import { MATRIX } from "@/lib/nav";
import { BRAND } from "@/lib/brand";
import { Countdown, FlapCycle, SplitFlap } from "@/components/SplitFlap";
import { NormDemo } from "@/components/NormDemo";
import { SectionLabel } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { EventT } from "@/lib/types";

const STAGES: { name: string; blurb: string; hot?: boolean }[] = [
  { name: "Registration", blurb: "Accounts, sessions, and a real role model — visitor, participant, judge, organizer, admin — scoped per event." },
  { name: "Teams", blurb: "Invite links with a code. Team size limits enforced server-side, one team per person per event." },
  { name: "Submissions", blurb: "Drafts that autosave, a hard deadline that holds even if you leave the tab open, and a checklist before you submit." },
  { name: "Eligibility", blurb: "Required fields, custom organiser questions, track selection — checked at the API, not just in the form." },
  { name: "Assignment", blurb: "Round-robin or load-balanced. Judges only ever see their own batch." },
  { name: "Scoring", blurb: "A weighted rubric, keyboard-first scoring, and autosave on every key press. Thirty projects should not take five hours." },
  { name: "Normalisation", blurb: "The stage every platform advertises and none documents. Per-judge z-score, shown side by side with the raw ranking.", hot: true },
  { name: "Results", blurb: "Sealed until the organiser publishes. Then a public board with rank movement and no judge names." },
  { name: "Certificates", blurb: "Participant, judge and winner certificates with a verifiable hash. Print-ready." },
  { name: "Archive", blurb: "Full JSON export and import. A platform you cannot leave is a trap." },
];
const FEATURES = [
  { icon: Scale, t: "Weighted rubrics", d: "Organiser-defined criteria with live-normalised weights. No shared, fixed five-criterion rubric." },
  { icon: Gauge, t: "Cross-judge normalisation", d: "Per-judge z-score with a raw-vs-normalised proof panel: rank shifts, bias bars, spread before and after." },
  { icon: GitCompareArrows, t: "Pairwise duels", d: "Show a judge two projects. Which is better? A Bradley–Terry ranking falls out — no absolute scores needed." },
  { icon: Vote, t: "Quadratic voting", d: "Credits, not clicks. n votes cost n². Results hidden during the window; ballots shuffled to kill position bias." },
  { icon: ScrollText, t: "An audit trail you can read", d: "Every mutation, every denial, written as a sentence. Filter by actor, action, outcome." },
  { icon: Webhook, t: "API-first, exportable", d: "Everything the UI does is in the OpenAPI spec. Webhooks, embeds, full JSON dump." },
];

export default function Landing() {
  const events = useQuery({ queryKey: ["events"], queryFn: () => api.events.list() });
  const router = useRouter(); const { login } = useAuth();
  const [stage, setStage] = useState(6);
  const list = events.data?.items ?? [];
  const featured = list.find((e) => e.status === "open") ?? list[0];

  const enter = async (email: string, to: string) => { await login(email, DEMO_PASSWORD); router.push(to); };

  return (
    <div className="-mt-4 space-y-28">
      {/* ------------------------------------------------ HERO */}
      <section className="grid grid-cols-1 items-center gap-12 pt-4 lg:grid-cols-[1.15fr_1fr] [&>*]:min-w-0">
        <div>
          <div className="label fade-up mb-6 flex items-center gap-3"><span className="pulse-dot ok" /> Open source · self-hostable · API-first</div>
          <h1 className="display fade-up text-[clamp(3.6rem,9.4vw,8.6rem)]" style={{ ["--i" as string]: 1 } as React.CSSProperties}>Every score.<br /><em>On the record.</em></h1>
          <p className="fade-up mt-8 max-w-xl text-[17px] leading-relaxed text-ink2" style={{ ["--i" as string]: 3 } as React.CSSProperties}>
            {BRAND.name} runs the whole hackathon pipeline — registration to archive — with weighted rubrics, cross-judge normalisation, quadratic voting, and an audit log an organiser can read without a database client.
          </p>
          <div className="fade-up mt-9 flex flex-wrap items-center gap-3" style={{ ["--i" as string]: 4 } as React.CSSProperties}>
            <Link href="/events" className="btn btn-primary">Explore live events <ArrowRight size={14} /></Link>
            <Link href="/signup" className="btn">Create an account</Link>
          </div>
          {USE_MOCK && (
            <div className="fade-up mt-10 flex flex-wrap items-center gap-2" style={{ ["--i" as string]: 5 } as React.CSSProperties}>
              <span className="label mr-2">Enter the demo as</span>
              <button className="chip hover:!text-ink" onClick={() => enter("mira@demo.dev", "/events/evt_dogfood/submit")}>participant</button>
              <button className="chip hover:!text-ink" onClick={() => enter("judge@demo.dev", "/events/evt_portmortem/judge")}>judge</button>
              <button className="chip hover:!text-ink" onClick={() => enter("organizer@demo.dev", "/events/evt_portmortem/results")}>organizer</button>
              <button className="chip hover:!text-ink" onClick={() => enter("admin@demo.dev", "/admin/audit")}>admin</button>
            </div>
          )}
        </div>

        {/* departures board */}
        <div className="fade-up relative" style={{ ["--i" as string]: 2 } as React.CSSProperties}>
          <div className="absolute -inset-6 -z-10 hidden opacity-60 blur-3xl sm:block" style={{ background: "radial-gradient(closest-side, color-mix(in srgb, var(--amber) 26%, transparent), transparent)" }} />
          <div className="panel ticks crt overflow-hidden" style={{ background: "#0c0a07", borderColor: "#2b271e" }}>
            <div className="flex items-center justify-between border-b px-5 py-3" style={{ borderColor: "#2b271e" }}>
              <span className="label !text-[#b9b19c]">Live board</span><span className="flex items-center gap-2 label !text-[#b9b19c]"><span className="pulse-dot ok" /> Now</span>
            </div>
            <div className="space-y-3 px-5 py-5">
              <div className="mono grid grid-cols-[1fr_auto] gap-4 text-[9px] uppercase tracking-[0.2em] text-[#7f7868]"><span>Event</span><span className="w-[6.4rem]">Status</span></div>
              {(list.length ? list.slice(0, 4) : ([undefined, undefined, undefined, undefined] as (EventT | undefined)[])).map((e, i) => (
                <div key={i} className="flex items-center justify-between gap-3">
                  {e ? <><SplitFlap text={e.name.replace(/ 20\d\d/, "")} pad={15} size={1.22} color="ivory" stagger={35} /><SplitFlap text={e.status} pad={9} size={1.22} color={e.status === "open" ? "ok" : e.status === "voting" ? "cool" : e.status === "published" ? "signal" : "amber"} stagger={35} /></> : <div className="skeleton h-9 w-full" />}
                </div>
              ))}
            </div>
            <div className="border-t px-5 py-5" style={{ borderColor: "#2b271e" }}>
              <div className="label mb-3 !text-[#b9b19c]">{featured ? `${featured.name} · submissions close in` : "Next deadline"}</div>
              <Countdown to={featured?.deadline_at} size={2.3} />
            </div>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------ FACTS STRIP */}
      <section className="grid grid-cols-2 gap-px border border-line bg-line md:grid-cols-4">
        {[["10", "pipeline stages"], ["05", "roles, per event"], ["04", "tiers, T1 → T4"], ["00", "third-party requests"]].map(([n, l], i) => (
          <div key={l} className="fade-up bg-bg2 p-6" style={{ ["--i" as string]: i } as React.CSSProperties}><div className="cond text-[4.6rem] text-amberink">{n}</div><div className="label mt-1">{l}</div></div>
        ))}
      </section>

      {/* ------------------------------------------------ PIPELINE */}
      <section id="pipeline" className="scroll-mt-24">
        <SectionLabel n="01">The pipeline</SectionLabel>
        <div className="mb-8 grid gap-6 lg:grid-cols-[1fr_1fr]">
          <h2 className="display text-[clamp(2.6rem,5vw,4.4rem)]">Running a hackathon is a data problem wearing a <em>party hat.</em></h2>
          <p className="self-end text-ink2">Ten stages, each with its own state, each feeding the next. Get one wrong and the part that suffers is the judging — the part participants actually came for. Pick a stage.</p>
        </div>
        <div className="grid grid-cols-2 gap-px border border-line bg-line sm:grid-cols-5 lg:grid-cols-10">
          {STAGES.map((s, i) => (
            <button key={s.name} onMouseEnter={() => setStage(i)} onFocus={() => setStage(i)} onClick={() => setStage(i)} className={cn("group relative flex min-h-[112px] flex-col justify-between bg-bg2 p-3.5 text-left transition-colors", stage === i && "!bg-[color-mix(in_srgb,var(--amber)_9%,var(--bg2))]")}>
              <span className={cn("cond text-3xl transition-colors", stage === i ? (s.hot ? "signal" : "amber") : "text-ink3")}>{String(i + 1).padStart(2, "0")}</span>
              <span className="text-[12.5px] leading-tight">{s.name}</span>
              {stage === i && <i className="absolute inset-x-0 bottom-0 h-[3px]" style={{ background: s.hot ? "var(--signal)" : "var(--amber)", boxShadow: `0 0 16px ${s.hot ? "var(--signal)" : "var(--amber)"}` }} />}
            </button>
          ))}
        </div>
        <div className="panel mt-px flex flex-wrap items-center gap-x-8 gap-y-3 border-t-0 px-6 py-5">
          <SplitFlap text={String(stage + 1).padStart(2, "0")} size={2.2} color={STAGES[stage].hot ? "signal" : "amber"} framed scramble stagger={0} />
          <div className="min-w-[240px] flex-1"><div className="display text-3xl">{STAGES[stage].name}{STAGES[stage].hot && <span className="chip chip-signal ml-3 align-middle">breaks first</span>}</div><p className="mt-1 max-w-2xl text-[14px] text-ink2">{STAGES[stage].blurb}</p></div>
        </div>
      </section>

      {/* ------------------------------------------------ NORMALISATION */}
      <section>
        <SectionLabel n="02">The hard part</SectionLabel>
        <div className="grid items-start gap-8 lg:grid-cols-[.8fr_1.2fr]">
          <div>
            <h2 className="display text-[clamp(2.6rem,5vw,4.2rem)]">Advertised everywhere. <em>Documented nowhere.</em></h2>
            <p className="mt-5 text-ink2">Every commercial platform claims score normalisation and none will say how it works. Here it is on a whiteboard: re-centre each judge on their own mean, re-scale to their own spread, average. Then show the organiser the before and after.</p>
            <ul className="mt-6 space-y-3 text-[14px] text-ink2">
              {["Rank-shift lens: raw vs normalised, project by project", "Judge bias bars: who marks harsh, who marks generous", "Spread before & after — the σ that shrinks"].map((t) => <li key={t} className="flex gap-3"><ShieldCheck size={16} className="mt-0.5 shrink-0 text-amberink" />{t}</li>)}
            </ul>
          </div>
          <NormDemo />
        </div>
      </section>

      {/* ------------------------------------------------ ROLES */}
      <section id="roles" className="scroll-mt-24">
        <SectionLabel n="03">Role isolation</SectionLabel>
        <div className="mb-8 grid gap-6 lg:grid-cols-2">
          <h2 className="display text-[clamp(2.6rem,5vw,4.2rem)]">If I can <em>curl</em> another judge&apos;s scores, it isn&apos;t isolation.</h2>
          <p className="self-end text-ink2">One reusable guard, used by every route. The UI hides what you can&apos;t do, but the API is the wall. Roles are per event — the same person can judge one and compete in another.</p>
        </div>
        <div className="grid gap-6 lg:grid-cols-[1.75fr_1fr]">
          <div className="panel overflow-x-auto">
            <table className="tbl min-w-[600px]">
              <thead><tr><th>Action</th>{["visitor", "participant", "judge", "organizer", "admin"].map((r) => <th key={r}>{r}</th>)}</tr></thead>
              <tbody>{MATRIX.map((m) => (
                <tr key={m.action}><td className="text-[13.5px]">{m.action}</td>
                  {(["visitor", "participant", "judge", "organizer", "admin"] as const).map((r) => { const v = m[r]; return <td key={r} className="mono text-[11px]">{v === true ? <span className="text-ok">●</span> : v === false ? <span className="text-ink3">—</span> : <span className="chip chip-amber">{v}</span>}</td>; })}</tr>
              ))}</tbody>
            </table>
          </div>
          <div className="panel crt overflow-hidden" style={{ background: "#0c0a07", borderColor: "#2b271e" }}>
            <div className="flex items-center gap-2 border-b px-4 py-2.5" style={{ borderColor: "#2b271e" }}><Terminal size={13} className="text-[#7f7868]" /><span className="label !text-[#7f7868]">judge · curl</span></div>
            <pre className="mono overflow-x-auto p-5 text-[11.5px] leading-[1.75] text-[#b9b19c]">
{`$ curl -H "Authorization: Bearer $JUDGE" \\
    /api/submissions/sub_9/scores

`}<span className="text-[#ff5a2b]">HTTP/1.1 403 Forbidden</span>{`
{
  "detail": "Role 'judge' may not scores.read"
}

$ tail audit.log
`}<span className="text-[#ffb81c]">14:02:11 DENIED</span>{` Dev Anand (judge)
  scores.read — denied at the API,
  not in the UI`}<span className="blink text-[#ffb81c]">▍</span>
            </pre>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------ FEATURES */}
      <section>
        <SectionLabel n="04">In the box</SectionLabel>
        <div className="grid gap-px border border-line bg-line sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map((f, i) => (
            <div key={f.t} className="fade-up group relative bg-bg2 p-7 transition-colors hover:bg-panel" style={{ ["--i" as string]: i } as React.CSSProperties}>
              <div className="mb-8 grid h-11 w-11 place-items-center border border-line2 text-amberink transition-colors group-hover:border-amber group-hover:bg-amber group-hover:text-[var(--on-amber)]"><f.icon size={19} /></div>
              <h3 className="display text-[2rem]">{f.t}</h3><p className="mt-2 text-[14px] text-ink2">{f.d}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ------------------------------------------------ CTA */}
      <section className="panel ticks relative overflow-hidden p-8 sm:p-14">
        <div className="pointer-events-none absolute -right-20 -top-24 opacity-50"><FlapCycle words={["SUBMIT", "JUDGE", "VERIFY", "PUBLISH"]} size={5.5} color="amber" /></div>
        <div className="label mb-5">One command</div>
        <h2 className="display max-w-3xl text-[clamp(2.8rem,6vw,5.4rem)]">Run it on Monday. <em>Leave</em> any time.</h2>
        <p className="mt-5 max-w-xl text-ink2">No cloud account, no hosted database, no auth-as-a-service. If it does not come up on a laptop with the network off, it does not ship.</p>
        <div className="mt-8 flex flex-wrap items-center gap-4">
          <code className="mono border border-line2 bg-bg px-5 py-3.5 text-[13px]"><span className="text-amberink">$</span> docker compose up</code>
          <Link href="/events" className="btn btn-primary">Open the demo <ArrowRight size={14} /></Link>
        </div>
      </section>
    </div>
  );
}
