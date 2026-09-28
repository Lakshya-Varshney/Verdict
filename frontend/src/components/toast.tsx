"use client";
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { CheckCircle2, ShieldAlert, Info } from "lucide-react";

type Kind = "ok" | "error" | "info";
interface T { id: number; kind: Kind; msg: string; }
const Ctx = createContext<(msg: string, kind?: Kind) => void>(() => {});
export const useToast = () => useContext(Ctx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<T[]>([]);
  const push = useCallback((msg: string, kind: Kind = "info") => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x.slice(-3), { id, kind, msg }]);
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), kind === "error" ? 6500 : 3800);
  }, []);
  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="no-print fixed bottom-4 right-4 z-[90] flex w-[min(92vw,380px)] flex-col gap-2" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className="panel fade-up flex items-start gap-3 px-4 py-3" style={{ borderColor: t.kind === "error" ? "var(--signal)" : t.kind === "ok" ? "color-mix(in srgb, var(--ok) 55%, var(--line))" : undefined }}>
            <span className="mt-0.5">{t.kind === "ok" ? <CheckCircle2 size={16} color="var(--ok)" /> : t.kind === "error" ? <ShieldAlert size={16} color="var(--signal)" /> : <Info size={16} color="var(--amber)" />}</span>
            <div><div className="label" style={{ color: t.kind === "error" ? "var(--signal)" : undefined }}>{t.kind === "error" ? "Rejected" : t.kind === "ok" ? "Done" : "Notice"}</div><div className="text-[13.5px] leading-snug">{t.msg}</div></div>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}
