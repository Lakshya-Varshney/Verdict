"use client";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Swords, PartyPopper } from "lucide-react";
import { api } from "@/lib/api";
import { useAct } from "@/lib/act";
import { Gate, useEventCtx } from "@/components/EventContext";
import { Cover } from "@/components/Cover";
import { SplitFlap } from "@/components/SplitFlap";
import { Empty, Kbd, PageHead, Q } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { Submission } from "@/lib/types";

export default function DuelPage() { return <Gate allow={["judge"]} what="Duels are drawn from a judge's own assignments."><Inner /></Gate>; }

function Inner() {
  const { event: e } = useEventCtx(); const qc = useQueryClient(); const act = useAct();
  const q = useQuery({ queryKey: ["duel", e.id], queryFn: () => api.judging.duelNext(e.id), staleTime: 0, gcTime: 0 });
  const [pick, setPick] = useState<string | null>(null);
  const choose = useCallback(async (a: Submission, b: Submission, w: Submission) => {
    if (pick) return; setPick(w.id);
    const r = await act(() => api.judging.duelVote(e.id, { a: a.id, b: b.id, winner_id: w.id }));
    await new Promise((res) => setTimeout(res, 550)); setPick(null); if (r) await qc.invalidateQueries({ queryKey: ["duel", e.id] }); 
  }, [pick, act, e.id, qc]);
  const d = q.data;
  useEffect(() => {
    const f = (ev: KeyboardEvent) => { if (!d?.a || !d.b) return; if (ev.key === "ArrowLeft" || ev.key.toLowerCase() === "a") choose(d.a, d.b, d.a); if (ev.key === "ArrowRight" || ev.key.toLowerCase() === "b") choose(d.a, d.b, d.b); };
    window.addEventListener("keydown", f); return () => window.removeEventListener("keydown", f);
  }, [d, choose]);
  return (
    <div>
      <PageHead kicker="Pairwise mode" title={<>Which is <em>better?</em></>} sub="No absolute scores. Two projects, one call. A Bradley–Terry ranking is fitted from everyone's duels — a second opinion on the rubric." />
      <Q q={q}>{(x) => {
        if (!x.a || !x.b) return <Empty icon={<PartyPopper size={20} />} title="All duels done" body={x.total ? `You've settled ${x.done} matchups. The organiser can now see a pairwise ranking beside the rubric scores.` : "You need at least two assigned projects for duels."} action={<Link href={`/events/${e.id}/judge`} className="btn btn-primary">Back to judge desk</Link>} />;
        const a = x.a, b = x.b;
        return (
          <div className="space-y-8">
            <div className="flex items-center justify-between"><div className="flex items-center gap-4"><SplitFlap text={String(x.done + 1).padStart(2, "0")} size={2.2} framed scramble={false} /><span className="label">of {x.total} duels</span></div><div className="hidden gap-4 text-[12px] text-ink3 sm:flex"><span><Kbd>←</Kbd> or <Kbd>A</Kbd> left wins</span><span><Kbd>→</Kbd> or <Kbd>B</Kbd> right wins</span></div></div>
            <div className="grid items-stretch gap-6 md:grid-cols-[1fr_auto_1fr]">
              {[a, b].map((s, i) => (
                <div key={s.id} className="contents">
                  <button onClick={() => choose(a, b, s)} className={cn("panel ticks group text-left transition-all duration-500", pick === s.id ? "!border-amber -translate-y-2 shadow-[0_0_60px_-10px_var(--amber)]" : pick ? "scale-[.97] opacity-30" : "hover-lift")} aria-label={`Choose ${s.name}`}>
                    <div className="aspect-[16/9] overflow-hidden border-b border-line"><Cover seed={s.id + s.name} label={s.name} rounded={false} /></div>
                    <div className="p-6"><div className="label mb-2">{i === 0 ? "Left" : "Right"} · {s.track_name}</div><h2 className="display text-[3.2rem]">{s.name}</h2><p className="mt-2 text-ink2">{s.tagline}</p><p className="mt-4 line-clamp-4 text-[13.5px] text-ink3">{s.description}</p>
                      <div className="btn btn-primary mt-6 w-full pointer-events-none"><Swords size={14} /> This one</div></div>
                  </button>
                  {i === 0 && <div className="hidden place-items-center md:grid"><span className="cond text-6xl text-ink3">VS</span></div>}
                </div>
              ))}
            </div>
          </div>
        );
      }}</Q>
    </div>
  );
}
