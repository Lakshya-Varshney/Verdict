import { hashStr, mulberry } from "@/lib/utils";

/** Deterministic generative cover art — every project gets a unique, on-brand "poster" without needing images. */
export function Cover({ seed, label, className = "", rounded = true }: { seed: string; label?: string; className?: string; rounded?: boolean }) {
  const r = mulberry(hashStr(seed));
  const kind = Math.floor(r() * 5);
  const A = "var(--amber)", I = "var(--ink)", S = "var(--signal)", L = "var(--line2)", C = "var(--cool)";
  const shapes: React.ReactNode[] = [];
  if (kind === 0) { // concentric dial
    const cx = 60 + r() * 280, cy = 80 + r() * 140;
    for (let i = 0; i < 9; i++) shapes.push(<circle key={i} cx={cx} cy={cy} r={16 + i * 22} fill="none" stroke={i % 4 === 0 ? A : L} strokeWidth={i % 4 === 0 ? 2.5 : 1} strokeDasharray={i % 3 === 0 ? "3 6" : undefined} />);
    shapes.push(<circle key="c" cx={cx} cy={cy} r={7} fill={S} />);
  } else if (kind === 1) { // score bars
    const n = 11; const bw = 400 / n;
    for (let i = 0; i < n; i++) { const h = 30 + r() * 210; shapes.push(<rect key={i} x={i * bw + 5} y={300 - h} width={bw - 10} height={h} fill={i === Math.floor(r() * n) ? A : "none"} stroke={i % 3 === 0 ? A : L} strokeWidth={1.5} />); }
  } else if (kind === 2) { // dot matrix with diagonal
    for (let y = 0; y < 11; y++) for (let x = 0; x < 15; x++) { const on = Math.abs(x * 0.9 - y * 1.6 - (r() * 2 - 1) * 2) < 1.6; shapes.push(<circle key={x + "-" + y} cx={16 + x * 26} cy={16 + y * 27} r={on ? 6 : 2} fill={on ? (r() > 0.75 ? S : A) : L} />); }
  } else if (kind === 3) { // nested rotated squares
    for (let i = 0; i < 8; i++) shapes.push(<rect key={i} x={200 - (150 - i * 17)} y={150 - (150 - i * 17)} width={(150 - i * 17) * 2} height={(150 - i * 17) * 2} fill="none" stroke={i % 3 === 0 ? A : i === 5 ? C : L} strokeWidth={i % 3 === 0 ? 2.2 : 1} transform={`rotate(${i * (6 + r() * 6)} 200 150)`} />);
  } else { // radial ticks
    const cx = 200, cy = 170;
    for (let i = 0; i < 60; i++) { const a = (i / 60) * Math.PI * 2, long = i % 5 === 0; const r1 = 70, r2 = long ? 128 : 108; shapes.push(<line key={i} x1={cx + Math.cos(a) * r1} y1={cy + Math.sin(a) * r1} x2={cx + Math.cos(a) * r2} y2={cy + Math.sin(a) * r2} stroke={i === Math.floor(r() * 60) ? S : long ? A : L} strokeWidth={long ? 2.4 : 1.2} />); }
    shapes.push(<circle key="c" cx={cx} cy={cy} r={4} fill={I} />);
  }
  const initial = (label || seed).trim()[0]?.toUpperCase() ?? "V";
  return (
    <svg viewBox="0 0 400 300" preserveAspectRatio="xMidYMid slice" className={className} role="img" aria-label={label ? `${label} cover` : "cover"} style={{ display: "block", width: "100%", height: "100%", borderRadius: rounded ? 2 : 0 }}>
      <rect width="400" height="300" fill="var(--bg2)" />
      <rect width="400" height="300" fill="url(#g)" opacity="0" />
      {shapes}
      <text x="18" y="278" fontFamily="var(--font-serif)" fontStyle="italic" fontSize="120" fill={I} opacity="0.09" style={{ letterSpacing: "-0.04em" }}>{initial}</text>
      <path d="M0 0h18M0 0v18M400 300h-18M400 300v-18" stroke={A} strokeWidth="2" fill="none" transform="translate(6 6) scale(.97)" opacity=".8" />
    </svg>
  );
}
