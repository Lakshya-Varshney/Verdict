"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Command, LogOut, Menu, X, Copy, Check } from "lucide-react";
import { api, USE_MOCK } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { BRAND } from "@/lib/brand";
import { copyText, fmtDate } from "@/lib/utils";
import { SplitFlap } from "./SplitFlap";
import { ThemeToggle } from "./ThemeToggle";
import { Avatar } from "./ui";
import { CommandPalette } from "./CommandPalette";
import { RoleLens } from "./RoleLens";

export function Logo({ small }: { small?: boolean }) {
  return (
    <Link href="/" className="group flex items-center gap-3" aria-label={`${BRAND.name} home`}>
      <span className="boardframe !p-[3px]" style={{ fontSize: "1rem" }}><SplitFlap text="V" size={small ? 1.5 : 1.85} scramble={false} /></span>
      <span className="cond text-[1.55rem] tracking-[0.08em] transition-colors group-hover:text-amberink">{BRAND.name}</span>
    </Link>
  );
}

function TopBar() {
  const { me, authed, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const pathname = usePathname();
  useEffect(() => setOpen(false), [pathname]);
  const links = [{ href: "/events", label: "Events" }, { href: "/#pipeline", label: "Pipeline" }, { href: "/#roles", label: "Roles" }, ...(authed ? [{ href: "/admin/audit", label: "Audit" }] : [])];
  return (
    <header className="no-print sticky top-0 z-50 border-b border-line bg-[color-mix(in_srgb,var(--bg)_82%,transparent)] backdrop-blur-xl">
      <div className="mx-auto flex h-[68px] max-w-[1400px] items-center justify-between gap-4 px-5">
        <Logo />
        <nav className="hidden items-center gap-1 md:flex">
          {links.map((l) => <Link key={l.href} href={l.href} className={`tab !py-2 ${pathname === l.href ? "on" : ""}`}>{l.label}</Link>)}
        </nav>
        <div className="flex items-center gap-2">
          <button className="btn btn-sm hidden sm:inline-flex" onClick={() => window.dispatchEvent(new Event("verdict:palette"))} aria-label="Open command palette"><Command size={12} /> Search <span className="kbd ml-1">⌘K</span></button>
          <ThemeToggle />
          {authed && me ? (
            <div className="flex items-center gap-2">
              <Link href="/events" className="hidden items-center gap-2 sm:flex"><Avatar name={me.user.name} size={30} /><span className="hidden text-[13px] lg:block">{me.user.name}</span></Link>
              <button className="btn btn-ghost btn-icon" onClick={() => logout()} aria-label="Sign out" title="Sign out"><LogOut size={15} /></button>
            </div>
          ) : (
            <><Link href="/login" className="btn btn-sm hidden sm:inline-flex">Sign in</Link><Link href="/signup" className="btn btn-primary btn-sm">Get started</Link></>
          )}
          <button className="btn btn-ghost btn-icon md:hidden" onClick={() => setOpen((o) => !o)} aria-label="Menu">{open ? <X size={18} /> : <Menu size={18} />}</button>
        </div>
      </div>
      {open && <div className="border-t border-line bg-bg2 px-5 py-4 md:hidden"><div className="flex flex-col gap-1">{links.map((l) => <Link key={l.href} href={l.href} className="py-2 font-mono text-xs uppercase tracking-[0.14em]">{l.label}</Link>)}
        {!authed && <Link href="/login" className="py-2 font-mono text-xs uppercase tracking-[0.14em] text-amberink">Sign in</Link>}</div></div>}
    </header>
  );
}

function StatusTape() {
  const q = useQuery({ queryKey: ["events"], queryFn: () => api.events.list() });
  const items = q.data?.items ?? [];
  if (!items.length) return <div className="no-print h-[34px] border-b border-line bg-bg2" />;
  const one = items.map((e) => (
    <span key={e.id} className="mono flex items-center gap-3 whitespace-nowrap px-6 text-[10.5px] uppercase tracking-[0.16em] text-ink2">
      <span className={e.status === "open" ? "pulse-dot ok" : e.status === "judging" || e.status === "voting" ? "pulse-dot amber" : "inline-block h-[7px] w-[7px] rounded-full bg-ink3"} />
      <b className="font-semibold text-ink">{e.name}</b><span className="text-amberink">{e.status}</span>
      <span className="text-ink3">{e.submission_count ?? 0} projects · closes {fmtDate(e.deadline_at)}</span><span className="text-line2">///</span>
    </span>
  ));
  return (
    <div className="no-print relative h-[34px] overflow-hidden border-b border-line bg-bg2 [mask-image:linear-gradient(90deg,transparent,#000_6%,#000_94%,transparent)]" aria-hidden>
      <div className="tape flex h-full items-center">{one}{one}{one}{one}</div>
    </div>
  );
}

function Footer() {
  const [copied, setCopied] = useState(false);
  return (
    <footer className="no-print relative z-10 mt-24 border-t border-line bg-bg2">
      <div className="mx-auto grid max-w-[1400px] gap-10 px-5 py-14 md:grid-cols-[1.4fr_1fr_1fr]">
        <div>
          <Logo small />
          <p className="mt-4 max-w-sm text-[13.5px] text-ink2">{BRAND.tagline} Every rule enforced at the API. Every action in the audit log. Leave any time with your data.</p>
          <button onClick={async () => { await copyText("docker compose up"); setCopied(true); setTimeout(() => setCopied(false), 1800); }} className="mono mt-5 inline-flex items-center gap-3 border border-line2 bg-bg px-4 py-3 text-[12px] hover:border-amber">
            <span className="text-amberink">$</span> docker compose up {copied ? <Check size={13} color="var(--ok)" /> : <Copy size={13} className="text-ink3" />}
          </button>
        </div>
        <div><div className="label mb-4">Product</div><ul className="space-y-2 text-[13.5px] text-ink2"><li><Link className="link-u" href="/events">Events</Link></li><li><Link className="link-u" href="/#pipeline">The 10-stage pipeline</Link></li><li><Link className="link-u" href="/#roles">Role isolation</Link></li><li><a className="link-u" href="/backend-docs">API docs (/docs)</a></li></ul></div>
        <div><div className="label mb-4">Status</div><p className="text-[13px] text-ink2">{USE_MOCK ? <>Running on the <span className="chip chip-amber">built-in mock API</span>. Set <code className="mono text-[11px] text-amberink">NEXT_PUBLIC_MOCK=false</code> to talk to FastAPI.</> : <>Connected to the live API through <code className="mono text-[11px] text-amberink">/api</code>.</>}</p></div>
      </div>
      <div className="border-t border-line py-4 text-center"><span className="label">{BRAND.name} · MIT / Apache-2.0 · self-host · no telemetry · no third-party requests</span></div>
    </footer>
  );
}

export function Chrome({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  if (pathname.startsWith("/embed/")) return <>{children}</>;
  return (
    <div className="relative z-10 flex min-h-screen flex-col">
      <TopBar />
      <StatusTape />
      <main className="mx-auto w-full max-w-[1400px] flex-1 px-5 pb-10 pt-10">{children}</main>
      <Footer />
      <CommandPalette />
      <RoleLens />
    </div>
  );
}
