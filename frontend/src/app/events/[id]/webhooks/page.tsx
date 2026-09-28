"use client";
import { useState } from "react";
import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Copy, KeyRound, Plus, Send, Trash2, Webhook } from "lucide-react";
import { api } from "@/lib/api";
import { useAct } from "@/lib/act";
import { Gate } from "@/components/EventContext";
import { Empty, Field, PageHead, Q, SectionLabel } from "@/components/ui";
import { copyText, timeAgo } from "@/lib/utils";
import type { Webhook as Hook, WebhookDelivery } from "@/lib/types";

const TYPES = ["submission.submitted", "team.created", "vote.cast", "comment.added", "judging.normalized", "event.status_changed", "results.published", "certificate.issued"];

export default function WebhooksPage() { return <Gate allow={["organizer"]} what="Webhooks are configured by organisers."><Inner /></Gate>; }

function DeliveryLog({ id }: { id: string }) {
  const q = useQuery({ queryKey: ["hook-log", id], queryFn: () => api.hooks.deliveries(id), refetchInterval: 4000 });
  const rows: WebhookDelivery[] = q.data ?? [];
  if (!rows.length) return <p className="label mt-3">No deliveries yet. Use “Send test”.</p>;
  return (
    <ul className="mt-3 space-y-1.5" data-testid="delivery-log">
      {rows.slice(0, 8).map((d) => (
        <li key={d.id} className="mono flex flex-wrap items-center gap-x-3 text-[11.5px]">
          <span className={d.status === "success" ? "text-ok" : d.status === "dead" ? "text-signal" : "text-amberink"}>{d.status}</span>
          <span>{d.event_type}</span><span className="text-ink3">{d.response_status ? `HTTP ${d.response_status}` : d.last_error ?? "queued"} · {d.attempts} attempt{d.attempts === 1 ? "" : "s"}</span>
        </li>
      ))}
    </ul>
  );
}

