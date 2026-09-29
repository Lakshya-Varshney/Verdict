"use client";
import { useRef, useState } from "react";
import { Braces, Check, Copy, Download, Puzzle, Upload } from "lucide-react";
import { api, USE_MOCK } from "@/lib/api";
import { useAct } from "@/lib/act";
import { Gate, useEventCtx } from "@/components/EventContext";
import { PageHead, SectionLabel } from "@/components/ui";
import { copyText, downloadBlob } from "@/lib/utils";
import { useQueryClient } from "@tanstack/react-query";
import { useToast } from "@/components/toast";
import type { ImportResult } from "@/lib/types";

export default function DataPage() { return <Gate allow={["organizer"]} what="Import, export and embeds are organiser tools."><Inner /></Gate>; }

function Inner() {
  const { event: e } = useEventCtx(); const act = useAct(); const toast = useToast(); const qc = useQueryClient(); const file = useRef<HTMLInputElement>(null); const [copied, setCopied] = useState(false); const [imported, setImported] = useState<ImportResult | null>(null); const [dry, setDry] = useState(false);
  const origin = typeof window !== "undefined" ? location.origin : ""; const snippet = `<script src="${origin}/api/embed.js" data-event="${e.id}" data-theme="dark" data-limit="12"></script>`;
  const exp = async () => { const d = await act(() => api.data.export(e.id), "Export ready"); if (d) downloadBlob(new Blob([JSON.stringify(d, null, 2)], { type: "application/json" }), `${e.id}-dump.json`); };
  const imp = async (f: File | undefined) => { if (!f) return; let json: unknown; try { json = JSON.parse(await f.text()); } catch { toast("That file isn't valid JSON.", "error"); return; } const r = await act(() => api.data.import(e.id, json, dry), dry ? "Dump is valid — nothing was written" : "Import complete"); if (r) { setImported(r); if (!dry) qc.invalidateQueries(); } };
  return (
    <div>
      <PageHead kicker="Adoptability" title={<>Take it with you. <em>Or leave.</em></>} sub="A platform you can't leave is a trap. Everything here is a plain file or a snippet — no vendor format, no support ticket." />
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="panel ticks p-7"><Braces size={20} className="mb-4 text-amberink" /><h3 className="display text-4xl">Full export</h3><p className="mt-2 text-[14px] text-ink2">Event, tracks, rubric, teams, submissions, assignments and scores in one JSON document.</p><button className="btn btn-primary mt-6" onClick={exp}><Download size={14} /> Download JSON</button></div>
        <div className="panel p-7"><Upload size={20} className="mb-4 text-amberink" /><h3 className="display text-4xl">Import</h3><p className="mt-2 text-[14px] text-ink2">Restore from a dump. Records upsert by ID, so re-importing is safe.</p>
          <input ref={file} type="file" accept="application/json" className="hidden" onChange={(x) => { const f = x.target.files?.[0]; x.target.value = ""; imp(f); }} /><button className="btn mt-6" onClick={() => file.current?.click()}><Upload size={14} /> Choose file…</button>
          <label className="mt-4 flex items-center gap-2 text-[12.5px] text-ink2"><input type="checkbox" checked={dry} onChange={(x) => setDry(x.target.checked)} /> Validate only (dry run)</label>
          {imported && <p className="mono mt-4 text-[12px] text-ok">{imported.dry_run ? "Would import" : "Imported"}: {Object.entries(imported.imported).filter(([, v]) => v > 0).map(([k, v]) => `${v} ${k}`).join(" · ")}{imported.checksum_verified ? " · checksum ✓" : ""}</p>}
          {imported?.warnings?.map((w) => <p key={w} className="mt-2 text-[12px] text-signal">⚠ {w}</p>)}</div>
        <div className="panel p-7 lg:col-span-2"><Puzzle size={20} className="mb-4 text-amberink" /><h3 className="display text-4xl">Embeddable gallery</h3><p className="mt-2 max-w-2xl text-[14px] text-ink2">Drop the submitted-projects gallery on any site. Read-only, no cookies, follows your theme.</p>
          <div className="mt-5 flex gap-2"><code className="mono block min-w-0 flex-1 overflow-x-auto whitespace-nowrap border border-line bg-bg px-4 py-3 text-[11.5px] text-ink2">{snippet}</code><button className="btn" aria-label={copied ? "Copied" : "Copy embed snippet"} onClick={async () => { await copyText(snippet); setCopied(true); setTimeout(() => setCopied(false), 1600); }}>{copied ? <Check size={14} color="var(--ok)" /> : <Copy size={14} />}</button></div>
          <div className="mt-6 overflow-hidden border border-line2"><iframe title="Embed preview" src={`/api/embed/${e.id}`} className="h-[420px] w-full bg-bg" /></div></div>
        <div className="panel p-7 lg:col-span-2"><SectionLabel>API</SectionLabel><p className="text-[14px] text-ink2">Everything this UI does is in the OpenAPI spec. {USE_MOCK ? "You're on the mock API — point at FastAPI to browse the live spec at /backend-docs." : <>Browse it at <a className="link-u text-amberink" href="/backend-docs">/backend-docs</a>.</>}</p>
          <pre className="mono mt-4 overflow-x-auto border border-line bg-bg p-4 text-[11.5px] text-ink2">{`curl -H "Authorization: Bearer $TOKEN" \\\n  ${origin}/api/events/${e.id}/judging/export.csv > results.csv`}</pre></div>
      </div>
    </div>
  );
}
