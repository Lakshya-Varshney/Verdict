"use client";
import type { Criterion, JudgeBias, ResultRow } from "@/lib/types";

const PALETTE = ["var(--amber)", "var(--cool)", "var(--signal)", "var(--ok)", "var(--ink2)", "var(--ink3)"];

export function WeightBar({ criteria }: { criteria: Pick<Criterion, "id" | "name" | "weight">[] }) {
  const total = criteria.reduce((a, c) => a + c.weight, 0) || 1;
  return (
    <div>
      <div className="flex h-10 w-full overflow-hidden border border-line2">
        {criteria.map((c, i) => (
          <div key={c.id} title={`${c.name} — ${((c.weight / total) * 100).toFixed(0)}%`} className="relative grid place-items-center overflow-hidden transition-all duration-700"
            style={{ width: `${(c.weight / total) * 100}%`, background: `color-mix(in srgb, ${PALETTE[i % PALETTE.length]} ${i === 0 ? 92 : 70}%, var(--bg))`, borderRight: i < criteria.length - 1 ? "2px solid var(--bg)" : undefined }}>
            <span className="cond text-lg" style={{ color: "var(--on-amber)" }}>{Math.round((c.weight / total) * 100)}</span>
          </div>
        ))}
      </div>
      <div className="mt-3 flex flex-wrap gap-x-5 gap-y-1.5">
        {criteria.map((c, i) => <span key={c.id} className="flex items-center gap-2 text-[12px] text-ink2"><i className="inline-block h-2.5 w-2.5" style={{ background: PALETTE[i % PALETTE.length] }} />{c.name}</span>)}
      </div>
    </div>
  );
}

export function SlopeChart({ rows, hover, setHover }: { rows: ResultRow[]; hover: string | null; setHover: (id: string | null) => void }) {
  const rr = rows.filter((r) => r.norm_rank !== null);
  const n = rr.length; const rowH = 25; const H = n * rowH + 56; const W = 620; const xl = 205, xr = 415;
  const y = (rank: number) => 48 + (rank - 1) * rowH;
  const byRaw = [...rr].sort((a, b) => a.raw_rank - b.raw_rank); const byNorm = [...rr].sort((a, b) => (a.norm_rank as number) - (b.norm_rank as number));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Rank movement from raw to normalised scoring" onMouseLeave={() => setHover(null)}>
      <text x={xl - 12} y={22} textAnchor="end" className="label" fill="var(--ink3)" fontFamily="var(--font-mono)" fontSize="10" letterSpacing="1.6">RAW</text>
      <text x={xr + 12} y={22} textAnchor="start" fill="var(--amber-ink)" fontFamily="var(--font-mono)" fontSize="10" letterSpacing="1.6">NORMALISED</text>
      {rr.map((r) => {
        const d = (r.raw_rank) - (r.norm_rank as number); const col = d > 0 ? "var(--ok)" : d < 0 ? "var(--signal)" : "var(--line2)"; const on = hover === r.submission_id;
        const x1 = xl, x2 = xr, y1 = y(r.raw_rank), y2 = y(r.norm_rank as number);
        return <path key={r.submission_id} d={`M${x1} ${y1} C ${(x1 + x2) / 2} ${y1}, ${(x1 + x2) / 2} ${y2}, ${x2} ${y2}`} fill="none" stroke={col} strokeWidth={on ? 3 : 1.6} opacity={hover ? (on ? 1 : 0.15) : d === 0 ? 0.5 : 0.85} style={{ transition: "all .2s" }} />;
      })}
      {byRaw.map((r) => (
        <g key={"l" + r.submission_id} onMouseEnter={() => setHover(r.submission_id)} style={{ cursor: "pointer" }}>
          <rect x={0} y={y(r.raw_rank) - 11} width={xl + 4} height={22} fill="transparent" />
          <text x={xl - 12} y={y(r.raw_rank) + 4} textAnchor="end" fontFamily="var(--font-mono)" fontSize="10.5" fill={hover === r.submission_id ? "var(--ink)" : "var(--ink2)"}>{r.name} <tspan fill="var(--ink3)">{String(r.raw_rank).padStart(2, "0")}</tspan></text>
          <circle cx={xl} cy={y(r.raw_rank)} r={3} fill="var(--ink3)" />
        </g>
      ))}
      {byNorm.map((r) => {
        const d = r.raw_rank - (r.norm_rank as number);
        return (
          <g key={"r" + r.submission_id} onMouseEnter={() => setHover(r.submission_id)} style={{ cursor: "pointer" }}>
            <rect x={xr - 4} y={y(r.norm_rank as number) - 11} width={W - xr} height={22} fill="transparent" />
            <circle cx={xr} cy={y(r.norm_rank as number)} r={3.5} fill="var(--amber)" />
            <text x={xr + 12} y={y(r.norm_rank as number) + 4} fontFamily="var(--font-mono)" fontSize="10.5" fill={hover === r.submission_id ? "var(--ink)" : "var(--ink2)"}><tspan fill="var(--ink3)">{String(r.norm_rank).padStart(2, "0")}</tspan> {r.name}
              {d !== 0 && <tspan fill={d > 0 ? "var(--ok)" : "var(--signal)"} dx="8">{d > 0 ? "▲" : "▼"}{Math.abs(d)}</tspan>}</text>
          </g>
        );
      })}
    </svg>
  );
}

