"use client";
import { useMemo, useState } from "react";
import { SplitFlap } from "./SplitFlap";
import { Segmented } from "./ui";

const R: Record<string, Record<string, number>> = {
  "Harsh judge": { Gavelbird: 3.0, Ballast: 2.4, Scrutiny: 2.0, Ledgerline: 3.2 },
  "Generous judge": { Plumbline: 4.7, Quorum: 4.4, Ledgerline: 4.9, Scrutiny: 4.5 },
  "Steady judge": { Gavelbird: 3.6, Plumbline: 3.3, Ballast: 3.1, Quorum: 3.4, Scrutiny: 2.9, Ledgerline: 3.8 },
};
const mean = (a: number[]) => a.reduce((x, y) => x + y, 0) / a.length;
const sd = (a: number[]) => { const m = mean(a); return Math.sqrt(mean(a.map((x) => (x - m) ** 2))); };

export function NormDemo() {
  const [mode, setMode] = useState<"raw" | "norm">("raw");
  const rows = useMemo(() => {
    const all = Object.values(R).flatMap((o) => Object.values(o)); const mu = mean(all), sg = sd(all);
    const stats = Object.fromEntries(Object.entries(R).map(([j, o]) => [j, { m: mean(Object.values(o)), s: sd(Object.values(o)) }]));
    const P: Record<string, { raw: number[]; norm: number[] }> = {};
    Object.entries(R).forEach(([j, o]) => Object.entries(o).forEach(([p, x]) => { (P[p] ??= { raw: [], norm: [] }).raw.push(x); P[p].norm.push(mu + ((x - stats[j].m) / stats[j].s) * sg); }));
    const list = Object.entries(P).map(([name, v]) => ({ name, raw: mean(v.raw), norm: mean(v.norm) }));
    const rawRank = Object.fromEntries([...list].sort((a, b) => b.raw - a.raw).map((r, i) => [r.name, i + 1]));
    const normRank = Object.fromEntries([...list].sort((a, b) => b.norm - a.norm).map((r, i) => [r.name, i + 1]));
    return list.map((r) => ({ ...r, rawRank: rawRank[r.name], normRank: normRank[r.name] }));
  }, []);
  const rowH = 58;
  return (
    <div className="panel ticks p-6 sm:p-8">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div><div className="label mb-1 text-amberink">Try it — no backend needed</div><div className="display text-4xl">Same scores. <em>Fairer</em> order.</div></div>
        <Segmented value={mode} onChange={setMode} options={[{ value: "raw", label: "Raw average" }, { value: "norm", label: "Normalised" }]} />
      </div>
      <div className="relative" style={{ height: rows.length * rowH }}>
        {rows.map((r) => {
          const rank = mode === "raw" ? r.rawRank : r.normRank; const d = r.rawRank - r.normRank; const v = mode === "raw" ? r.raw : r.norm;
          return (
            <div key={r.name} className="absolute left-0 right-0 flex items-center gap-4 border border-line bg-bg2 px-4 transition-transform duration-[900ms] [transition-timing-function:cubic-bezier(.7,0,.2,1)]" style={{ height: rowH - 8, transform: `translateY(${(rank - 1) * rowH}px)` }}>
              <SplitFlap text={String(rank).padStart(2, "0")} size={1.5} color="amber" framed={false} scramble={false} stagger={0} />
              <span className="w-32 shrink-0 font-serif text-2xl italic leading-none">{r.name}</span>
              <div className="relative h-2 flex-1 bg-line"><i className="absolute inset-y-0 left-0 bg-amber transition-all duration-[900ms]" style={{ width: `${(v / 5) * 100}%`, boxShadow: "0 0 14px var(--amber)" }} /></div>
              <span className="mono w-12 text-right text-[12px] text-ink2">{v.toFixed(2)}</span>
              <span className="mono w-10 text-right text-[11px]" style={{ color: mode === "norm" && d !== 0 ? (d > 0 ? "var(--ok)" : "var(--signal)") : "transparent" }}>{d > 0 ? "▲" : d < 0 ? "▼" : "•"}{Math.abs(d) || ""}</span>
            </div>
          );
        })}
      </div>
      <p className="mt-5 max-w-2xl text-[13px] text-ink3">Three judges scored different subsets. One marks everything low, one marks everything high. Each judge&apos;s scores are re-centred on their own average and spread before projects are ranked — so the project that drew the harsh reviewer isn&apos;t punished for it.</p>
    </div>
  );
}
