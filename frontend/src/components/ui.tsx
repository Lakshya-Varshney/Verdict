"use client";
import Link from "next/link";
import { useEffect, type ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { X, Lock, Inbox, RotateCcw, LogIn } from "lucide-react";
import { ApiError } from "@/lib/api";
import { cn, hashStr, initials } from "@/lib/utils";
import type { EventStatus, Role } from "@/lib/types";

export function PageHead({ kicker, title, sub, actions, className }: { kicker?: string; title: ReactNode; sub?: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <div className={cn("mb-8 flex flex-wrap items-end justify-between gap-6", className)}>
      <div className="max-w-3xl">
        {kicker && <div className="label fade-up mb-3 flex items-center gap-2"><span className="inline-block h-px w-6 bg-amber" />{kicker}</div>}
        <h1 className="display fade-up text-[clamp(2.4rem,5.2vw,4.4rem)]" style={{ ["--i" as string]: 1 } as React.CSSProperties}>{title}</h1>
        {sub && <p className="fade-up mt-4 max-w-2xl text-[15.5px] text-ink2" style={{ ["--i" as string]: 2 } as React.CSSProperties}>{sub}</p>}
      </div>
      {actions && <div className="fade-up flex flex-wrap items-center gap-3" style={{ ["--i" as string]: 3 } as React.CSSProperties}>{actions}</div>}
    </div>
  );
}

export function Field({ label, hint, error, children, className }: { label: string; hint?: ReactNode; error?: string | null; children: ReactNode; className?: string }) {
  return (
    <label className={cn("block", className)}>
      <span className="label mb-2 flex items-center justify-between gap-2"><span>{label}</span>{hint && <span className="normal-case tracking-normal text-[11px] text-ink3" style={{ fontFamily: "var(--font-sans)" }}>{hint}</span>}</span>
      {children}
      {error && <span className="mt-1.5 block text-[12.5px] text-signal">{error}</span>}
    </label>
  );
}

const statusTone: Record<EventStatus, string> = { draft: "", open: "chip-ok", judging: "chip-amber", voting: "chip-cool", published: "chip-signal", archived: "" };
export function StatusChip({ status }: { status: EventStatus }) {
  return <span className={cn("chip", statusTone[status])}>{status === "open" || status === "judging" || status === "voting" ? <span className={cn("pulse-dot", status === "open" ? "ok" : "amber")} style={{ width: 5, height: 5 }} /> : null}{status}</span>;
}
const roleTone: Record<Role, string> = { visitor: "", participant: "chip-cool", judge: "chip-amber", organizer: "chip-ok", admin: "chip-signal" };
export function RoleBadge({ role }: { role: Role }) { return <span className={cn("chip", roleTone[role])}>{role}</span>; }

export function Avatar({ name, size = 32 }: { name: string; size?: number }) {
  const h = hashStr(name) % 3; const c = ["var(--amber)", "var(--cool)", "var(--signal)"][h];
  return <span className="inline-flex shrink-0 items-center justify-center rounded-full font-mono font-semibold" style={{ width: size, height: size, fontSize: size * 0.34, background: `color-mix(in srgb, ${c} 16%, var(--panel2))`, border: `1px solid color-mix(in srgb, ${c} 55%, transparent)`, color: c }}>{initials(name)}</span>;
}

export function Skeleton({ className = "", style }: { className?: string; style?: React.CSSProperties }) { return <div className={cn("skeleton", className)} style={style} />; }
export function LoadingBlock({ rows = 3 }: { rows?: number }) {
  return <div className="space-y-3" aria-busy>{Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className="h-16" style={{ opacity: 1 - i * 0.18 }} />)}</div>;
}

export function Denied({ need, what, hint }: { need?: string; what?: string; hint?: string }) {
  return (
    <div className="panel ticks fade-up mx-auto max-w-2xl overflow-hidden">
      <div className="hazard h-3" />
      <div className="p-8 sm:p-10">
        <div className="label mb-4 flex items-center gap-2" style={{ color: "var(--signal)" }}><Lock size={12} /> 403 · denied at the API</div>
        <h2 className="display text-5xl">You can&apos;t <em style={{ color: "var(--signal)" }}>do</em> that here.</h2>
        <p className="mt-4 text-ink2">{what ?? "This screen is for a different role."}{need ? <> It needs <span className="chip chip-amber">{need}</span>.</> : null}</p>
        <p className="mt-3 text-[13px] text-ink3">{hint ?? "The UI hides what your role can't do — but the real check lives in the backend. Even if you typed this URL by hand, the API would say no."}</p>
        <div className="mt-6 flex gap-3"><Link href="/events" className="btn btn-primary">Back to events</Link></div>
      </div>
    </div>
  );
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const e = error instanceof ApiError ? error : null;
  if (e?.status === 403) return <Denied what={e.detail} />;
  if (e?.status === 401) return (
    <div className="panel mx-auto max-w-lg p-8 text-center"><LogIn className="mx-auto mb-3" size={22} color="var(--amber)" /><h3 className="display text-3xl">Sign in to continue</h3><p className="mt-2 text-ink2 text-sm">{e.detail}</p>
      <Link className="btn btn-primary mt-5" href={`/login?next=${encodeURIComponent(typeof window !== "undefined" ? window.location.pathname : "/")}`}>Sign in</Link></div>
  );
  return (
    <div className="panel mx-auto max-w-lg p-8 text-center">
      <div className="label mb-3" style={{ color: "var(--signal)" }}>{e ? `Error ${e.status}` : "Something broke"}</div>
      <p className="text-ink2">{e?.detail ?? "Unexpected error."}</p>
      {retry && <button className="btn mt-5" onClick={retry}><RotateCcw size={13} /> Try again</button>}
    </div>
  );
}

