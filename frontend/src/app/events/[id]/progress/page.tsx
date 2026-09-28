"use client";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { Gate, useEventCtx } from "@/components/EventContext";
import { SplitFlap } from "@/components/SplitFlap";
import { Empty, PageHead, Q } from "@/components/ui";
import type { Assignment } from "@/lib/types";

export default function ProgressPage() { return <Gate allow={["organizer"]} what="Progress is an organiser view."><Inner /></Gate>; }

function Inner() {
  const { event: e } = useEventCtx();
  const q = useQuery({ queryKey: ["progress", e.id], queryFn: () => api.judging.progress(e.id), refetchInterval: 8000 });
  const asg = useQuery({ queryKey: ["assignments", e.id], queryFn: () => api.judging.allAssignments(e.id) });
  return (
    <div>
      <PageHead kicker="Judging · progress" title={<>Who hasn&apos;t <em>started?</em></>} sub="Live view — refreshes every few seconds. Each cell is one assigned project: green is fully scored, amber is started, dark is untouched." />
      <Q q={q}>{(p) => {
        if (!p.total_assignments) return <Empty title="Nothing to track" body="Run assignment first." />;
        const pct = Math.round((p.total_complete / p.total_assignments) * 100); const idle = p.judges.filter((j) => j.assigned > 0 && j.started === 0);
        return (
          <div className="space-y-8">
            <div className="grid gap-4 md:grid-cols-[1.3fr_1fr]">
              <div className="panel ticks p-6"><div className="label mb-4">Overall</div><div className="flex flex-wrap items-center gap-5"><SplitFlap text={String(pct).padStart(3, " ")} size={4.4} framed scramble color={pct === 100 ? "ok" : "amber"} /><span className="cond text-5xl text-ink3">%</span><div className="ml-auto text-right"><div className="cond text-4xl">{p.total_complete}<span className="text-ink3"> / {p.total_assignments}</span></div><div className="label">reviews complete</div></div></div><div className="progress mt-6"><i style={{ width: `${pct}%` }} /></div></div>
              <div className="panel p-6"><div className="label mb-3" style={{ color: idle.length ? "var(--signal)" : undefined }}>Not started</div>{idle.length ? <ul className="space-y-2">{idle.map((j) => <li key={j.judge_id} className="flex items-center justify-between text-[14px]"><span>{j.judge_name}</span><span className="chip chip-signal">{j.assigned} waiting</span></li>)}</ul> : <p className="text-[14px] text-ink2">Everyone with an assignment has begun.</p>}</div>
            </div>
            <div className="panel divide-y divide-line">
              {p.judges.map((j) => {
                const mine = (asg.data?.assignments ?? []).filter((a) => a.judge_id === j.judge_id);
                return (
                  <div key={j.judge_id} className="grid items-center gap-4 p-5 md:grid-cols-[14rem_1fr_6rem]">
                    <div><div className="text-[15px]">{j.judge_name}</div><div className="label mt-1">{j.assigned} assigned</div></div>
                    <div className="flex flex-wrap gap-1.5">{((mine.length ? mine : Array.from({ length: j.assigned }, () => null)) as (Assignment | null)[]).map((a, i) => { const st = !a ? "none" : a.complete ? "done" : a.scored_criteria > 0 ? "part" : "none"; return <i key={i} title={a ? `${a.submission_name}: ${a.scored_criteria}/${a.total_criteria}` : ""} className="h-6 w-6 border transition-colors" style={{ borderColor: st === "done" ? "var(--ok)" : st === "part" ? "var(--amber)" : "var(--line2)", background: st === "done" ? "color-mix(in srgb, var(--ok) 55%, transparent)" : st === "part" ? "color-mix(in srgb, var(--amber) 40%, transparent)" : "transparent" }} />; })}</div>
                    <div className="text-right"><span className="cond text-3xl">{j.complete}</span><span className="cond text-xl text-ink3">/{j.assigned}</span></div>
                  </div>
                );
              })}
            </div>
          </div>
        );
      }}</Q>
    </div>
  );
}
