"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink, GitBranch, Globe, PlayCircle, Send, Gavel, EyeOff } from "lucide-react";
import { api } from "@/lib/api";
import { useAct } from "@/lib/act";
import { isStaff, useAuth } from "@/lib/auth";
import { Cover } from "@/components/Cover";
import { Avatar, Empty, ErrorState, LoadingBlock, Q, SectionLabel, StatusChip } from "@/components/ui";
import { safeHref, timeAgo } from "@/lib/utils";
import type { Submission } from "@/lib/types";

export default function SubmissionPage() {
  const { sid } = useParams<{ sid: string }>();
  const q = useQuery({ queryKey: ["sub-view", sid], queryFn: () => api.subs.get(sid) });
  if (q.isLoading) return <LoadingBlock rows={4} />;
  if (q.error || !q.data) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  return <Detail s={q.data} />;
}

function Detail({ s }: { s: Submission }) {
  const { roleFor, authed } = useAuth(); const role = roleFor(s.event_id);
  const ev = useQuery({ queryKey: ["event", s.event_id], queryFn: () => api.events.get(s.event_id) });
  const votes = useQuery({ queryKey: ["votes", s.id], queryFn: () => api.vote.count(s.id) });
  const crit = useQuery({ queryKey: ["criteria", s.event_id], queryFn: () => api.judging.criteria(s.event_id), enabled: isStaff(role) || role === "judge" });
  const mine = useQuery({ queryKey: ["assign-mine", s.event_id], queryFn: () => api.judging.mine(s.event_id), enabled: role === "judge" });
  const all = useQuery({ queryKey: ["scores-all", s.id], queryFn: () => api.judging.allScores(s.id), enabled: isStaff(role), retry: false });
  const assigned = mine.data?.find((a) => a.submission_id === s.id);
  const links = [{ url: s.repo_url, label: "Repository", icon: GitBranch }, { url: s.live_url, label: "Live demo", icon: Globe }, { url: s.video_url, label: "Demo video", icon: PlayCircle }].filter((l) => safeHref(l.url));
  return (
    <div className="space-y-14">
      <Link href={`/events/${s.event_id}/gallery`} className="label flex items-center gap-2 hover:text-ink"><ArrowLeft size={13} /> {ev.data?.name ?? "Gallery"}</Link>
      <section className="grid gap-10 lg:grid-cols-[1.1fr_1fr]">
        <div className="panel ticks fade-up aspect-[4/3] overflow-hidden">{s.thumbnail_url ? // eslint-disable-next-line @next/next/no-img-element
          <img src={safeHref(s.thumbnail_url)} alt="" className="h-full w-full object-cover" /> : <Cover seed={s.id + (s.name || "untitled")} label={s.name} rounded={false} />}</div>
        <div className="flex flex-col justify-center">
          <div className="fade-up mb-5 flex flex-wrap items-center gap-2">{ev.data && <StatusChip status={ev.data.status} />}{s.track_name && <span className="chip">{s.track_name}</span>}{s.status === "draft" && <span className="chip chip-signal">draft — only your team sees this</span>}</div>
          <h1 className="display fade-up text-[clamp(3.4rem,7vw,6.4rem)]" style={{ ["--i" as string]: 1 } as React.CSSProperties}>{s.name || "Untitled"}</h1>
          <p className="fade-up mt-4 text-xl text-ink2" style={{ ["--i" as string]: 2 } as React.CSSProperties}>{s.tagline}</p>
          <div className="fade-up mt-7 flex flex-wrap gap-3" style={{ ["--i" as string]: 3 } as React.CSSProperties}>{links.map((l) => <a key={l.label} href={safeHref(l.url)} target="_blank" rel="noopener noreferrer" className="btn"><l.icon size={14} /> {l.label} <ExternalLink size={11} className="text-ink3" /></a>)}
            {assigned && <Link href={`/events/${s.event_id}/judge/${s.id}`} className="btn btn-primary"><Gavel size={14} /> Score this</Link>}</div>
          <div className="fade-up mt-8 flex flex-wrap items-center gap-6" style={{ ["--i" as string]: 4 } as React.CSSProperties}>
            <div><div className="label mb-1">Team</div><div className="text-[15px]">{s.team_name}</div></div>
            <div className="flex -space-x-2">{s.members?.map((m) => <Avatar key={m.user_id} name={m.name} size={34} />)}</div>
            <div><div className="label mb-1">Votes</div>{votes.data?.hidden ? <span className="chip"><EyeOff size={11} /> hidden while voting</span> : <span className="cond text-3xl">{votes.data?.count ?? "—"}</span>}</div>
          </div>
          {s.tags.length > 0 && <div className="mt-6 flex flex-wrap gap-2">{s.tags.map((t) => <span key={t} className="chip chip-amber">#{t}</span>)}</div>}
        </div>
      </section>

      <section className="grid gap-10 lg:grid-cols-[1.4fr_1fr]">
        <div><SectionLabel>About</SectionLabel><div className="space-y-4 text-[16px] leading-relaxed text-ink2">{s.description.split("\n\n").map((p, i) => <p key={i}>{p}</p>)}</div>
          {Object.keys(s.custom_answers).length > 0 && ev.data && <div className="mt-10"><SectionLabel>From the team</SectionLabel><dl className="space-y-5">{ev.data.custom_questions.filter((q) => s.custom_answers[q.id]).map((q) => <div key={q.id}><dt className="label mb-1">{q.label}</dt><dd className="text-[15px]">{s.custom_answers[q.id]}</dd></div>)}</dl></div>}
        </div>
        <div>
          {isStaff(role) && (
            <div className="panel mb-8 p-5"><div className="label mb-4 text-amberink">Organiser view · judge scores</div>
              <Q q={all} skeleton={<LoadingBlock rows={2} />}>{(d) => d.length ? <div className="space-y-4">{d.map((j) => <div key={j.judge_id}><div className="mb-1.5 text-[13px]">{j.judge_name}</div><div className="flex gap-1.5">{crit.data?.map((c) => { const sc = j.scores.find((x) => x.criterion_id === c.id); return <span key={c.id} title={c.name} className={`grid h-8 w-8 place-items-center border text-sm ${sc ? "border-amber text-amberink" : "border-line text-ink3"}`}>{sc?.value ?? "·"}</span>; })}</div></div>)}</div> : <p className="text-[13px] text-ink3">No judge has scored this yet.</p>}</Q></div>
          )}
          <Comments sid={s.id} authed={authed} />
        </div>
      </section>
    </div>
  );
}

function Comments({ sid, authed }: { sid: string; authed: boolean }) {
  const q = useQuery({ queryKey: ["comments", sid], queryFn: () => api.comments.list(sid) }); const qc = useQueryClient(); const act = useAct(); const [body, setBody] = useState("");
  const post = async (e: React.FormEvent) => { e.preventDefault(); const r = await act(() => api.comments.add(sid, body)); if (r) { setBody(""); qc.invalidateQueries({ queryKey: ["comments", sid] }); } };
  return (
    <div><SectionLabel>Discussion</SectionLabel>
      {authed ? <form onSubmit={post} className="mb-6"><textarea className="textarea !min-h-[84px]" placeholder="Say something useful — praise counts." value={body} onChange={(e) => setBody(e.target.value)} maxLength={800} /><div className="mt-2 flex items-center justify-between"><span className="label">{body.length}/800</span><button className="btn btn-sm btn-primary" disabled={!body.trim()}><Send size={12} /> Post</button></div></form>
        : <p className="mb-6 text-[13.5px] text-ink3"><Link href={`/login?next=${encodeURIComponent(typeof window !== "undefined" ? location.pathname : "/")}`} className="link-u text-amberink">Sign in</Link> to comment.</p>}
      <Q q={q} skeleton={<LoadingBlock rows={2} />}>{(d) => d.length ? <ul className="space-y-5">{d.map((c) => <li key={c.id} className="flex gap-3"><Avatar name={c.user_name} size={30} /><div><div className="flex items-baseline gap-2"><span className="text-[13.5px] font-medium">{c.user_name}</span><span className="label">{timeAgo(c.created_at)}</span></div><p className="mt-1 text-[14px] text-ink2">{c.body}</p></div></li>)}</ul> : <Empty title="No comments yet" body="Be the first." />}</Q>
    </div>
  );
}
