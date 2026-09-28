"use client";
import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Shuffle, UserPlus } from "lucide-react";
import { api } from "@/lib/api";
import { useAct } from "@/lib/act";
import { Gate, useEventCtx } from "@/components/EventContext";
import { AssignGraph } from "@/components/Charts";
import { Empty, Field, LoadingBlock, Modal, PageHead, Segmented, SectionLabel, Stat } from "@/components/ui";
import type { AssignStrategy } from "@/lib/types";

export default function AssignPage() { return <Gate allow={["organizer"]} what="Only organisers assign judges."><Inner /></Gate>; }

function Inner() {
  const { event: e } = useEventCtx(); const qc = useQueryClient(); const act = useAct();
  const roles = useQuery({ queryKey: ["roles", e.id], queryFn: () => api.events.roles(e.id) });
  const subs = useQuery({ queryKey: ["gallery", e.id, "all", false], queryFn: () => api.subs.gallery(e.id, { limit: 200 }) });
  const asg = useQuery({ queryKey: ["assignments", e.id], queryFn: () => api.judging.allAssignments(e.id) });
  const [strategy, setStrategy] = useState<AssignStrategy>("round_robin"); const [k, setK] = useState(3); const [confirm, setConfirm] = useState(false); const [email, setEmail] = useState(""); const [hover, setHover] = useState<string | null>(null);
  const judges = useMemo(() => [...new Map((roles.data ?? []).filter((r) => r.role === "judge").map((r) => [r.user_id!, { id: r.user_id!, name: r.user_name ?? r.user_id! }])).values()], [roles.data]);
  const list = asg.data?.assignments ?? []; const has = list.length > 0;
  const load = useMemo(() => judges.map((j) => ({ ...j, n: list.filter((a) => a.judge_id === j.id).length })), [judges, list]);
  const run = async () => { setConfirm(false); const r = await act(() => api.judging.assign(e.id, { strategy, reviews_per_submission: k }), "Assignments generated"); if (r) qc.invalidateQueries({ queryKey: ["assignments", e.id] }); };
  const invite = async (ev: React.FormEvent) => { ev.preventDefault(); const r = await act(() => api.events.addRole(e.id, { email, role: "judge" }), "Judge added"); if (r) { setEmail(""); qc.invalidateQueries({ queryKey: ["roles", e.id] }); } };
  const shownSubs = (subs.data?.items ?? []).map((s) => ({ id: s.id, name: s.name }));
  return (
    <div>
      <PageHead kicker="Judging · assignment" title={<>Who reviews <em>what.</em></>} sub="Judges only ever see their own batch. Re-running assignment clears existing assignments and their scores — so do it before judging starts." />
      {(roles.isLoading || subs.isLoading || asg.isLoading) ? <LoadingBlock /> : (
        <div className="grid gap-10 lg:grid-cols-[.9fr_1.5fr]">
          <div className="space-y-6">
            <div className="grid grid-cols-3 gap-3"><Stat label="Judges" value={String(judges.length).padStart(2, "0")} /><Stat label="Projects" value={String(subs.data?.total ?? 0).padStart(2, "0")} /><Stat label="Reviews" value={String(list.length).padStart(2, "0")} accent /></div>
            <div className="panel ticks space-y-6 p-6"><SectionLabel>Strategy</SectionLabel>
              <Segmented value={strategy} onChange={setStrategy} options={[{ value: "round_robin", label: "Round-robin" }, { value: "balanced", label: "Balanced load" }]} />
              <p className="text-[13px] text-ink3">{strategy === "round_robin" ? "Judges take turns down the project list. Predictable and easy to audit." : "Each project goes to the currently least-loaded judges. Evens out uneven counts."}</p>
              <Field label={`Reviews per project · ${k}`} hint={`max ${Math.max(1, judges.length)}`}><input type="range" min={1} max={Math.max(1, judges.length)} value={Math.min(k, Math.max(1, judges.length))} onChange={(x) => setK(+x.target.value)} className="w-full accent-[var(--amber)]" /></Field>
              <button className="btn btn-primary w-full" disabled={!judges.length || !(subs.data?.total)} onClick={() => (has ? setConfirm(true) : run())}><Shuffle size={14} /> {has ? "Re-run assignment" : "Assign judges"}</button>
            </div>
            <form onSubmit={invite} className="panel space-y-4 p-6"><SectionLabel>Judging panel</SectionLabel>
              <ul className="space-y-2">{load.map((j) => <li key={j.id} onMouseEnter={() => setHover(j.id)} onMouseLeave={() => setHover(null)} className="flex items-center justify-between border border-line px-3 py-2 text-[13.5px] transition-colors hover:border-amber"><span>{j.name}</span><span className="mono text-[11px] text-ink3">{j.n} projects</span></li>)}{!judges.length && <li className="text-sm text-ink3">No judges yet.</li>}</ul>
              <div className="flex gap-2"><input className="input" type="email" placeholder="judge@email.com" value={email} onChange={(x) => setEmail(x.target.value)} aria-label="Judge email" /><button className="btn btn-icon" disabled={!email}><UserPlus size={15} /></button></div>
            </form>
          </div>
          <div className="panel p-6"><div className="mb-4 flex items-center justify-between"><SectionLabel>Assignment graph</SectionLabel></div>
            {has ? <AssignGraph judges={judges} subs={shownSubs} edges={list} hover={hover} setHover={setHover} /> : <Empty title="No assignments yet" body="Pick a strategy and run it — you'll see every judge-to-project link drawn here." />}
            {has && <p className="mt-2 text-[12px] text-ink3">Hover a judge to isolate their batch.</p>}</div>
        </div>
      )}
      <Modal open={confirm} onClose={() => setConfirm(false)} title="Re-run assignment?"><p className="text-ink2">This replaces all {list.length} current assignments and <b className="text-signal">deletes any scores already entered</b>. It&apos;s recorded in the audit log.</p><div className="mt-6 flex gap-3"><button className="btn btn-danger" onClick={run}>Yes, reassign</button><button className="btn" onClick={() => setConfirm(false)}>Cancel</button></div></Modal>
    </div>
  );
}