export function Empty({ title, body, action, icon }: { title: string; body?: ReactNode; action?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="panel dots fade-up flex flex-col items-center px-6 py-14 text-center">
      <div className="mb-4 grid h-12 w-12 place-items-center border border-line2 text-amberink">{icon ?? <Inbox size={20} />}</div>
      <h3 className="display text-3xl">{title}</h3>
      {body && <p className="mt-2 max-w-md text-[14px] text-ink2">{body}</p>}
      {action && <div className="mt-6">{action}</div>}
    </div>
  );
}

/** Query boundary: skeleton -> error -> data. */
export function Q<T>({ q, children, skeleton }: { q: UseQueryResult<T>; children: (d: T) => ReactNode; skeleton?: ReactNode }) {
  if (q.isLoading) return <>{skeleton ?? <LoadingBlock />}</>;
  if (q.error) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  if (q.data === undefined) return null;
  return <>{children(q.data)}</>;
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; wide?: boolean }) {
  useEffect(() => { if (!open) return; const f = (e: KeyboardEvent) => e.key === "Escape" && onClose(); window.addEventListener("keydown", f); return () => window.removeEventListener("keydown", f); }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[80] grid place-items-center p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className={cn("panel ticks fade-up relative max-h-[88vh] w-full overflow-auto p-6 sm:p-8", wide ? "max-w-3xl" : "max-w-lg")}>
        <button onClick={onClose} className="btn btn-ghost btn-icon absolute right-3 top-3" aria-label="Close"><X size={16} /></button>
        <h3 className="display mb-5 pr-8 text-4xl">{title}</h3>
        {children}
      </div>
    </div>
  );
}

export function Segmented<T extends string>({ options, value, onChange }: { options: { value: T; label: string; hint?: string }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex max-w-full overflow-x-auto border border-line2" role="tablist">
      {options.map((o) => (
        <button key={o.value} role="tab" aria-selected={value === o.value} onClick={() => onChange(o.value)} title={o.hint}
          className={cn("px-4 py-2.5 font-mono text-[10.5px] uppercase tracking-[0.12em] transition-colors", value === o.value ? "bg-amber text-[var(--on-amber)] font-semibold" : "text-ink2 hover:text-ink")}>{o.label}</button>
      ))}
    </div>
  );
}

export function TagInput({ value, onChange, placeholder }: { value: string[]; onChange: (v: string[]) => void; placeholder?: string }) {
  return (
    <div className="input flex min-h-[46px] flex-wrap items-center gap-1.5 !py-1.5">
      {value.map((t) => <span key={t} className="chip chip-amber">{t}<button type="button" onClick={() => onChange(value.filter((x) => x !== t))} aria-label={`Remove ${t}`}><X size={10} /></button></span>)}
      <input className="min-w-[8ch] flex-1 bg-transparent py-1 text-sm outline-none placeholder:text-ink3" placeholder={value.length ? "" : placeholder}
        onKeyDown={(e) => {
          const v = e.currentTarget.value.trim().toLowerCase().replace(/[^a-z0-9-+.#]/g, "");
          if ((e.key === "Enter" || e.key === "," || e.key === " ") && v) { e.preventDefault(); if (!value.includes(v) && value.length < 8) onChange([...value, v]); e.currentTarget.value = ""; }
          if (e.key === "Backspace" && !e.currentTarget.value && value.length) onChange(value.slice(0, -1));
        }} />
    </div>
  );
}

export function Stat({ label, value, sub, accent }: { label: string; value: ReactNode; sub?: ReactNode; accent?: boolean }) {
  return (
    <div className="panel p-5">
      <div className="label">{label}</div>
      <div className={cn("cond mt-2 text-[2.6rem]", accent && "amber")}>{value}</div>
      {sub && <div className="mt-1 text-[12.5px] text-ink3">{sub}</div>}
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) { return <span className="kbd">{children}</span>; }
export function SectionLabel({ n, children }: { n?: string; children: ReactNode }) {
  return <div className="label mb-5 flex items-center gap-3"><span className="text-amberink">{n ? `[ ${n} ]` : "//"}</span><span>{children}</span><span className="rule flex-1" /></div>;
}
