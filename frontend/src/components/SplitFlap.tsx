"use client";
import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

const CHARS = " ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.:-/$%#+★▲▼";
const FT = 62; // ms per half-flip

function seqFor(from: string, to: string, scramble: boolean): string[] {
  if (!scramble) return [to];
  const a = CHARS.indexOf(from), b = CHARS.indexOf(to);
  if (a < 0 || b < 0) return [to];
  const N = CHARS.length; const steps = (b - a + N) % N;
  const n = Math.min(steps, 5); const out: string[] = [];
  for (let i = n - 1; i >= 0; i--) out.push(CHARS[(b - i + N) % N]);
  return out.length ? out : [to];
}

function FlapChar({ ch, scramble, delay }: { ch: string; scramble: boolean; delay: number }) {
  const [shown, setShown] = useState(ch);
  const shownRef = useRef(ch);
  const [fold, setFold] = useState<{ from: string; to: string; k: number } | null>(null);
  const run = useRef(0); const kRef = useRef(0);

  useEffect(() => {
    if (ch === shownRef.current) return;
    const id = ++run.current; const seq = seqFor(shownRef.current, ch, scramble); let i = 0;
    const timers: ReturnType<typeof setTimeout>[] = [];
    const step = () => {
      if (id !== run.current) return;
      const to = seq[i];
      setFold({ from: shownRef.current, to, k: ++kRef.current });
      timers.push(setTimeout(() => {
        if (id !== run.current) return;
        shownRef.current = to; setShown(to); setFold(null); i++;
        if (i < seq.length) timers.push(setTimeout(step, 0));
      }, FT * 2));
    };
    timers.push(setTimeout(step, delay));
    return () => { timers.forEach(clearTimeout); };
  }, [ch, scramble, delay]);

  const from = fold?.from ?? shown; const to = fold?.to ?? shown;
  return (
    <span className="flap" aria-hidden>
      <span className="flap-half flap-t"><span>{to}</span></span>
      <span className="flap-half flap-b"><span>{from}</span></span>
      {fold && <span key={fold.k + "t"} className="flap-half flap-t flap-fold-t"><span>{fold.from}</span></span>}
      {fold && <span key={fold.k + "b"} className="flap-half flap-b flap-fold-b"><span>{fold.to}</span></span>}
    </span>
  );
}

export function SplitFlap({
  text, size = 2, color = "amber", pad, padSide = "end", scramble = true, framed = false, stagger = 45, className,
}: {
  text: string | number; size?: number | string; color?: "amber" | "ivory" | "signal" | "ok" | "cool";
  pad?: number; padSide?: "start" | "end"; scramble?: boolean; framed?: boolean; stagger?: number; className?: string;
}) {
  let t = String(text).toUpperCase();
  if (pad) t = padSide === "start" ? t.padStart(pad, " ") : t.padEnd(pad, " ");
  const chars = Array.from(t);
  const row = (
    <span role="text" aria-label={String(text)} className={cn("flaprow", `flap-${color}`, className)} style={{ ["--fs" as string]: typeof size === "number" ? `${size}rem` : size, ["--ft" as string]: `${FT}ms` } as React.CSSProperties}>
      {chars.map((c, i) => <FlapChar key={i} ch={c} scramble={scramble} delay={i * stagger} />)}
    </span>
  );
  return framed ? <span className="boardframe" style={{ fontSize: typeof size === "number" ? `${size}rem` : size }}>{row}</span> : row;
}

/** Cycles through words on a flap board. */
export function FlapCycle({ words, ms = 2600, ...rest }: { words: string[]; ms?: number } & Omit<React.ComponentProps<typeof SplitFlap>, "text">) {
  const [i, setI] = useState(0);
  useEffect(() => { const t = setInterval(() => setI((x) => (x + 1) % words.length), ms); return () => clearInterval(t); }, [words.length, ms]);
  const w = Math.max(...words.map((x) => x.length));
  return <SplitFlap text={words[i]} pad={w} {...rest} />;
}

export function useNow(ms = 1000) {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => { setNow(Date.now()); const t = setInterval(() => setNow(Date.now()), ms); return () => clearInterval(t); }, [ms]);
  return now;
}
export function useCountdown(to: string | null | undefined) {
  const now = useNow(1000);
  if (!to || now === null) return { ready: false, over: false, d: 0, h: 0, m: 0, s: 0, ms: 0 };
  const ms = new Date(to).getTime() - now; const over = ms <= 0; const a = Math.max(0, ms);
  return { ready: true, over, d: Math.floor(a / 86400000), h: Math.floor((a % 86400000) / 3600000), m: Math.floor((a % 3600000) / 60000), s: Math.floor((a % 60000) / 1000), ms };
}

const two = (n: number) => String(n).padStart(2, "0");
export function Countdown({ to, size = 2.6, closedText = "CLOSED", labels = true }: { to: string | null | undefined; size?: number; closedText?: string; labels?: boolean }) {
  const c = useCountdown(to);
  if (!c.ready) return <div className="skeleton" style={{ height: `${size * 1.6}rem`, width: `${size * 7.5}rem` }} />;
  if (c.over) return <div className="flex flex-col gap-2"><SplitFlap text={closedText} size={size} color="signal" framed /></div>;
  const groups: [string, number][] = [["days", c.d], ["hrs", c.h], ["min", c.m], ["sec", c.s]];
  return (
    <div className="flex items-start gap-2 sm:gap-3">
      {groups.map(([l, v], i) => (
        <div key={l} className="flex flex-col items-center gap-1.5">
          <SplitFlap text={two(v)} size={size} color={l === "sec" ? "signal" : "amber"} scramble={false} framed stagger={0} />
          {labels && <span className="label">{l}</span>}
          {i < 3 && null}
        </div>
      ))}
    </div>
  );
}
