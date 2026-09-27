"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight } from "lucide-react";
import { api } from "@/lib/api";
import { useAct } from "@/lib/act";
import { useRequireAuth } from "@/lib/auth";
import { Field, LoadingBlock, PageHead, SectionLabel, TagInput } from "@/components/ui";
import { fromLocalInput, toLocalInput } from "@/lib/utils";
import { useQueryClient } from "@tanstack/react-query";

export default function NewEvent() {
  const { authed } = useRequireAuth(); const router = useRouter(); const act = useAct(); const qc = useQueryClient();
  const in72 = toLocalInput(new Date(Date.now() + 72 * 3600_000).toISOString());
  const [f, setF] = useState({ name: "", tagline: "", description: "", deadline: in72, mode: "auth", tracks: [] as string[] });
  const [busy, setBusy] = useState(false);
  if (!authed) return <LoadingBlock rows={2} />;
  const submit = async (e: React.FormEvent) => {
    e.preventDefault(); setBusy(true);
    const r = await act(() => api.events.create({ name: f.name, tagline: f.tagline, description: f.description, deadline_at: fromLocalInput(f.deadline), voting_mode: f.mode as never, tracks: f.tracks.map((name) => ({ name })) }), "Event created as a draft");
    setBusy(false); if (r) { qc.invalidateQueries(); router.push(`/events/${r.id}/settings`); }
  };
  return (
    <div className="mx-auto max-w-3xl">
      <PageHead kicker="Organiser" title={<>A new <em>event.</em></>} sub="Starts as a draft — nobody sees it until you open it. You can fill in prizes, questions and schedule on the next screen." />
      <form onSubmit={submit} className="panel ticks space-y-6 p-8"><SectionLabel n="01">The essentials</SectionLabel>
        <Field label="Name"><input className="input !text-lg" value={f.name} onChange={(x) => setF({ ...f, name: x.target.value })} placeholder="Dogfood 2027" /></Field>
        <Field label="Tagline"><input className="input" value={f.tagline} onChange={(x) => setF({ ...f, tagline: x.target.value })} /></Field>
        <Field label="Description"><textarea className="textarea" value={f.description} onChange={(x) => setF({ ...f, description: x.target.value })} /></Field>
        <div className="grid gap-5 sm:grid-cols-2"><Field label="Submissions close"><input type="datetime-local" className="input" value={f.deadline} onChange={(x) => setF({ ...f, deadline: x.target.value })} /></Field>
          <Field label="Voting mode"><select className="select" value={f.mode} onChange={(x) => setF({ ...f, mode: x.target.value })}><option value="open">Open link</option><option value="email">Email-gated</option><option value="auth">Signed-in only</option><option value="quadratic">Quadratic credits</option></select></Field></div>
        <Field label="Tracks" hint="Enter to add"><TagInput value={f.tracks} onChange={(v) => setF({ ...f, tracks: v })} placeholder="backend, design, ai…" /></Field>
        <button className="btn btn-primary" disabled={busy || f.name.trim().length < 3}>Create event <ArrowRight size={14} /></button></form>
    </div>
  );
}
