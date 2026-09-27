"use client";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Gavel, Users, FilePenLine, Scale, Vote, Trophy, Settings2, Award } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useEventCtx } from "@/components/EventContext";
import { SplitFlap } from "@/components/SplitFlap";
import { SectionLabel, Stat } from "@/components/ui";
import { fmtDateTime, money, cn } from "@/lib/utils";
import { EVENT_STATUSES } from "@/lib/types";

const STAGE_LABEL: Record<string, string> = { draft: "Draft", open: "Building", judging: "Judging", voting: "Voting", published: "Published", archived: "Archived" };

export default function Overview() {
  const { event: e, role } = useEventCtx(); const { authed, me } = useAuth();
  const tracks = useQuery({ queryKey: ["tracks", e.id], queryFn: () => api.events.tracks(e.id) });
  const mine = useQuery({ queryKey: ["assign-mine", e.id], queryFn: () => api.judging.mine(e.id), enabled: role === "judge" });
  const idx = EVENT_STATUSES.indexOf(e.status); const b = `/events/${e.id}`;
  const done = mine.data?.filter((a) => a.complete).length ?? 0;

  const cta: { icon: React.ElementType; title: string; body: string; href: string; label: string }[] = [];
  if (role === "visitor") cta.push({ icon: Users, title: "Join this event", body: "Create an account, then form a team or accept an invite.", href: `/signup?next=${b}/team`, label: "Create account" });
  if (role === "participant") cta.push({ icon: FilePenLine, title: "Your submission", body: "Autosaving drafts, a checklist, and a hard deadline.", href: `${b}/submit`, label: "Open editor" }, { icon: Users, title: "Your team", body: "Invite link, members, capacity.", href: `${b}/team`, label: "Manage team" });
  if (role === "judge") cta.push({ icon: Gavel, title: "Judge desk", body: mine.data ? `${done} of ${mine.data.length} assigned projects fully scored.` : "Your assigned projects only.", href: `${b}/judge`, label: "Start scoring" });
  if (role === "organizer" || role === "admin") cta.push(
    { icon: Scale, title: "Rubric & assignment", body: "Weights, judges, and who reviews what.", href: `${b}/rubric`, label: "Configure" },
    { icon: Trophy, title: "Results", body: "Raw vs normalised, with the proof.", href: `${b}/results`, label: "Open results" },
    { icon: Settings2, title: "Event settings", body: "Dates, lifecycle status, tracks, roles.", href: `${b}/settings`, label: "Settings" });
  if (e.status === "published" && me && (role === "participant" || role === "judge")) cta.push({ icon: Award, title: "Your certificate", body: "Verifiable, print-ready, yours to keep.", href: `${b}/certificate/${me.user.id}`, label: "View certificate" });
  if (e.status === "voting") cta.push({ icon: Vote, title: "Cast your ballot", body: "Order is shuffled per voter. Counts stay hidden until the window closes.", href: `${b}/vote`, label: "Open ballot" });

  return (
    <div className="space-y-16">
      <section>
        <div className="mb-10 grid grid-cols-2 gap-px border border-line bg-line sm:grid-cols-5">
          {EVENT_STATUSES.slice(0, 5).map((s, i) => (
            <div key={s} className={cn("bg-bg2 p-4", i === idx && "!bg-[color-mix(in_srgb,var(--amber)_10%,var(--bg2))]")}>
              <div className="flex items-center justify-between"><span className={cn("cond text-3xl", i === idx ? "amber" : i < idx ? "text-ink2" : "text-ink3")}>{String(i + 1).padStart(2, "0")}</span>{i < idx && <span className="text-ok text-xs">✓</span>}{i === idx && <span className="pulse-dot amber" />}</div>
              <div className="label mt-3">{STAGE_LABEL[s]}</div>
            </div>
          ))}
        </div>
        <div className="grid gap-10 lg:grid-cols-[1.5fr_1fr]">
          <div>
            <SectionLabel>Brief</SectionLabel>
            <div className="space-y-4 text-[16px] leading-relaxed text-ink2">{e.description.split("\n\n").map((p, i) => <p key={i} className={i === 0 ? "text-[19px] text-ink" : ""}>{p}</p>)}</div>
            <dl className="mt-8 grid grid-cols-2 gap-4 sm:grid-cols-3">
              <div><dt className="label">Starts</dt><dd className="mt-1 text-sm">{fmtDateTime(e.starts_at)}</dd></div>
              <div><dt className="label">Submissions close</dt><dd className="mt-1 text-sm">{fmtDateTime(e.deadline_at)}</dd></div>
              <div><dt className="label">Team size</dt><dd className="mt-1 text-sm">up to {e.team_size_max}</dd></div>
              {e.voting_opens_at && <div><dt className="label">Voting</dt><dd className="mt-1 text-sm">{fmtDateTime(e.voting_opens_at)} → {fmtDateTime(e.voting_closes_at)}</dd></div>}
              <div><dt className="label">Ballot</dt><dd className="mt-1 text-sm">{e.voting_mode === "quadratic" ? "Quadratic credits" : e.voting_mode === "auth" ? "Signed-in voters" : e.voting_mode === "email" ? "Email-gated" : "Open link"}</dd></div>
            </dl>
          </div>
          <div className="grid content-start grid-cols-2 gap-4"><Stat label="Projects" value={String(e.submission_count ?? 0).padStart(2, "0")} accent /><Stat label="Teams" value={String(e.team_count ?? 0).padStart(2, "0")} />
            <div className="panel col-span-2 p-5"><div className="label mb-3">Tracks</div>
              {tracks.data?.length ? <ul className="space-y-3">{tracks.data.map((t) => <li key={t.id}><div className="text-[14px]">{t.name}</div><div className="text-[12.5px] text-ink3">{t.description}</div></li>)}</ul> : <div className="text-sm text-ink3">{tracks.isLoading ? "Loading…" : "No tracks — single open field."}</div>}</div>
          </div>
        </div>
      </section>

      {cta.length > 0 && (
        <section><SectionLabel>{authed ? "Your next move" : "Get started"}</SectionLabel>
          <div className="grid gap-px border border-line bg-line md:grid-cols-3">
            {cta.map((c, i) => (
              <Link key={c.title} href={c.href} className="fade-up group flex flex-col justify-between gap-8 bg-bg2 p-7 transition-colors hover:bg-panel" style={{ ["--i" as string]: i } as React.CSSProperties}>
                <div><c.icon size={20} className="mb-5 text-amberink" /><h3 className="display text-4xl">{c.title}</h3><p className="mt-2 text-[14px] text-ink2">{c.body}</p></div>
                <span className="label flex items-center gap-2 text-ink group-hover:text-amberink">{c.label} <ArrowRight size={13} className="transition-transform group-hover:translate-x-1" /></span>
              </Link>
            ))}
          </div>
        </section>
      )}

      {e.prizes.length > 0 && (
        <section><SectionLabel>Prize board</SectionLabel>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {e.prizes.map((p, i) => (
              <div key={i} className="panel ticks fade-up p-5" style={{ ["--i" as string]: i } as React.CSSProperties}>
                <div className="label mb-4 flex justify-between"><span>{p.place}</span><span>{p.name}</span></div>
                <SplitFlap text={money(p.amount)} size={2.4} color={i === 0 ? "amber" : "ivory"} pad={5} padSide="start" />
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
