"use client";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { api } from "@/lib/api";
import { useAct } from "@/lib/act";
import { Gate, useEventCtx } from "@/components/EventContext";
import { WeightBar } from "@/components/Charts";
import { SplitFlap } from "@/components/SplitFlap";
import { Empty, Field, PageHead, Q, SectionLabel } from "@/components/ui";

export default function RubricPage() { return <Gate allow={["organizer"]} what="Only organisers configure the rubric."><Inner /></Gate>; }

function Inner() {
  const { event: e } = useEventCtx(); const qc = useQueryClient(); const act = useAct();
  const q = useQuery({ queryKey: ["criteria", e.id], queryFn: () => api.judging.criteria(e.id) });
  const [name, setName] = useState(""); const [description, setDescription] = useState(""); const [weight, setWeight] = useState(10);
  const add = async (ev: React.FormEvent) => { ev.preventDefault(); const r = await act(() => api.judging.addCriterion(e.id, { name, description, weight }), "Criterion added"); if (r) { setName(""); setDescription(""); setWeight(10); qc.invalidateQueries({ queryKey: ["criteria", e.id] }); } };
  const del = async (id: string) => { const r = await act(() => api.judging.deleteCriterion(e.id, id), "Criterion removed"); if (r) qc.invalidateQueries({ queryKey: ["criteria", e.id] }); };
  return (
    <div>
      <PageHead kicker="Judging · rubric" title={<>What counts, and <em>how much.</em></>} sub="Weights are relative — they're normalised to 100% when scores are combined, so add or remove criteria without redoing the arithmetic." />
      <Q q={q}>{(cs) => (
        <div className="grid gap-10 lg:grid-cols-[1.4fr_1fr]">
          <div className="space-y-8">
            {cs.length > 0 && <div className="panel p-6"><div className="label mb-4">Weight distribution</div><WeightBar criteria={cs} /></div>}
            {cs.length ? <ul className="space-y-3">{cs.map((c, i) => (
              <li key={c.id} className="panel fade-up flex items-center gap-5 p-5" style={{ ["--i" as string]: i } as React.CSSProperties}>
                <SplitFlap text={String(Math.round((c.weight / cs.reduce((a, x) => a + x.weight, 0)) * 100))} size={2.2} pad={2} padSide="start" framed scramble={false} />
                <div className="min-w-0 flex-1"><h3 className="display text-[1.9rem]">{c.name}</h3><p className="text-[13px] text-ink3">{c.description}</p></div>
                <div className="text-right"><div className="label">raw weight</div><div className="cond text-2xl">{c.weight}</div></div>
                <button className="btn btn-ghost btn-icon hover:!text-signal" onClick={() => del(c.id)} aria-label={`Remove ${c.name}`}><Trash2 size={15} /></button>
              </li>))}</ul> : <Empty title="No criteria yet" body="Judges can't score until a rubric exists. Add the first criterion." />}
          </div>
          <form onSubmit={add} className="panel ticks h-fit space-y-5 p-6 lg:sticky lg:top-[132px]"><SectionLabel>Add criterion</SectionLabel>
            <Field label="Name"><input className="input" value={name} onChange={(x) => setName(x.target.value)} placeholder="Judging Integrity" /></Field>
            <Field label="What are judges looking for?"><textarea className="textarea !min-h-[90px]" value={description} onChange={(x) => setDescription(x.target.value)} /></Field>
            <Field label={`Weight · ${weight}`}><input type="range" min={1} max={50} value={weight} onChange={(x) => setWeight(+x.target.value)} className="w-full accent-[var(--amber)]" /></Field>
            <button className="btn btn-primary w-full" disabled={!name.trim()}><Plus size={14} /> Add to rubric</button>
          </form>
        </div>
      )}</Q>
    </div>
  );
}
