"use client";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Circle, Lock, Rocket } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useAct } from "@/lib/act";
import { Gate, useEventCtx } from "@/components/EventContext";
import { Countdown, SplitFlap, useCountdown } from "@/components/SplitFlap";
import { SubmissionCard } from "@/components/SubmissionCard";
import { Empty, Field, LoadingBlock, Q, SectionLabel, TagInput } from "@/components/ui";
import { useToast } from "@/components/toast";
import { cn } from "@/lib/utils";
import type { EventT, Submission, Track } from "@/lib/types";

interface Form { name: string; tagline: string; description: string; track_id: string; thumbnail_url: string; images: string; video_url: string; repo_url: string; live_url: string; tags: string[]; custom_answers: Record<string, string>; }
const toForm = (s: Submission): Form => ({ name: s.name, tagline: s.tagline, description: s.description, track_id: s.track_id ?? "", thumbnail_url: s.thumbnail_url ?? "", images: s.images.join("\n"), video_url: s.video_url, repo_url: s.repo_url, live_url: s.live_url, tags: s.tags, custom_answers: s.custom_answers });
const toPatch = (f: Form) => ({ ...f, track_id: f.track_id || null, thumbnail_url: f.thumbnail_url || null, images: f.images.split("\n").map((x) => x.trim()).filter(Boolean) });

export default function SubmitPage() { return <Gate allow={["participant"]} what="Submissions belong to participant teams."><Inner /></Gate>; }

function Inner() {
  const { event: e } = useEventCtx(); const qc = useQueryClient(); const act = useAct();
  const teams = useQuery({ queryKey: ["team-mine", e.id], queryFn: () => api.teams.mine(e.id) });
  const team = teams.data?.[0];
  const sub = useQuery({ queryKey: ["sub", team?.submission_id], queryFn: () => api.subs.get(team!.submission_id!), enabled: !!team?.submission_id });
  const tracks = useQuery({ queryKey: ["tracks", e.id], queryFn: () => api.events.tracks(e.id) });
  if (teams.isLoading) return <LoadingBlock />;
  if (!team) return <Empty title="Form a team first" body="Submissions belong to teams. Create one or join with an invite link." action={<Link href={`/events/${e.id}/team`} className="btn btn-primary">Go to my team</Link>} />;
  if (!team.submission_id) return (
    <Empty icon={<Rocket size={20} />} title="Nothing started yet" body={`${team.name} has no submission. Start a draft — it autosaves as you type.`}
      action={<button className="btn btn-primary" onClick={async () => { const s = await act(() => api.subs.create(team.id), "Draft created"); if (s) await qc.invalidateQueries({ queryKey: ["team-mine", e.id] }); }}>Start submission</button>} />
  );
  return <Q q={sub}>{(s) => <Editor key={s.id} sub={s} event={e} tracks={tracks.data ?? []} />}</Q>;
}

