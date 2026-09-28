"use client";
import { useState } from "react";
import { usePathname } from "next/navigation";
import { Eye, RotateCcw, X } from "lucide-react";
import { USE_MOCK, api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { DEMO_ACCOUNTS, DEMO_PASSWORD } from "@/lib/mock/db";
import { RoleBadge } from "./ui";
import { useToast } from "./toast";

/** Demo-only floating console: switch between seeded accounts to see every role's UI (mock mode only). */
export function RoleLens() {
  const [open, setOpen] = useState(false);
  const { me, login, logout, roleFor } = useAuth(); const pathname = usePathname(); const toast = useToast();
  if (!USE_MOCK) return null;
  const m = pathname.match(/^\/events\/([^/]+)/); const eid = m?.[1]; const role = me ? (eid ? roleFor(eid) : me.user.is_admin ? "admin" : "participant") : "visitor";
  const as = async (email: string, name: string) => { await login(email, DEMO_PASSWORD); toast(`Now viewing as ${name}`, "info"); };
  return (
    <div className="no-print fixed bottom-4 left-4 z-[70]">
      {open ? (
        <div className="panel ticks fade-up w-[280px] p-4">
          <div className="mb-3 flex items-center justify-between"><span className="label flex items-center gap-2 text-amberink"><Eye size={12} /> Role lens · demo</span><button onClick={() => setOpen(false)} aria-label="Close" className="text-ink3 hover:text-ink"><X size={14} /></button></div>
          <div className="space-y-1.5">
            {DEMO_ACCOUNTS.map((a) => (
              <button key={a.id} onClick={() => as(a.email, a.name)} className={`flex w-full items-center justify-between border px-3 py-2 text-left transition-colors ${me?.user.id === a.id ? "border-amber bg-[color-mix(in_srgb,var(--amber)_10%,transparent)]" : "border-line hover:border-line2"}`}>
                <span><span className="block text-[13px]">{a.name}</span><span className="label">{a.label}</span></span>{me?.user.id === a.id && <span className="pulse-dot ok" />}
              </button>
            ))}
            <button onClick={() => logout()} className={`flex w-full items-center justify-between border px-3 py-2 text-left ${!me ? "border-amber" : "border-line hover:border-line2"}`}><span><span className="block text-[13px]">Signed out</span><span className="label">Visitor</span></span></button>
          </div>
          <p className="mt-3 text-[11.5px] leading-snug text-ink3">Roles are per-event. Same person, different event = different powers. Try hitting a screen your role can&apos;t use — the mock API says no, like the real one will.</p>
          <button className="btn btn-sm mt-3 w-full" onClick={async () => { await api.dev.resetMock(); location.reload(); }}><RotateCcw size={12} /> Reset demo data</button>
        </div>
      ) : (
        <button onClick={() => setOpen(true)} className="panel flex items-center gap-3 px-3.5 py-2.5 hover:border-amber" aria-label="Open role lens">
          <Eye size={14} className="text-amberink" /><span className="label !text-ink2 hidden sm:inline">Role lens</span><span className="hidden sm:inline-flex"><RoleBadge role={role} /></span>
        </button>
      )}
    </div>
  );
}
