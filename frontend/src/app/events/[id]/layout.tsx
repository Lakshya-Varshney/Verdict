"use client";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { eventTabs } from "@/lib/nav";
import { EventCtx } from "@/components/EventContext";
import { Countdown, SplitFlap } from "@/components/SplitFlap";
import { ErrorState, RoleBadge, Skeleton } from "@/components/ui";
import { fmtDate } from "@/lib/utils";

export default function EventLayout({ children }: { children: React.ReactNode }) {
  const { id } = useParams<{ id: string }>(); const pathname = usePathname();
  const q = useQuery({ queryKey: ["event", id], queryFn: () => api.events.get(id) });
  const { roleFor } = useAuth();
  if (q.isLoading) return <div className="space-y-4"><Skeleton className="h-6 w-40" /><Skeleton className="h-24 w-2/3" /><Skeleton className="h-10 w-full" /></div>;
  if (q.error || !q.data) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  const e = q.data; const role = roleFor(id); const tabs = eventTabs(id, role, e.status);
  const active = [...tabs].filter((t) => (t.exact ? pathname === t.href : pathname.startsWith(t.href))).sort((a, b) => b.href.length - a.href.length)[0];
  const compact = pathname !== `/events/${id}`;
  const statusColor = e.status === "open" ? "ok" : e.status === "voting" ? "cool" : e.status === "published" ? "signal" : "amber";
  const clock = e.status === "open" ? { to: e.deadline_at, label: "Submissions close in" } : e.status === "voting" ? { to: e.voting_closes_at, label: "Voting closes in" } : null;
  return (
    <EventCtx.Provider value={{ event: e, role }}>
      <header className={compact ? "mb-1" : "mb-2"}>
        <div className="label mb-4 flex items-center gap-2"><Link href="/events" className="link-u hover:text-ink">Events</Link><span>/</span><Link href={`/events/${id}`} className="text-ink2 hover:text-ink">{e.name}</Link></div>
        {compact ? (
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex flex-wrap items-center gap-4"><h1 className="display text-[clamp(2.2rem,4vw,3.2rem)]">{e.name}</h1><SplitFlap text={e.status} pad={9} size={0.95} color={statusColor} framed /><RoleBadge role={role} /></div>
            {clock?.to && <div className="flex items-center gap-4"><span className="label hidden sm:block">{clock.label}</span><Countdown to={clock.to} size={1.15} labels={false} /></div>}
          </div>
        ) : (
        <div className="flex flex-wrap items-end justify-between gap-8">
          <div className="max-w-3xl">
            <div className="fade-up mb-5 flex flex-wrap items-center gap-3"><SplitFlap text={e.status} pad={9} size={1.35} color={statusColor} framed /><RoleBadge role={role} /></div>
            <h1 className="display fade-up text-[clamp(3rem,7vw,6rem)]" style={{ ["--i" as string]: 1 } as React.CSSProperties}>{e.name}</h1>
            <p className="fade-up mt-4 text-lg text-ink2" style={{ ["--i" as string]: 2 } as React.CSSProperties}>{e.tagline}</p>
          </div>
          {clock?.to ? <div className="fade-up" style={{ ["--i" as string]: 3 } as React.CSSProperties}><div className="label mb-3">{clock.label}</div><Countdown to={clock.to} size={2} /></div>
            : <div className="label">{e.status === "published" ? "Closed" : "Deadline"} · {fmtDate(e.deadline_at)}</div>}
        </div>
        )}
      </header>
      <div className={`no-print sticky top-[68px] z-40 -mx-5 mb-10 ${compact ? "mt-4" : "mt-8"} border-b border-line bg-[color-mix(in_srgb,var(--bg)_88%,transparent)] px-5 backdrop-blur-xl`}>
        <nav className="tabs" aria-label="Event sections">
          {tabs.map((t) => <Link key={t.key} href={t.href} className={`tab ${active?.key === t.key ? "on" : ""}`} aria-current={active?.key === t.key ? "page" : undefined}>{t.label}</Link>)}
        </nav>
      </div>
      {children}
    </EventCtx.Provider>
  );
}
