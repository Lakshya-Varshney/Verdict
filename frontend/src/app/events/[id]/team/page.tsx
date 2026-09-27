"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, Copy, Crown, Link2 } from "lucide-react";
import { api } from "@/lib/api";
import { useAct } from "@/lib/act";
import { Gate, useEventCtx } from "@/components/EventContext";
import { SplitFlap } from "@/components/SplitFlap";
import { Avatar, Field, Q, SectionLabel } from "@/components/ui";
import { copyText } from "@/lib/utils";
import type { Team } from "@/lib/types";

export default function TeamPage() { return <Gate allow={["participant"]} what="Teams are for participants."><Inner /></Gate>; }

function Inner() {
  const { event: e } = useEventCtx(); const q = useQuery({ queryKey: ["team-mine", e.id], queryFn: () => api.teams.mine(e.id) });
  return <Q q={q}>{(teams) => (teams.length ? <TeamCard team={teams[0]} /> : <NoTeam />)}</Q>;
}

function NoTeam() {
  const { event: e } = useEventCtx(); const act = useAct(); const qc = useQueryClient(); const router = useRouter();
  const [name, setName] = useState(""); const [link, setLink] = useState(""); const [busy, setBusy] = useState(false); const [linkErr, setLinkErr] = useState("");
  const create = async (ev: React.FormEvent) => { ev.preventDefault(); setBusy(true); const t = await act(() => api.teams.create(e.id, name), "Team created"); setBusy(false); if (t) { await qc.invalidateQueries(); } };
  const go = (ev: React.FormEvent) => {
    ev.preventDefault(); setLinkErr("");
    try { const u = new URL(link.trim()); const m = u.pathname.match(/\/join\/([^/]+)/); const c = u.searchParams.get("code"); if (m && c) return router.push(`/join/${m[1]}?code=${c}`); } catch { /* maybe id:code */ }
    const [id, code] = link.trim().split(":"); if (id && code) return router.push(`/join/${id}?code=${code}`);
    setLinkErr("That doesn't look like an invite link. Paste the full link your teammate sent.");
  };
  return (
    <div className="grid gap-8 lg:grid-cols-2">
      <form onSubmit={create} className="panel ticks fade-up p-8"><div className="label mb-3 text-amberink">Option A</div><h2 className="display text-5xl">Start a <em>team.</em></h2><p className="mt-3 text-[14px] text-ink2">You become the lead. Up to {e.team_size_max} people. You&apos;ll get an invite link to share.</p>
        <div className="mt-6 space-y-5"><Field label="Team name"><input className="input" value={name} onChange={(x) => setName(x.target.value)} placeholder="Null Pointers" /></Field><button className="btn btn-primary" disabled={busy || name.trim().length < 2}>Create team <ArrowRight size={14} /></button></div></form>
      <form onSubmit={go} className="panel fade-up p-8" style={{ ["--i" as string]: 1 } as React.CSSProperties}><div className="label mb-3 text-amberink">Option B</div><h2 className="display text-5xl">Got an <em>invite?</em></h2><p className="mt-3 text-[14px] text-ink2">Paste the invite link from your team lead.</p>
        <div className="mt-6 space-y-5"><Field label="Invite link" error={linkErr}><input className="input" value={link} onChange={(x) => setLink(x.target.value)} placeholder="https://…/join/team_x?code=NUL1234" /></Field><button className="btn" disabled={!link.trim()}><Link2 size={14} /> Continue</button></div></form>
    </div>
  );
}

function TeamCard({ team }: { team: Team }) {
  const { event: e } = useEventCtx(); const [copied, setCopied] = useState(false);
  const url = typeof window !== "undefined" ? `${location.origin}/join/${team.id}?code=${team.invite_code}` : "";
  return (
    <div className="grid gap-8 lg:grid-cols-[1.4fr_1fr]">
      <div className="panel ticks fade-up p-8">
        <div className="label mb-3">Your team</div><h2 className="display text-[4rem]">{team.name}</h2>
        <SectionLabel>Members</SectionLabel>
        <ul className="divide-y divide-line border-y border-line">{team.members.map((m) => <li key={m.user_id} className="flex items-center gap-4 py-3.5"><Avatar name={m.name} /><div className="flex-1"><div className="text-[14.5px]">{m.name}</div><div className="text-[12.5px] text-ink3">{m.email}</div></div>{m.is_lead && <span className="chip chip-amber"><Crown size={10} /> lead</span>}</li>)}</ul>
        <div className="mt-8"><div className="label mb-2">Invite link</div>
          <div className="flex gap-2"><input readOnly value={url} className="input mono !text-[11.5px]" onFocus={(x) => x.currentTarget.select()} aria-label="Invite link" />
            <button className="btn" onClick={async () => { await copyText(url); setCopied(true); setTimeout(() => setCopied(false), 1600); }}>{copied ? <Check size={14} color="var(--ok)" /> : <Copy size={14} />} Copy</button></div>
          <p className="mt-2 text-[12.5px] text-ink3">Anyone with this link and an account can join until the team is full.</p></div>
      </div>
      <div className="space-y-6">
        <div className="panel fade-up p-6" style={{ ["--i" as string]: 1 } as React.CSSProperties}><div className="label mb-4">Capacity</div><div className="flex items-center gap-4"><SplitFlap text={String(team.members.length).padStart(2, "0")} size={3} framed scramble={false} /><span className="cond text-4xl text-ink3">/</span><SplitFlap text={String(e.team_size_max).padStart(2, "0")} size={3} color="ivory" framed scramble={false} /></div></div>
        <div className="panel fade-up p-6" style={{ ["--i" as string]: 2 } as React.CSSProperties}><div className="label mb-2">Submission</div><p className="text-[14px] text-ink2">{team.submission_id ? "A draft exists. Keep editing until the deadline." : "No submission started yet."}</p><Link href={`/events/${e.id}/submit`} className="btn btn-primary mt-5">Open editor <ArrowRight size={14} /></Link></div>
      </div>
    </div>
  );
}