export function BiasBars({ judges }: { judges: JudgeBias[] }) {
  const max = Math.max(0.6, ...judges.map((j) => Math.abs(j.offset)));
  return (
    <div className="space-y-2.5">
      {judges.map((j) => {
        const w = (Math.abs(j.offset) / max) * 50; const pos = j.offset >= 0;
        return (
          <div key={j.judge_id} className="grid grid-cols-[minmax(0,9rem)_1fr_4.5rem] items-center gap-3 text-[12.5px]">
            <span className="truncate text-ink2" title={j.single_review ? "Only one review — no spread to measure, standardised against the pooled mean" : j.zero_variance ? "Gave every project the same score — standardised against the pooled mean instead" : undefined}>{j.judge_name}{j.single_review ? " †" : j.zero_variance ? " ⚑" : ""}</span>
            <div className="relative h-4 border-x border-line2"><i className="absolute left-1/2 top-0 h-full w-px bg-line2" />
              <i className="absolute top-[3px] h-2.5 transition-all duration-700" style={{ [pos ? "left" : "right"]: "50%", width: `${w}%`, background: pos ? "var(--amber)" : "var(--cool)" } as React.CSSProperties} /></div>
            <span className="mono text-right text-[11px] text-ink3">{j.offset >= 0 ? "+" : ""}{j.offset.toFixed(2)} · σ{j.sd.toFixed(2)}</span>
          </div>
        );
      })}
      <div className="label flex justify-between pt-1"><span>← harsher than average</span><span>more generous →</span></div>
    </div>
  );
}

export function ScoreStrip({ raw, norm }: { raw: number[]; norm?: (number | null)[] }) {
  const x = (v: number) => ((v - 1) / 4) * 100;
  return (
    <div className="relative h-7 w-full min-w-[110px]">
      <i className="absolute left-0 right-0 top-1/2 h-px bg-line2" />
      {[1, 2, 3, 4, 5].map((t) => <i key={t} className="absolute top-[9px] h-2 w-px bg-line2" style={{ left: `${x(t)}%` }} />)}
      {raw.map((v, i) => <i key={"r" + i} className="absolute top-[7px] h-3 w-3 rounded-full border border-ink3 bg-bg" style={{ left: `calc(${x(v)}% - 6px)` }} title={`raw ${v.toFixed(2)}`} />)}
      {norm?.map((v, i) => v !== null && <i key={"n" + i} className="absolute top-[9px] h-2 w-2 rotate-45 bg-amber" style={{ left: `calc(${x(v)}% - 4px)`, boxShadow: "0 0 8px var(--amber)" }} title={`normalised ${v.toFixed(2)}`} />)}
    </div>
  );
}

export function AssignGraph({ judges, subs, edges, hover, setHover }: { judges: { id: string; name: string }[]; subs: { id: string; name: string }[]; edges: { judge_id: string; submission_id: string }[]; hover: string | null; setHover: (id: string | null) => void }) {
  const W = 680; const rowJ = Math.max(34, Math.min(56, 360 / Math.max(judges.length, 1))); const rowS = 15.5;
  const H = Math.max(judges.length * rowJ, subs.length * rowS) + 40;
  const jy = (i: number) => 30 + i * rowJ + rowJ / 2 - 6; const sy = (i: number) => 30 + i * rowS;
  const xj = 178, xs = 500;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Judge to project assignment graph" onMouseLeave={() => setHover(null)}>
      <text x={xj} y={14} textAnchor="end" fill="var(--ink3)" fontFamily="var(--font-mono)" fontSize="10" letterSpacing="1.6">JUDGES</text>
      <text x={xs} y={14} fill="var(--ink3)" fontFamily="var(--font-mono)" fontSize="10" letterSpacing="1.6">PROJECTS</text>
      {edges.map((e, k) => {
        const ji = judges.findIndex((j) => j.id === e.judge_id), si = subs.findIndex((s) => s.id === e.submission_id); if (ji < 0 || si < 0) return null;
        const on = hover === e.judge_id;
        return <path key={k} d={`M${xj + 6} ${jy(ji)} C ${(xj + xs) / 2} ${jy(ji)}, ${(xj + xs) / 2} ${sy(si)}, ${xs - 6} ${sy(si)}`} fill="none" stroke="var(--amber)" strokeWidth={on ? 1.6 : 0.9} opacity={hover ? (on ? 0.95 : 0.06) : 0.28} style={{ transition: "opacity .2s" }} />;
      })}
      {judges.map((j, i) => (
        <g key={j.id} onMouseEnter={() => setHover(j.id)} style={{ cursor: "pointer" }}>
          <rect x={0} y={jy(i) - rowJ / 2 + 4} width={xj + 12} height={rowJ - 6} fill="transparent" />
          <text x={xj - 12} y={jy(i) + 4} textAnchor="end" fontSize="12.5" fontFamily="var(--font-sans)" fill={hover === j.id ? "var(--amber-ink)" : "var(--ink)"}>{j.name}</text>
          <circle cx={xj} cy={jy(i)} r={5} fill={hover === j.id ? "var(--amber)" : "var(--bg)"} stroke="var(--amber)" strokeWidth="2" />
        </g>
      ))}
      {subs.map((s, i) => (
        <g key={s.id}><circle cx={xs} cy={sy(i)} r={2.6} fill="var(--ink3)" /><text x={xs + 10} y={sy(i) + 3.4} fontSize="9.5" fontFamily="var(--font-mono)" fill="var(--ink2)">{s.name}</text></g>
      ))}
    </svg>
  );
}
