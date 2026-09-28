"use client";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Minus, Plus, UserPlus } from "lucide-react";
import { api } from "@/lib/api";
import { useAct } from "@/lib/act";
import { Gate, useEventCtx } from "@/components/EventContext";
import { Field, PageHead, Q, RoleBadge, Segmented, SectionLabel } from "@/components/ui";
import { MATRIX } from "@/lib/nav";
import { EVENT_STATUSES, type EventT, type Prize, type Role, type VotingMode } from "@/lib/types";
import { fromLocalInput, toLocalInput } from "@/lib/utils";

export default function SettingsPage() { return <Gate allow={["organizer"]} what="Only organisers change event settings."><Inner /></Gate>; }

function Inner() {
  const [tab, setTab] = useState<"details" | "tracks" | "roles">("details");
  return (<div><PageHead kicker="Organiser" title={<>Event <em>settings.</em></>} actions={<Segmented value={tab} onChange={setTab} options={[{ value: "details", label: "Details" }, { value: "tracks", label: "Tracks" }, { value: "roles", label: "Roles" }]} />} />
    {tab === "details" ? <Details /> : tab === "tracks" ? <Tracks /> : <Roles />}</div>);
}

function Details() {
  const { event: e } = useEventCtx(); const qc = useQueryClient(); const act = useAct();
  const [f, setF] = useState<EventT>({ ...e }); const set = <K extends keyof EventT>(k: K, v: EventT[K]) => setF((x) => ({ ...x, [k]: v }));
  const save = async (ev: React.FormEvent) => { ev.preventDefault(); const r = await act(() => api.events.update(e.id, { name: f.name, tagline: f.tagline, description: f.description, status: f.status, starts_at: f.starts_at, deadline_at: f.deadline_at, voting_opens_at: f.voting_opens_at, voting_closes_at: f.voting_closes_at, voting_mode: f.voting_mode, votes_per_voter: f.votes_per_voter, vote_credits: f.vote_credits, team_size_max: f.team_size_max, prizes: f.prizes, custom_questions: f.custom_questions }), "Settings saved"); if (r) qc.invalidateQueries(); };
  const setPrize = (i: number, p: Partial<Prize>) => set("prizes", f.prizes.map((x, j) => (j === i ? { ...x, ...p } : x)));
  return (
    <form onSubmit={save} className="grid gap-8 lg:grid-cols-[1.4fr_1fr]">
      <div className="space-y-8">
        <section className="panel space-y-5 p-7"><SectionLabel n="01">Basics</SectionLabel>
          <Field label="Name"><input className="input" value={f.name} onChange={(x) => set("name", x.target.value)} /></Field>
          <Field label="Tagline"><input className="input" value={f.tagline} onChange={(x) => set("tagline", x.target.value)} /></Field>
          <Field label="Description"><textarea className="textarea !min-h-[140px]" value={f.description} onChange={(x) => set("description", x.target.value)} /></Field></section>
        <section className="panel space-y-5 p-7"><SectionLabel n="02">Schedule</SectionLabel>
          <div className="grid gap-5 sm:grid-cols-2"><Field label="Starts"><input type="datetime-local" className="input" value={toLocalInput(f.starts_at)} onChange={(x) => set("starts_at", fromLocalInput(x.target.value))} /></Field>
            <Field label="Submissions close"><input type="datetime-local" className="input" value={toLocalInput(f.deadline_at)} onChange={(x) => set("deadline_at", fromLocalInput(x.target.value))} /></Field>
            <Field label="Voting opens"><input type="datetime-local" className="input" value={toLocalInput(f.voting_opens_at)} onChange={(x) => set("voting_opens_at", x.target.value ? fromLocalInput(x.target.value) : null)} /></Field>
            <Field label="Voting closes"><input type="datetime-local" className="input" value={toLocalInput(f.voting_closes_at)} onChange={(x) => set("voting_closes_at", x.target.value ? fromLocalInput(x.target.value) : null)} /></Field></div></section>
        <section className="panel space-y-4 p-7"><SectionLabel n="03">Prizes</SectionLabel>
          {f.prizes.map((p, i) => <div key={i} className="grid grid-cols-[4rem_1fr_7rem_2.5rem] gap-3"><input className="input" value={p.place} onChange={(x) => setPrize(i, { place: x.target.value })} aria-label="Place" /><input className="input" value={p.name} onChange={(x) => setPrize(i, { name: x.target.value })} aria-label="Prize name" /><input className="input" type="number" min={0} value={p.amount} onChange={(x) => setPrize(i, { amount: +x.target.value })} aria-label="Amount" /><button type="button" className="btn btn-ghost btn-icon" onClick={() => set("prizes", f.prizes.filter((_, j) => j !== i))} aria-label="Remove prize"><Minus size={14} /></button></div>)}
          <button type="button" className="btn btn-sm" onClick={() => set("prizes", [...f.prizes, { place: "★", name: "Special Prize", amount: 100 }])}><Plus size={12} /> Add prize</button></section>
        <section className="panel space-y-4 p-7"><SectionLabel n="04">Submission questions</SectionLabel>
          {f.custom_questions.map((q, i) => <div key={q.id} className="grid grid-cols-[1fr_auto_2.5rem] items-center gap-3"><input className="input" value={q.label} onChange={(x) => set("custom_questions", f.custom_questions.map((y, j) => (j === i ? { ...y, label: x.target.value } : y)))} aria-label="Question" /><label className="chip cursor-pointer"><input type="checkbox" className="accent-[var(--amber)]" checked={q.required} onChange={(x) => set("custom_questions", f.custom_questions.map((y, j) => (j === i ? { ...y, required: x.target.checked } : y)))} /> required</label><button type="button" className="btn btn-ghost btn-icon" onClick={() => set("custom_questions", f.custom_questions.filter((_, j) => j !== i))} aria-label="Remove question"><Minus size={14} /></button></div>)}
          <button type="button" className="btn btn-sm" onClick={() => set("custom_questions", [...f.custom_questions, { id: "cq" + Date.now().toString(36), label: "", required: false }])}><Plus size={12} /> Add question</button></section>
      </div>
      <div className="space-y-6 lg:sticky lg:top-[132px] lg:self-start">
        <div className="panel ticks space-y-5 p-6"><SectionLabel>Lifecycle</SectionLabel>
          <Field label="Status"><select className="select" value={f.status} onChange={(x) => set("status", x.target.value as EventT["status"])}>{EVENT_STATUSES.map((s) => <option key={s}>{s}</option>)}</select></Field>
          <p className="text-[12.5px] text-ink3">open → participants build · judging → scoring enabled · voting → public ballot · published → results visible.</p>
          <Field label="Voting mode"><select className="select" value={f.voting_mode} onChange={(x) => set("voting_mode", x.target.value as VotingMode)}><option value="open">Open link (fingerprint)</option><option value="email">Email-gated</option><option value="auth">Signed-in only</option><option value="quadratic">Quadratic credits</option></select></Field>
          {f.voting_mode === "quadratic"
            ? <Field label="Credits per voter" hint="n votes on one project cost n² credits"><input type="number" min={1} className="input" value={f.vote_credits ?? 25} onChange={(x) => set("vote_credits", Math.max(1, Number(x.target.value) || 1))} /></Field>
            : <Field label="Votes per voter" hint="one person, this many votes for the whole event"><input type="number" min={1} className="input" value={f.votes_per_voter ?? 1} onChange={(x) => set("votes_per_voter", Math.max(1, Number(x.target.value) || 1))} /></Field>}
          <Field label="Max team size"><input className="input" type="number" min={1} max={10} value={f.team_size_max} onChange={(x) => set("team_size_max", +x.target.value)} /></Field>
          <button className="btn btn-primary w-full">Save settings</button></div>
      </div>
    </form>
  );
}

