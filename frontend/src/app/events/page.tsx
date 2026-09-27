"use client";
import Link from "next/link";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Plus } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { fmtDate } from "@/lib/utils";
import { EVENT_STATUSES, type EventStatus } from "@/lib/types";
import { Cover } from "@/components/Cover";
import { Countdown } from "@/components/SplitFlap";
import { Empty, PageHead, Q, StatusChip, Skeleton } from "@/components/ui";

export default function EventsPage() {
  const q = useQuery({ queryKey: ["events"], queryFn: () => api.events.list() });
  const { me } = useAuth(); const [f, setF] = useState<EventStatus | "all">("all");
  const canCreate = !!me && (me.user.is_admin || me.roles.some((r) => r.role === "organizer"));
  return (
    <>
      <PageHead kicker="Directory" title={<>Every event, <em>one board.</em></>} sub="Open events take teams and submissions. Judging and voting events show their gallery; results stay sealed until an organiser publishes."
        actions={canCreate ? <Link href="/events/new" className="btn btn-primary"><Plus size={14} /> New event</Link> : undefined} />
      <div className="mb-8 flex flex-wrap gap-2">
        {(["all", ...EVENT_STATUSES] as const).map((s) => <button key={s} onClick={() => setF(s)} className={`chip ${f === s ? "chip-on" : ""}`}>{s}</button>)}
      </div>
      <Q q={q} skeleton={<div className="grid gap-6 md:grid-cols-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-[380px]" />)}</div>}>
        {(d) => {
          const items = d.items.filter((e) => f === "all" || e.status === f);
          if (!items.length) return <Empty title="Nothing on this board" body="No events match that status yet." />;
          return (
            <div className="grid gap-6 md:grid-cols-2">
              {items.map((e, i) => (
                <Link key={e.id} href={`/events/${e.id}`} className="panel hover-lift fade-up group block overflow-hidden" style={{ ["--i" as string]: i } as React.CSSProperties}>
                  <div className="relative h-44 overflow-hidden border-b border-line"><div className="h-full transition-transform duration-700 group-hover:scale-105"><Cover seed={e.name} label={e.name} rounded={false} /></div>
                    <div className="absolute left-4 top-4"><StatusChip status={e.status} /></div>
                    <ArrowUpRight className="absolute right-4 top-4 text-ink3 transition-all group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-amberink" size={20} /></div>
                  <div className="p-6">
                    <h2 className="display text-[2.6rem]">{e.name}</h2><p className="mt-2 text-[14px] text-ink2">{e.tagline}</p>
                    <div className="mt-6 flex flex-wrap items-end justify-between gap-4">
                      <div className="flex gap-6"><div><div className="cond text-3xl">{String(e.submission_count ?? 0).padStart(2, "0")}</div><div className="label">projects</div></div><div><div className="cond text-3xl">{String(e.team_count ?? 0).padStart(2, "0")}</div><div className="label">teams</div></div>
                        <div><div className="cond text-3xl">${e.prizes.reduce((a, p) => a + p.amount, 0)}</div><div className="label">prizes</div></div></div>
                      {e.status === "open" ? <div><div className="label mb-2">closes in</div><Countdown to={e.deadline_at} size={1.15} labels={false} /></div> : <div className="label">closed {fmtDate(e.deadline_at)}</div>}
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          );
        }}
      </Q>
    </>
  );
}