function Editor({ sub, event, tracks }: { sub: Submission; event: EventT; tracks: Track[] }) {
  const qc = useQueryClient(); const act = useAct(); const toast = useToast();
  const [f, setF] = useState<Form>(() => toForm(sub)); const [status, setStatus] = useState(sub.status);
  const [save, setSave] = useState<"idle" | "dirty" | "saving" | "saved" | "error">("idle"); const [savedAt, setSavedAt] = useState<Date | null>(null);
  const last = useRef(JSON.stringify(toForm(sub)));
  const c = useCountdown(event.deadline_at); const locked = c.over;
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((x) => ({ ...x, [k]: v }));

  useEffect(() => {
    if (locked) return; const cur = JSON.stringify(f); if (cur === last.current) return; setSave("dirty");
    const t = setTimeout(async () => {
      setSave("saving");
      try { const r = await api.subs.update(sub.id, toPatch(f)); last.current = cur; setSave("saved"); setSavedAt(new Date()); qc.setQueryData(["sub", sub.id], r); }
      catch (x) { setSave("error"); toast(x instanceof ApiError ? x.detail : "Autosave failed", "error"); }
    }, 900);
    return () => clearTimeout(t);
  }, [f, locked, sub.id, qc, toast]);

  const checklist = useMemo(() => [
    { ok: !!f.name.trim(), label: "Project name" }, { ok: !!f.tagline.trim(), label: "One-line tagline" }, { ok: f.description.trim().length >= 40, label: `Description, 40+ chars (${f.description.trim().length})` },
    { ok: !!f.repo_url.trim(), label: "Repository URL" }, ...(tracks.length ? [{ ok: !!f.track_id, label: "Track selected" }] : []),
    ...event.custom_questions.filter((q) => q.required).map((q) => ({ ok: !!(f.custom_answers[q.id] ?? "").trim(), label: q.label.length > 42 ? q.label.slice(0, 42) + "…" : q.label })),
  ], [f, tracks.length, event.custom_questions]);
  const ready = checklist.every((x) => x.ok);

  const submit = async () => {
    const r = await act(async () => { await api.subs.update(sub.id, toPatch(f)); last.current = JSON.stringify(f); return api.subs.submit(sub.id); }, "Submitted — you're on the board");
    if (r) { setStatus("submitted"); qc.setQueryData(["sub", sub.id], r); qc.invalidateQueries({ queryKey: ["gallery"] }); }
  };
  const track = tracks.find((t) => t.id === f.track_id);
  const stateLabel = save === "saving" ? "Saving…" : save === "dirty" ? "Unsaved changes" : save === "error" ? "Save failed" : savedAt ? `Saved ${savedAt.toLocaleTimeString("en-GB")}` : "All changes saved";

  return (
    <div className="grid gap-10 lg:grid-cols-[1.5fr_1fr]">
      <div className="space-y-8">
        {locked && <div className="panel overflow-hidden"><div className="hazard h-2.5" /><div className="flex items-center gap-4 p-5"><Lock size={18} className="text-signal" /><div><div className="label text-signal">Locked · deadline passed</div><p className="text-[13.5px] text-ink2">Editing is closed. This is enforced by the API — the form is disabled only as a courtesy.</p></div></div></div>}
        <fieldset disabled={locked} className="space-y-8 border-0 p-0">
          <section className="panel p-7"><SectionLabel n="01">Identity</SectionLabel>
            <div className="space-y-5">
              <Field label="Project name"><input className="input !text-lg" value={f.name} onChange={(x) => set("name", x.target.value)} maxLength={60} placeholder="Plumbline" /></Field>
              <Field label="Tagline" hint={`${f.tagline.length}/90`}><input className="input" value={f.tagline} onChange={(x) => set("tagline", x.target.value)} maxLength={90} placeholder="One sentence a stranger would understand" /></Field>
              {tracks.length > 0 && <Field label="Track"><select className="select" value={f.track_id} onChange={(x) => set("track_id", x.target.value)}><option value="">Choose a track…</option>{tracks.map((t) => <option key={t.id} value={t.id}>{t.name} — {t.description}</option>)}</select></Field>}
              <Field label="Tags" hint="Enter or space to add"><TagInput value={f.tags} onChange={(v) => set("tags", v)} placeholder="fastapi, postgres, z-score…" /></Field>
            </div></section>
          <section className="panel p-7"><SectionLabel n="02">Story</SectionLabel>
            <Field label="Description" hint="Blank line = new paragraph"><textarea className="textarea !min-h-[220px]" value={f.description} onChange={(x) => set("description", x.target.value)} placeholder="What works. What doesn't. What you'd do next." /></Field></section>
          <section className="panel p-7"><SectionLabel n="03">Links & media</SectionLabel>
            <div className="grid gap-5 sm:grid-cols-2">
              <Field label="Repository URL"><input className="input" value={f.repo_url} onChange={(x) => set("repo_url", x.target.value)} placeholder="https://github.com/you/project" /></Field>
              <Field label="Live demo URL" hint="optional"><input className="input" value={f.live_url} onChange={(x) => set("live_url", x.target.value)} /></Field>
              <Field label="Demo video URL" hint="optional"><input className="input" value={f.video_url} onChange={(x) => set("video_url", x.target.value)} /></Field>
              <Field label="Cover image URL" hint="optional — we generate one if empty"><input className="input" value={f.thumbnail_url} onChange={(x) => set("thumbnail_url", x.target.value)} /></Field>
              <Field label="Screenshot URLs" hint="one per line" className="sm:col-span-2"><textarea className="textarea !min-h-[80px]" value={f.images} onChange={(x) => set("images", x.target.value)} /></Field>
            </div></section>
          {event.custom_questions.length > 0 && <section className="panel p-7"><SectionLabel n="04">From the organisers</SectionLabel>
            <div className="space-y-5">{event.custom_questions.map((q) => <Field key={q.id} label={q.label} hint={q.required ? "required" : "optional"}><textarea className="textarea !min-h-[90px]" value={f.custom_answers[q.id] ?? ""} onChange={(x) => set("custom_answers", { ...f.custom_answers, [q.id]: x.target.value })} /></Field>)}</div></section>}
        </fieldset>
      </div>

      <aside className="space-y-6 lg:sticky lg:top-[132px] lg:self-start">
        <div className="panel ticks p-6">
          <div className="mb-4 flex items-center justify-between"><span className="label">Status</span><SplitFlap text={status} pad={9} size={1.1} color={status === "submitted" ? "ok" : "amber"} scramble /></div>
          {!locked && <div className="mb-5"><div className="label mb-2">Deadline in</div><Countdown to={event.deadline_at} size={1.5} labels={false} /></div>}
          <div className={cn("mono mb-5 flex items-center gap-2 text-[11px]", save === "error" ? "text-signal" : "text-ink3")}><span className={cn("pulse-dot", save === "saving" ? "amber" : save === "error" ? "" : "ok")} style={{ width: 6, height: 6 }} />{stateLabel}</div>
          <ul className="mb-6 space-y-2.5">{checklist.map((x) => <li key={x.label} className="flex items-start gap-2.5 text-[13.5px]">{x.ok ? <Check size={15} className="mt-0.5 shrink-0 text-ok" /> : <Circle size={15} className="mt-0.5 shrink-0 text-ink3" />}<span className={x.ok ? "text-ink2" : ""}>{x.label}</span></li>)}</ul>
          <button className="btn btn-primary w-full" disabled={!ready || locked || save === "saving"} onClick={submit}><Rocket size={14} /> {status === "submitted" ? "Update submission" : "Submit to the board"}</button>
          <p className="mt-3 text-[12px] text-ink3">{status === "submitted" ? "You're on the public gallery. Edits stay open until the deadline." : "Drafts are private to your team. Submitting makes it public."}</p>
          {status === "submitted" && <Link href={`/submissions/${sub.id}`} className="btn btn-sm mt-3 w-full">View public page</Link>}
        </div>
        <div><div className="label mb-3">Live preview</div><SubmissionCard preview s={{ id: sub.id, name: f.name, tagline: f.tagline, team_name: sub.team_name, track_name: track?.name ?? null, tags: f.tags, thumbnail_url: f.thumbnail_url || null, status }} /></div>
      </aside>
    </div>
  );
}