function Tracks() {
  const { event: e } = useEventCtx(); const qc = useQueryClient(); const act = useAct(); const q = useQuery({ queryKey: ["tracks", e.id], queryFn: () => api.events.tracks(e.id) }); const [name, setName] = useState(""); const [d, setD] = useState("");
  const add = async (ev: React.FormEvent) => { ev.preventDefault(); const r = await act(() => api.events.addTrack(e.id, { name, description: d }), "Track added"); if (r) { setName(""); setD(""); qc.invalidateQueries({ queryKey: ["tracks", e.id] }); } };
  return (<div className="grid gap-8 lg:grid-cols-[1.4fr_1fr]"><Q q={q}>{(ts) => <ul className="space-y-3">{ts.map((t, i) => <li key={t.id} className="panel flex items-center gap-5 p-5"><span className="cond text-3xl amber">{String(i + 1).padStart(2, "0")}</span><div><h3 className="display text-3xl">{t.name}</h3><p className="text-[13px] text-ink3">{t.description}</p></div></li>)}{!ts.length && <li className="text-ink3">No tracks — teams compete in one open field.</li>}</ul>}</Q>
    <form onSubmit={add} className="panel space-y-5 p-6"><SectionLabel>Add track</SectionLabel><Field label="Name"><input className="input" value={name} onChange={(x) => setName(x.target.value)} /></Field><Field label="Description"><input className="input" value={d} onChange={(x) => setD(x.target.value)} /></Field><button className="btn btn-primary" disabled={!name.trim()}><Plus size={14} /> Add</button></form></div>);
}

