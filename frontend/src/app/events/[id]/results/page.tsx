"use client";
import { useParams } from "next/navigation";
import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Gauge, Megaphone } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { useAuth, isStaff } from "@/lib/auth";
import { useAct } from "@/lib/act";
import { downloadBlob, fmtDateTime } from "@/lib/utils";
import type { Results } from "@/lib/types";
import { BiasBars, ScoreStrip, SlopeChart } from "@/components/Charts";
import { SplitFlap } from "@/components/SplitFlap";
import { Empty, ErrorState, LoadingBlock, Modal, PageHead, Segmented, Stat } from "@/components/ui";

const ROW = 66;

function Sealed() {
  return (
    <div className="panel ticks fade-up mx-auto max-w-2xl overflow-hidden text-center">
      <div className="hazard h-3" />
      <div className="p-10 sm:p-14"><SplitFlap text="SEALED" size={5} color="signal" framed scramble />
        <h2 className="display mt-10 text-5xl">Results are <em style={{ color: "var(--signal)" }}>sealed.</em></h2>
        <p className="mx-auto mt-4 max-w-md text-ink2">Raw and normalised scores stay hidden from judges, participants and the public until the organiser publishes — so nobody can lobby the leaderboard.</p></div>
    </div>
  );
}

function Board({ d, staff, mode, hover, setHover }: { d: Results; staff: boolean; mode: "raw" | "norm"; hover: string | null; setHover: (s: string | null) => void }) {
  const rank = (r: Results["rows"][number]) => (mode === "norm" && r.norm_rank ? r.norm_rank : r.raw_rank);
  return (
    <div className="relative" style={{ height: d.rows.length * ROW }}>
      {d.rows.map((r) => {
        const rk = rank(r); const v = mode === "norm" && r.norm_mean !== null ? r.norm_mean : r.raw_mean; const delta = r.norm_rank ? r.raw_rank - r.norm_rank : 0; const podium = rk <= 3;
        return (
          <div key={r.submission_id} onMouseEnter={() => setHover(r.submission_id)} onMouseLeave={() => setHover(null)}
            className="absolute left-0 right-0 flex items-center gap-4 border bg-bg2 px-4 transition-[transform,border-color] duration-[900ms] [transition-timing-function:cubic-bezier(.7,0,.2,1)]"
            style={{ height: ROW - 8, transform: `translateY(${(rk - 1) * ROW}px)`, borderColor: hover === r.submission_id ? "var(--amber)" : podium ? "color-mix(in srgb, var(--amber) 40%, var(--line))" : "var(--line)" }}>
            <SplitFlap text={String(rk).padStart(2, "0")} size={1.6} color={podium ? "amber" : "ivory"} scramble stagger={30} />
            <div className="min-w-0 flex-1"><div className="truncate font-serif text-[1.65rem] italic leading-none">{r.name}</div><div className="label mt-1.5 truncate">{r.team_name}{r.track_name ? ` · ${r.track_name}` : ""}</div></div>
            {staff && <div className="hidden w-36 lg:block"><ScoreStrip raw={r.scores.map((s) => s.raw)} norm={mode === "norm" ? r.scores.map((s) => s.norm) : undefined} /></div>}
            <div className="hidden w-32 sm:block"><div className="relative h-2 bg-line"><i className="absolute inset-y-0 left-0 bg-amber transition-all duration-[900ms]" style={{ width: `${(v / 5) * 100}%`, boxShadow: "0 0 12px var(--amber)" }} /></div></div>
            <span className="mono w-12 text-right text-[12.5px]">{v.toFixed(2)}</span>
            <span className="mono w-11 text-right text-[11px]" style={{ color: mode === "norm" && delta ? (delta > 0 ? "var(--ok)" : "var(--signal)") : "transparent" }}>{delta > 0 ? "▲" : delta < 0 ? "▼" : "•"}{Math.abs(delta) || ""}</span>
          </div>
        );
      })}
    </div>
  );
}