function Inner() {
  const { id: eventId } = useParams<{ id: string }>();
  const qc = useQueryClient(); const act = useAct();
  const q = useQuery({ queryKey: ["hooks", eventId], queryFn: () => api.hooks.list(eventId) });
  const [url, setUrl] = useState(""); const [types, setTypes] = useState<string[]>(["submission.submitted"]);
  const [secret, setSecret] = useState<{ url: string; value: string } | null>(null); const [copied, setCopied] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const refresh = () => qc.invalidateQueries({ queryKey: ["hooks", eventId] });
  const add = async (ev: React.FormEvent) => {
    ev.preventDefault();
    const r = await act(() => api.hooks.subscribe({ url, event_types: types, event_id: eventId }), "Webhook registered");
    if (r) { setUrl(""); setSecret(r.secret ? { url: r.url, value: r.secret } : null); refresh(); }
  };
  const del = async (h: Hook) => { const r = await act(() => api.hooks.remove(h.id), "Webhook removed"); if (r) refresh(); };
  const ping = async (h: Hook) => { const r = await act(() => api.hooks.ping(h.id), "Test delivery queued"); if (r) { setOpen(h.id); qc.invalidateQueries({ queryKey: ["hook-log", h.id] }); } };
  return (
    <div>
      <PageHead kicker="Integrations" title={<>Tell your other tools <em>when.</em></>} sub="Register an endpoint and pick the events it should hear about. We POST signed JSON, retry failures with backoff, and switch off endpoints that stay broken." />
      <div className="grid gap-8 lg:grid-cols-[1.4fr_1fr]">
        <div className="space-y-6">
          {secret && (
            <div className="panel ticks border-amber p-5" data-testid="webhook-secret">
              <div className="label mb-2 flex items-center gap-2 text-amberink"><KeyRound size={13} /> Signing secret for {secret.url} — shown once</div>
              <div className="flex gap-2"><code className="mono block min-w-0 flex-1 overflow-x-auto whitespace-nowrap border border-line bg-bg px-3 py-2 text-[12px]">{secret.value}</code>
                <button className="btn" onClick={async () => { await copyText(secret.value); setCopied(true); setTimeout(() => setCopied(false), 1600); }}>{copied ? <Check size={14} color="var(--ok)" /> : <Copy size={14} />}</button></div>
              <p className="mt-2 text-[12px] text-ink3">Store it now: it is never shown again. Verify every request with it (see the payload panel).</p>
            </div>)}
          <Q q={q}>{(hs) => hs.length ? <ul className="space-y-3">{hs.map((h) => (
            <li key={h.id} className="panel p-5" data-testid="webhook-row">
              <div className="flex items-start gap-4"><Webhook size={18} className="mt-1 text-amberink" />
                <div className="min-w-0 flex-1"><div className="mono truncate text-[13px]">{h.url}</div>
                  <div className="mt-2 flex flex-wrap gap-1.5">{h.event_types.map((t) => <span key={t} className="chip chip-amber">{t}</span>)}</div>
                  <div className="label mt-2">added {timeAgo(h.created_at)} · {h.active ? (h.last_status === "failing" ? "failing, retrying" : "active") : "disabled"}{h.disabled_reason ? ` — ${h.disabled_reason}` : ""}</div></div>
                <button className="btn btn-sm" onClick={() => ping(h)} disabled={!h.active} aria-label="Send test delivery"><Send size={13} /> Send test</button>
                <button className="btn btn-ghost btn-icon hover:!text-signal" onClick={() => del(h)} aria-label="Remove webhook"><Trash2 size={15} /></button></div>
              <button className="label mt-3 underline-offset-2 hover:underline" onClick={() => setOpen(open === h.id ? null : h.id)}>{open === h.id ? "Hide" : "Show"} delivery log</button>
              {open === h.id && <DeliveryLog id={h.id} />}
            </li>))}</ul> : <Empty title="No webhooks" body="Nothing is listening yet." />}</Q>
          <div className="panel crt p-6" style={{ background: "#0c0a07", borderColor: "#2b271e" }}><div className="label mb-3 !text-[#7f7868]">Payload &amp; verification</div><pre className="mono overflow-x-auto text-[11.5px] leading-[1.7] text-[#b9b19c]">{`POST https://your.endpoint/hook
X-Dogfood-Event: submission.submitted
X-Dogfood-Delivery: 5b0d…            # same id on every retry: de-duplicate on it
X-Dogfood-Timestamp: 1790518931
X-Dogfood-Signature: sha256=9f2c…    # HMAC-SHA256(secret, "<timestamp>.<body>")

{ "id": "5b0d…", "type": "submission.submitted", "created_at": "2026-09-27T14:02:11Z",
  "event_id": "…", "data": { "submission_id": "…", "name": "…", "team_id": "…" } }

// verify: recompute the HMAC over \`\${timestamp}.\${rawBody}\`, compare in constant time,
// and reject timestamps older than 5 minutes. Respond 2xx; anything else is retried.`}</pre></div>
        </div>
        <form onSubmit={add} className="panel ticks h-fit space-y-5 p-6"><SectionLabel>Subscribe</SectionLabel><Field label="Endpoint URL"><input className="input" value={url} onChange={(x) => setUrl(x.target.value)} placeholder="https://hooks.example.dev/dogfood" /></Field>
          <div><div className="label mb-2">Events</div><div className="flex flex-wrap gap-2">{TYPES.map((t) => <button type="button" key={t} className={`chip ${types.includes(t) ? "chip-on" : ""}`} onClick={() => setTypes((x) => (x.includes(t) ? x.filter((y) => y !== t) : [...x, t]))}>{t}</button>)}</div></div>
          <button className="btn btn-primary w-full" disabled={!url || !types.length}><Plus size={14} /> Register</button></form>
      </div>
    </div>
  );
}
