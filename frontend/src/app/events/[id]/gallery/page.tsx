"use client";
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { api } from "@/lib/api";
import { isStaff } from "@/lib/auth";
import { useEventCtx } from "@/components/EventContext";
import { SubmissionCard } from "@/components/SubmissionCard";
import { Empty, Q, Segmented, Skeleton } from "@/components/ui";

export default function Gallery() {
  const { event: e, role } = useEventCtx();
  const [q, setQ] = useState(""); const [dq, setDq] = useState(""); const [track, setTrack] = useState(""); const [tag, setTag] = useState(""); const [sort, setSort] = useState<"new" | "name">("new"); const [drafts, setDrafts] = useState(false);
  useEffect(() => { const t = setTimeout(() => setDq(q), 250); return () => clearTimeout(t); }, [q]);
  const tracks = useQuery({ queryKey: ["tracks", e.id], queryFn: () => api.events.tracks(e.id) });
  const all = useQuery({ queryKey: ["gallery", e.id, "all", drafts], queryFn: () => api.subs.gallery(e.id, { limit: 200, include_drafts: drafts ? 1 : undefined }) });
  const list = useQuery({ queryKey: ["gallery", e.id, dq, track, tag, sort, drafts], queryFn: () => api.subs.gallery(e.id, { q: dq, track, tag, sort: sort === "name" ? "name" : undefined, limit: 200, include_drafts: drafts ? 1 : undefined }), placeholderData: (p) => p });
  const tagCounts = useMemo(() => { const m = new Map<string, number>(); all.data?.items.forEach((s) => s.tags.forEach((t) => m.set(t, (m.get(t) ?? 0) + 1))); return [...m.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12); }, [all.data]);

  return (
    <div>
      <div className="mb-8 grid gap-4 lg:grid-cols-[1fr_auto] lg:items-center">
        <div className="relative"><Search size={15} className="absolute left-4 top-1/2 -translate-y-1/2 text-ink3" /><input className="input !pl-11" placeholder="Search projects, teams, tags…" value={q} onChange={(ev) => setQ(ev.target.value)} aria-label="Search projects" /></div>
        <div className="flex flex-wrap items-center gap-3"><Segmented value={sort} onChange={setSort} options={[{ value: "new", label: "Newest" }, { value: "name", label: "A–Z" }]} />
          {isStaff(role) && <label className="chip cursor-pointer"><input type="checkbox" className="accent-[var(--amber)]" checked={drafts} onChange={(x) => setDrafts(x.target.checked)} /> include drafts</label>}</div>
      </div>
      <div className="mb-8 flex flex-wrap gap-2">
        <button className={`chip ${!track ? "chip-on" : ""}`} onClick={() => setTrack("")}>all tracks</button>
        {tracks.data?.map((t) => <button key={t.id} className={`chip ${track === t.id ? "chip-on" : ""}`} onClick={() => setTrack(track === t.id ? "" : t.id)}>{t.name}</button>)}
        <span className="mx-2 w-px bg-line2" />
        {tagCounts.map(([t, n]) => <button key={t} className={`chip ${tag === t ? "chip-amber" : ""}`} onClick={() => setTag(tag === t ? "" : t)}>#{t} <span className="text-ink3">{n}</span></button>)}
      </div>
      <Q q={list} skeleton={<div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">{Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-[330px]" />)}</div>}>
        {(d) => d.items.length ? (
          <>
            <div className="label mb-5">{d.total} project{d.total === 1 ? "" : "s"}{dq || track || tag ? " match" : ""}</div>
            <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">{d.items.map((s, i) => <SubmissionCard key={s.id} s={s} index={i} href={`/submissions/${s.id}`} />)}</div>
          </>
        ) : <Empty title={dq || track || tag ? "Nothing matches" : "No submissions yet"} body={dq || track || tag ? "Loosen a filter — or clear them all." : "Projects appear here the moment a team submits. Drafts stay private."} action={(dq || track || tag) ? <button className="btn" onClick={() => { setQ(""); setTrack(""); setTag(""); }}>Clear filters</button> : undefined} />}
      </Q>
    </div>
  );
}