function Inner() {
  const { id } = useParams<{ id: string }>(); const { roleFor } = useAuth(); const role = roleFor(id); const staff = isStaff(role);
  const qc = useQueryClient(); const act = useAct();
  const ev = useQuery({ queryKey: ["event", id], queryFn: () => api.events.get(id) });
  const q = useQuery({ queryKey: ["results", id, role], queryFn: () => api.judging.results(id), retry: false });
  const [m, setMode] = useState<"raw" | "norm" | null>(null); const [hover, setHover] = useState<string | null>(null); const [pub, setPub] = useState(false);
  if (q.isLoading) return <LoadingBlock rows={5} />;
  if (q.error instanceof ApiError && q.error.status === 403) return <Sealed />;
  if (q.error) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  const d = q.data!; const mode = m ?? (d.normalized ? "norm" : "raw"); const reviews = d.rows.reduce((a, r) => a + r.judge_count, 0);
  const normalize = async () => { const r = await act(() => api.judging.normalize(id), "Scores normalised — see the rank shifts"); if (r) { qc.setQueryData(["results", id, role], r); setMode("norm"); } };
  const publish = async () => { setPub(false); const r = await act(() => api.events.update(id, { status: "published" }), "Results published"); if (r) { qc.invalidateQueries({ queryKey: ["event", id] }); qc.invalidateQueries({ queryKey: ["events"] }); qc.invalidateQueries({ queryKey: ["results", id] }); } };
  const moved = d.rows.filter((r) => r.norm_rank && r.norm_rank !== r.raw_rank).length;

  return (
    <div>
      <PageHead kicker={d.published ? "Final results" : "Results · organiser preview"} title={d.published ? <>The <em>verdict.</em></> : <>Before the <em>reveal.</em></>}
        sub={d.published ? "Ranked by normalised score. Judge names and individual scores are never shown publicly." : "Only organisers can see this. Nothing is public until you publish."}
        actions={staff ? <>
          <button className="btn" onClick={async () => { const b = await act(() => api.judging.exportCsv(id), "CSV downloaded"); if (b) downloadBlob(b, `results-${id}.csv`); }}><Download size={13} /> CSV</button>
          <button className="btn" onClick={normalize}><Gauge size={13} /> {d.normalized ? "Recompute" : "Normalise"}</button>
          {ev.data?.status !== "published" && <button className="btn btn-primary" onClick={() => setPub(true)}><Megaphone size={13} /> Publish</button>}</> : undefined} />
      {!d.rows.length ? <Empty title="No reviews yet" body="A review counts as soon as a judge has scored at least one criterion. Check the progress tab." /> : (
        <div className="space-y-12">
          {staff && <div className="grid gap-4 md:grid-cols-4">
            <Stat label="Projects ranked" value={d.rows.length} accent /><Stat label="Reviews counted" value={reviews} sub="partial reviews included" />
            <Stat label="Judge spread σ" value={d.spread_raw !== null ? <>{d.spread_raw.toFixed(2)}{d.spread_norm !== null && <span className="text-ink3"> → <span className="amber">{d.spread_norm.toFixed(2)}</span></span>}</> : "—"} sub="how much judges disagree on the same project" />
            <Stat label="Rank changes" value={d.normalized ? moved : "—"} sub={d.normalized ? `normalised ${fmtDateTime(d.normalized_at)}` : "not normalised yet"} /></div>}
          <div className="grid items-start gap-8 xl:grid-cols-[1.5fr_1fr]">
            <div>
              <div className="mb-5 flex flex-wrap items-center justify-between gap-4"><span className="label">Leaderboard</span>
                {d.normalized ? <Segmented value={mode} onChange={setMode} options={[{ value: "raw", label: "Raw average" }, { value: "norm", label: "Normalised" }]} /> : staff ? <span className="chip chip-amber">raw only — normalise to correct judge bias</span> : null}</div>
              <Board d={d} staff={staff} mode={mode} hover={hover} setHover={setHover} />
            </div>
            {staff && d.judges.length > 0 && (
              <div className="panel ticks space-y-6 p-6 xl:sticky xl:top-[140px]">
                <div><div className="label mb-1 text-amberink">Normalisation proof</div><h3 className="display text-3xl">Who marks harsh, who marks generous.</h3></div>
                <BiasBars judges={d.judges} />
                <p className="border-t border-line pt-4 text-[12.5px] leading-relaxed text-ink3"><b className="text-ink2">Method.</b> {d.method}</p>
                {(() => { const single = new Set(d.single_review_judges ?? []); const flat = (d.zero_variance_judges ?? []).filter((j) => !single.has(j)).length;
                  return <>{flat > 0 && <p className="text-[12.5px] leading-relaxed text-signal">⚑ {flat} judge(s) scored every project identically, so their scores carry no ranking signal.</p>}
                    {single.size > 0 && <p className="text-[12.5px] leading-relaxed text-ink3">† {single.size} judge(s) submitted only one review — nothing to normalise, standardised against the pooled mean.</p>}</>; })()}
                <div className="flex items-center gap-4 text-[11.5px] text-ink3"><span className="flex items-center gap-2"><i className="inline-block h-3 w-3 rounded-full border border-ink3" /> raw judge score</span><span className="flex items-center gap-2"><i className="inline-block h-2 w-2 rotate-45 bg-amber" /> normalised</span></div>
              </div>)}
          </div>
          {staff && d.normalized && (
            <section className="panel ticks p-6 sm:p-8"><div className="mb-2 label text-amberink">Rank-shift lens</div><h3 className="display mb-6 text-4xl">Same scores, <em>fairer</em> order.</h3><SlopeChart rows={d.rows} hover={hover} setHover={setHover} /></section>)}
        </div>)}
      <Modal open={pub} onClose={() => setPub(false)} title="Publish results?">
        <p className="text-ink2">This makes the ranked board public and moves the event to <b>published</b>. Individual judge scores stay private. It is written to the audit log.</p>
        {!d.normalized && <p className="mt-3 border border-signal p-3 text-[13px] text-signal">You haven&apos;t normalised yet — the public ranking will use raw averages.</p>}
        <div className="mt-6 flex justify-end gap-3"><button className="btn" onClick={() => setPub(false)}>Not yet</button><button className="btn btn-primary" onClick={publish}>Publish</button></div>
      </Modal>
    </div>
  );
}
export default function ResultsPage() { return <Inner />; }
