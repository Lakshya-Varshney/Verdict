"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { CornerDownLeft, Search } from "lucide-react";
import { api, USE_MOCK } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { eventTabs } from "@/lib/nav";
import { useTheme } from "./ThemeToggle";
import { Kbd } from "./ui";

interface Cmd { id: string; label: string; group: string; run: () => void; }

export function CommandPalette() {
  const [open, setOpen] = useState(false); const [q, setQ] = useState(""); const [idx, setIdx] = useState(0);
  const router = useRouter(); const { authed, logout, roleFor } = useAuth(); const { toggle } = useTheme();
  const events = useQuery({ queryKey: ["events"], queryFn: () => api.events.list() });
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const k = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen((o) => !o); } if (e.key === "Escape") setOpen(false); };
    const p = () => setOpen(true);
    window.addEventListener("keydown", k); window.addEventListener("verdict:palette", p);
    return () => { window.removeEventListener("keydown", k); window.removeEventListener("verdict:palette", p); };
  }, []);
  useEffect(() => { if (open) { setQ(""); setIdx(0); setTimeout(() => ref.current?.focus(), 30); } }, [open]);

  const cmds = useMemo<Cmd[]>(() => {
    const go = (href: string) => () => { setOpen(false); router.push(href); };
    const c: Cmd[] = [{ id: "home", label: "Home", group: "Go", run: go("/") }, { id: "events", label: "All events", group: "Go", run: go("/events") }, { id: "new", label: "Create an event", group: "Go", run: go("/events/new") }, { id: "audit", label: "Audit log", group: "Go", run: go("/admin/audit") }];
    (events.data?.items ?? []).forEach((e) => eventTabs(e.id, roleFor(e.id), e.status).forEach((t) => c.push({ id: `${e.id}-${t.key}`, label: `${e.name} — ${t.label}`, group: e.name, run: go(t.href) })));
    c.push({ id: "theme", label: "Toggle Board / Paper theme", group: "System", run: () => { toggle(); setOpen(false); } });
    if (authed) c.push({ id: "out", label: "Sign out", group: "System", run: () => { logout(); setOpen(false); } }); else c.push({ id: "in", label: "Sign in", group: "System", run: go("/login") });
    if (USE_MOCK) c.push({ id: "reset", label: "Reset demo data", group: "System", run: async () => { await api.dev.resetMock(); location.href = "/"; } });
    return c;
  }, [events.data, roleFor, router, toggle, authed, logout]);

  const list = useMemo(() => { const s = q.trim().toLowerCase(); return (s ? cmds.filter((c) => c.label.toLowerCase().includes(s)) : cmds).slice(0, 12); }, [cmds, q]);
  useEffect(() => setIdx(0), [q]);
  if (!open) return null;
  return (
    <div className="no-print fixed inset-0 z-[95] grid place-items-start justify-items-center px-4 pt-[14vh]" role="dialog" aria-modal="true" aria-label="Command palette">
      <div className="absolute inset-0 bg-black/70 backdrop-blur-sm" onClick={() => setOpen(false)} />
      <div className="panel ticks fade-up relative w-full max-w-xl overflow-hidden">
        <div className="flex items-center gap-3 border-b border-line px-4"><Search size={15} className="text-ink3" />
          <input ref={ref} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Jump to an event, screen, or action…" className="h-14 flex-1 bg-transparent text-[15px] outline-none placeholder:text-ink3"
            onKeyDown={(e) => { if (e.key === "ArrowDown") { e.preventDefault(); setIdx((i) => Math.min(list.length - 1, i + 1)); } if (e.key === "ArrowUp") { e.preventDefault(); setIdx((i) => Math.max(0, i - 1)); } if (e.key === "Enter") list[idx]?.run(); }} />
          <Kbd>esc</Kbd></div>
        <ul className="max-h-[52vh] overflow-auto py-2">
          {list.map((c, i) => (
            <li key={c.id}><button onMouseEnter={() => setIdx(i)} onClick={c.run} className={`flex w-full items-center justify-between gap-4 px-4 py-2.5 text-left text-[13.5px] ${i === idx ? "bg-[color-mix(in_srgb,var(--amber)_12%,transparent)]" : ""}`}>
              <span className="flex min-w-0 items-center gap-3"><span className="label w-24 shrink-0 truncate">{c.group}</span><span className="truncate">{c.label}</span></span>{i === idx && <CornerDownLeft size={13} className="text-amberink" />}</button></li>
          ))}
          {!list.length && <li className="px-4 py-8 text-center text-sm text-ink3">Nothing matches “{q}”.</li>}
        </ul>
      </div>
    </div>
  );
}