function Roles() {
  const { event: e } = useEventCtx(); const qc = useQueryClient(); const act = useAct(); const q = useQuery({ queryKey: ["roles", e.id], queryFn: () => api.events.roles(e.id) }); const [email, setEmail] = useState(""); const [role, setRole] = useState("judge");
  const add = async (ev: React.FormEvent) => { ev.preventDefault(); const r = await act(() => api.events.addRole(e.id, { email, role }), `${email} is now ${role}`); if (r) { setEmail(""); qc.invalidateQueries({ queryKey: ["roles", e.id] }); } };
  return (
    <div className="space-y-10">
      <div className="grid gap-8 lg:grid-cols-[1.4fr_1fr]">
        <Q q={q}>{(rs) => { const staff = rs.filter((r) => r.role !== "participant"); return (
          <div className="panel overflow-x-auto"><table className="tbl"><thead><tr><th>Person</th><th>Email</th><th>Role</th></tr></thead><tbody>{staff.map((r) => <tr key={r.user_id + r.role}><td>{r.user_name}</td><td className="text-ink3">{r.user_email}</td><td><RoleBadge role={r.role as Role} /></td></tr>)}<tr><td colSpan={3} className="text-[12.5px] text-ink3">+ {rs.filter((r) => r.role === "participant").length} participants (added automatically when they join a team)</td></tr></tbody></table></div>); }}</Q>
        <form onSubmit={add} className="panel space-y-5 p-6"><SectionLabel>Grant a role</SectionLabel><Field label="Email"><input className="input" type="email" value={email} onChange={(x) => setEmail(x.target.value)} placeholder="judge@email.com" /></Field>
          <Field label="Role"><select className="select" value={role} onChange={(x) => setRole(x.target.value)}><option value="judge">Judge</option><option value="organizer">Organizer</option></select></Field><button className="btn btn-primary" disabled={!email}><UserPlus size={14} /> Grant</button><p className="text-[12px] text-ink3">Roles are per event. Granting judge here doesn&apos;t make anyone a judge elsewhere.</p></form>
      </div>
      <div><SectionLabel>What each role can do</SectionLabel><div className="panel overflow-x-auto"><table className="tbl min-w-[720px]"><thead><tr><th>Action</th>{["visitor", "participant", "judge", "organizer", "admin"].map((r) => <th key={r}>{r}</th>)}</tr></thead><tbody>{MATRIX.map((m) => <tr key={m.action}><td className="text-[13.5px]">{m.action}</td>{(["visitor", "participant", "judge", "organizer", "admin"] as const).map((r) => { const v = m[r]; return <td key={r} className="mono text-[11px]">{v === true ? <span className="text-ok">●</span> : v === false ? <span className="text-ink3">—</span> : <span className="chip chip-amber">{v}</span>}</td>; })}</tr>)}</tbody></table></div></div>
    </div>
  );
}
