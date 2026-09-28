"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, ExternalLink, GitBranch, Globe, Lock } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { Gate, useEventCtx } from "@/components/EventContext";
import { SplitFlap } from "@/components/SplitFlap";
import { Cover } from "@/components/Cover";
import { ErrorState, Kbd, LoadingBlock } from "@/components/ui";
import { useToast } from "@/components/toast";
import { cn, safeHref } from "@/lib/utils";

const LABELS = ["Broken", "Weak", "Solid", "Strong", "Exceptional"];

export default function ScorePage() { return <Gate allow={["judge"]} what="Only assigned judges can score."><Inner /></Gate>; }

function Inner() {
  const { event: e } = useEventCtx(); const { sid } = useParams<{ sid: string }>(); const router = useRouter(); const qc = useQueryClient(); const toast = useToast();
  const sub = useQuery({ queryKey: ["sub-view", sid], queryFn: () => api.subs.get(sid) });
  const crit = useQuery({ queryKey: ["criteria", e.id], queryFn: () => api.judging.criteria(e.id) });
  const mine = useQuery({ queryKey: ["myscores", sid], queryFn: () => api.judging.myScores(sid) });
  const queue = useQuery({ queryKey: ["assign-mine", e.id], queryFn: () => api.judging.mine(e.id) });
  const [vals, setVals] = useState<Record<string, number>>({}); const [active, setActive] = useState(0); const [saving, setSaving] = useState<string | null>(null); const [err, setErr] = useState<string | null>(null);
  const seeded = useRef<string | null>(null);
  useEffect(() => { if (mine.data && seeded.current !== sid) { seeded.current = sid; setVals(Object.fromEntries(mine.data.scores.map((s) => [s.criterion_id, s.value]))); setActive(0); } }, [mine.data, sid]);

  const list = queue.data ?? []; const idx = list.findIndex((a) => a.submission_id === sid); const prev = list[idx - 1]; const next = list[idx + 1];
  const criteria = crit.data ?? []; const locked = e.status !== "judging";
  const wsum = criteria.reduce((a, c) => a + c.weight, 0) || 1;
  const answered = criteria.filter((c) => vals[c.id]).length; const complete = criteria.length > 0 && answered === criteria.length;
  const total = useMemo(() => (answered ? criteria.reduce((a, c) => a + (vals[c.id] ?? 0) * c.weight, 0) / criteria.filter((c) => vals[c.id]).reduce((a, c) => a + c.weight, 0) : 0), [vals, criteria, answered]);

  const setScore = useCallback(async (cid: string, v: number) => {
    if (locked) return; setVals((x) => ({ ...x, [cid]: v })); setSaving(cid); setErr(null);
    try { await api.judging.score(sid, { criterion_id: cid, value: v }); qc.invalidateQueries({ queryKey: ["assign-mine", e.id] }); }
    catch (x) { setErr(x instanceof ApiError ? x.detail : "Save failed"); toast(x instanceof ApiError ? x.detail : "Save failed", "error"); }
    setSaving(null);
  }, [locked, sid, qc, e.id, toast]);

  useEffect(() => {
    const f = (ev: KeyboardEvent) => {
      const t = ev.target as HTMLElement; if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
      if (/^[1-5]$/.test(ev.key) && criteria[active]) { setScore(criteria[active].id, +ev.key); if (active < criteria.length - 1) setTimeout(() => setActive((a) => Math.min(criteria.length - 1, a + 1)), 160); }
      if (ev.key === "ArrowDown" || ev.key === "j") { ev.preventDefault(); setActive((a) => Math.min(criteria.length - 1, a + 1)); }
      if (ev.key === "ArrowUp" || ev.key === "k") { ev.preventDefault(); setActive((a) => Math.max(0, a - 1)); }
      if (ev.key === "ArrowRight" && next) router.push(`/events/${e.id}/judge/${next.submission_id}`);
      if (ev.key === "ArrowLeft" && prev) router.push(`/events/${e.id}/judge/${prev.submission_id}`);
    };
    window.addEventListener("keydown", f); return () => window.removeEventListener("keydown", f);
  }, [criteria, active, setScore, next, prev, router, e.id]);

  if (sub.isLoading || crit.isLoading || mine.isLoading) return <LoadingBlock rows={4} />;
  if (mine.error) return <ErrorState error={mine.error} retry={() => mine.refetch()} />;
  if (sub.error || !sub.data) return <ErrorState error={sub.error} />;
  const s = sub.data;
  return (
    <div className="grid gap-8 lg:grid-cols-[1fr_1.15fr]">
      <div className="space-y-6 lg:sticky lg:top-[132px] lg:self-start">
        <Link href={`/events/${e.id}/judge`} className="label flex items-center gap-2 hover:text-ink"><ArrowLeft size={13} /> Judge desk · {idx + 1} of {list.length}</Link>
        <div className="panel ticks overflow-hidden"><div className="aspect-[16/6] border-b border-line"><Cover seed={s.id + s.name} label={s.name} rounded={false} /></div>
          <div className="p-6"><div className="mb-3 flex gap-2">{s.track_name && <span className="chip">{s.track_name}</span>}<span className="chip">{s.team_name}</span></div>
            <h1 className="display text-[3.4rem]">{s.name}</h1><p className="mt-2 text-ink2">{s.tagline}</p>
            <div className="mt-5 flex flex-wrap gap-2">{safeHref(s.repo_url) && <a className="btn btn-sm" href={safeHref(s.repo_url)} target="_blank" rel="noopener noreferrer"><GitBranch size={12} /> Repo <ExternalLink size={10} className="text-ink3" /></a>}{s.live_url && <a className="btn btn-sm" href={s.live_url} target="_blank" rel="noopener noreferrer"><Globe size={12} /> Live</a>}</div>
            <div className="mt-6 max-h-56 space-y-3 overflow-auto pr-2 text-[14px] leading-relaxed text-ink2">{s.description.split("\n\n").map((p, i) => <p key={i}>{p}</p>)}</div></div></div>
      </div>

      <div className="space-y-5">
        {locked && <div className="panel flex items-center gap-3 p-4"><Lock size={16} className="text-signal" /><span className="text-[13.5px] text-ink2">Scoring is closed for this event — read-only.</span></div>}
        <div className="panel ticks flex flex-wrap items-center justify-between gap-4 p-5"><div><div className="label mb-2">Your weighted score</div><SplitFlap text={answered ? total.toFixed(2) : "-.--"} size={3.4} color={complete ? "ok" : "amber"} framed scramble={false} stagger={0} /></div>
          <div className="text-right"><div className="label mb-1">{complete ? "Complete" : `${answered}/${criteria.length} scored`}</div><div className="progress w-40"><i style={{ width: `${(answered / Math.max(1, criteria.length)) * 100}%`, background: complete ? "var(--ok)" : undefined }} /></div></div></div>
        {criteria.map((c, i) => (
          <div key={c.id} onClick={() => setActive(i)} className={cn("panel p-6 transition-all", active === i ? "!border-amber shadow-[0_0_0_1px_var(--amber),0_20px_50px_-24px_var(--amber)]" : "opacity-90")}>
            <div className="mb-5 flex items-start justify-between gap-4"><div><div className="label mb-1.5 flex items-center gap-2"><span className="text-amberink">{String(i + 1).padStart(2, "0")}</span> · weight {Math.round((c.weight / wsum) * 100)}%</div><h3 className="display text-[2rem]">{c.name}</h3><p className="mt-1 max-w-md text-[13px] text-ink3">{c.description}</p></div>
              <span className="mono text-[10.5px] text-ink3">{saving === c.id ? "saving…" : vals[c.id] ? "saved ✓" : ""}</span></div>
            <div className="flex flex-wrap gap-3">{[1, 2, 3, 4, 5].map((n) => (
              <button key={n} className={cn("key", vals[c.id] === n && "on")} disabled={locked} onClick={(ev) => { ev.stopPropagation(); setActive(i); setScore(c.id, n); }} aria-pressed={vals[c.id] === n} aria-label={`${n} — ${LABELS[n - 1]}`}><span className="n">{n}</span><span className="t">{LABELS[n - 1]}</span></button>
            ))}</div>
          </div>
        ))}
        {err && <div role="alert" className="border border-signal px-4 py-3 text-sm text-signal">{err}</div>}
        <div className="flex flex-wrap items-center justify-between gap-4 pt-2">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-[12px] text-ink3"><span><Kbd>1</Kbd>–<Kbd>5</Kbd> score</span><span><Kbd>↑</Kbd><Kbd>↓</Kbd> criterion</span><span><Kbd>←</Kbd><Kbd>→</Kbd> project</span></div>
          <div className="flex gap-2">{prev && <Link className="btn btn-sm" href={`/events/${e.id}/judge/${prev.submission_id}`}><ArrowLeft size={12} /> Prev</Link>}{next ? <Link className={cn("btn btn-sm", complete && "btn-primary")} href={`/events/${e.id}/judge/${next.submission_id}`}>Next <ArrowRight size={12} /></Link> : <Link className="btn btn-sm btn-primary" href={`/events/${e.id}/judge`}>Finish</Link>}</div>
        </div>
      </div>
    </div>
  );
}
