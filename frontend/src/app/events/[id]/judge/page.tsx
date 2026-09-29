"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Check, FileSignature, Lock } from "lucide-react";
import { api } from "@/lib/api";
import { Gate, useEventCtx } from "@/components/EventContext";
import { SplitFlap } from "@/components/SplitFlap";
import { Empty, Q, Stat } from "@/components/ui";
import { useAct } from "@/lib/act";
import { cn, downloadBlob } from "@/lib/utils";

export default function JudgeDesk() { return <Gate allow={["judge"]} what="The judge desk shows only a judge's own assignments."><Inner /></Gate>; }

function Inner() {
  const { event: e } = useEventCtx(); const q = useQuery({ queryKey: ["assign-mine", e.id], queryFn: () => api.judging.mine(e.id) });
  const open = e.status === "judging";
  const act = useAct();
  const attest = async () => {
    const doc = await act(() => api.judging.attestation(e.id), "Signed - downloading your record");
    if (doc) downloadBlob(new Blob([JSON.stringify(doc, null, 2)], { type: "application/json" }), `score-attestation-${doc.verify_hash.slice(0, 8)}.json`);
  };
  return (
    <Q q={q}>{(rows) => {
      const done = rows.filter((r) => r.complete).length; const started = rows.filter((r) => !r.complete && r.scored_criteria > 0).length; const next = rows.find((r) => !r.complete);
      if (!rows.length) return <Empty title="Nothing assigned yet" body="The organiser hasn't run assignment. You'll see your batch here — and only yours." />;
      return (
        <div className="space-y-10">
          {!open && <div className="panel flex items-center gap-4 p-5"><Lock size={18} className="text-signal" /><p className="text-[13.5px] text-ink2"><b className="text-ink">Scoring is closed</b> — this event is <span className="chip">{e.status}</span>. You can still read your scores.</p></div>}
          <div className="panel flex flex-wrap items-center justify-between gap-4 p-5">
            <div><div className="label mb-1">Proof of your scores</div><p className="text-[13px] text-ink2">An Ed25519-signed record of exactly what you scored, right now — yours to keep, verify offline, or show if a score is ever disputed.</p></div>
            <button className="btn" onClick={attest}><FileSignature size={14} /> Get signed record</button>
          </div>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <div className="panel ticks col-span-2 p-6"><div className="label mb-4">Completed</div><div className="flex items-center gap-4"><SplitFlap text={String(done).padStart(2, "0")} size="min(4rem, 11vw)" framed scramble /><span className="cond text-5xl text-ink3">/</span><SplitFlap text={String(rows.length).padStart(2, "0")} size="min(4rem, 11vw)" color="ivory" framed scramble /></div>
              <div className="progress mt-6"><i style={{ width: `${(done / rows.length) * 100}%` }} /></div></div>
            <Stat label="In progress" value={String(started).padStart(2, "0")} /><Stat label="Not started" value={String(rows.length - done - started).padStart(2, "0")} />
          </div>
          {next && open && <Link href={`/events/${e.id}/judge/${next.submission_id}`} className="btn btn-primary">Continue with {next.submission_name || "next project"} <ArrowRight size={14} /></Link>}
          <div className="panel overflow-x-auto"><table className="tbl">
            <thead><tr><th>#</th><th>Project</th><th>Team</th><th>Track</th><th>Progress</th><th /></tr></thead>
            <tbody>{rows.map((r, i) => (
              <tr key={r.id}><td className="mono text-ink3">{String(i + 1).padStart(2, "0")}</td><td><span className="display text-2xl">{r.submission_name}</span></td><td className="text-ink2">{r.team_name}</td><td><span className="chip">{r.track_name ?? "—"}</span></td>
                <td className="w-48"><div className="flex items-center gap-3"><div className="progress flex-1"><i style={{ width: `${(r.scored_criteria / Math.max(1, r.total_criteria)) * 100}%`, background: r.complete ? "var(--ok)" : undefined, boxShadow: r.complete ? "0 0 12px var(--ok)" : undefined }} /></div><span className="mono text-[11px] text-ink3">{r.scored_criteria}/{r.total_criteria}</span></div></td>
                <td className="text-right"><Link href={`/events/${e.id}/judge/${r.submission_id}`} className={cn("btn btn-sm", r.complete && "btn-ghost")}>{r.complete ? <><Check size={12} className="text-ok" /> Review</> : "Score"}</Link></td></tr>
            ))}</tbody></table></div>
        </div>
      );
    }}</Q>
  );
}
