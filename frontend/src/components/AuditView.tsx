"use client";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ShieldAlert, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { Avatar, Empty, Q, RoleBadge, Skeleton } from "./ui";
import { fmtDateTime, timeAgo } from "@/lib/utils";
import type { AuditEntry, Role } from "@/lib/types";

const VERB: Record<string, string> = {
  "auth.login": "signed in", "auth.signup": "created an account", "event.create": "created an event", "event.update": "edited event settings", "event.status": "changed the event stage", "results.publish": "published results",
  "rubric.configure": "tried to configure the rubric", "rubric.criterion.create": "added a rubric criterion", "rubric.criterion.delete": "removed a rubric criterion", "judging.assign": "assigned judges",
  "judging.normalize": "ran score normalisation", "score.upsert": "recorded a score", "scores.read": "tried to read another judge's scores", "results.read": "tried to open sealed results",
  "submission.create": "started a draft", "submission.update": "edited a submission", "submission.submit": "submitted a project", "vote.cast": "cast a vote", "role.grant": "granted a role", "team.create": "created a team", "team.join": "joined a team",
  "comment.create": "commented on", "export.csv": "exported results as CSV", "export.json": "exported an event dump", "import.json": "imported an event dump", "webhook.subscribe": "registered a webhook", "track.create": "added a track",
  "pairwise.vote": "settled a duel", "drafts.read": "tried to read drafts", "audit.read": "tried to read the audit log", "roles.read": "tried to read the role list", "assignments.read": "tried to read assignments",
};
const ACTIONS = ["", "auth", "event", "judging", "score", "submission", "vote", "role", "results", "export"];

export function AuditView({ eventId }: { eventId?: string }) {
  const [page, setPage] = useState(1); const [outcome, setOutcome] = useState(""); const [action, setAction] = useState(""); const [actor, setActor] = useState("");
  const q = useQuery({ queryKey: ["audit", eventId, page, outcome, action, actor], queryFn: () => api.audit.list({ page, limit: 20, outcome, action, actor, event_id: eventId }), placeholderData: (p) => p, retry: false });
  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center gap-3">
        {["", "ok", "denied"].map((o) => <button key={o} onClick={() => { setOutcome(o); setPage(1); }} className={`chip ${outcome === o ? (o === "denied" ? "chip-signal" : "chip-on") : ""}`}>{o || "all outcomes"}</button>)}
        <select className="select !w-auto !py-2 text-[12px]" value={action} onChange={(e) => { setAction(e.target.value); setPage(1); }} aria-label="Action filter">{ACTIONS.map((a) => <option key={a} value={a}>{a ? `${a}.*` : "any action"}</option>)}</select>
        <input className="input !w-56 !py-2 text-[13px]" placeholder="Filter by person…" value={actor} onChange={(e) => { setActor(e.target.value); setPage(1); }} aria-label="Filter by actor" />
      </div>
      <Q q={q} skeleton={<div className="space-y-2">{Array.from({ length: 8 }).map((_, i) => <Skeleton key={i} className="h-14" />)}</div>}>
        {(d) => !d.items.length ? <Empty title="No entries" body="Nothing matches those filters." /> : (
          <>
            <ol className="panel divide-y divide-line">{d.items.map((a) => <Row key={a.id} a={a} />)}</ol>
            <div className="mt-5 flex items-center justify-between"><span className="label">{d.total} entries · page {d.page} / {Math.max(1, Math.ceil(d.total / d.limit))}</span>
              <div className="flex gap-2"><button className="btn btn-sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Prev</button><button className="btn btn-sm" disabled={page * d.limit >= d.total} onClick={() => setPage((p) => p + 1)}>Next</button></div></div>
          </>
        )}
      </Q>
    </div>
  );
}

function Row({ a }: { a: AuditEntry }) {
  const denied = a.outcome === "denied";
  return (
    <li className="relative grid items-center gap-4 px-5 py-4 md:grid-cols-[2rem_1fr_auto]" style={denied ? { background: "color-mix(in srgb, var(--signal) 6%, transparent)" } : undefined}>
      {denied && <i className="absolute inset-y-0 left-0 w-[3px] bg-signal" />}
      <span className="hidden md:block">{denied ? <ShieldAlert size={17} className="text-signal" /> : <ShieldCheck size={17} className="text-ink3" />}</span>
      <div className="min-w-0"><p className="text-[14.5px]"><span className="inline-flex items-center gap-2 align-middle"><Avatar name={a.actor_name} size={22} /><b className="font-medium">{a.actor_name}</b></span> <RoleBadge role={a.actor_role as Role} /> <span className="text-ink2">{VERB[a.action] ?? a.action}</span> <span className="text-ink3">—</span> <span className="text-ink">{a.target}</span></p>
        {a.detail && <p className="mono mt-1 text-[11px]" style={{ color: denied ? "var(--signal)" : "var(--ink3)" }}>{a.detail}</p>}</div>
      <div className="text-right"><span className={`chip ${denied ? "chip-signal" : "chip-ok"}`}>{a.outcome}</span><div className="label mt-1.5" title={fmtDateTime(a.at)}>{timeAgo(a.at)}</div></div>
    </li>
  );
}
