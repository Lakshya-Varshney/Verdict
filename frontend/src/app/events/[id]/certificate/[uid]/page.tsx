"use client";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { FileDown, Printer, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { useEventCtx } from "@/components/EventContext";
import { Q, LoadingBlock } from "@/components/ui";
import { useAct } from "@/lib/act";
import { downloadBlob, fmtDate } from "@/lib/utils";
import { BRAND } from "@/lib/brand";

const KIND = { participant: "Certificate of Participation", judge: "Certificate of Service", winner: "Certificate of Achievement" } as const;

export default function CertificatePage() {
  const { event: e } = useEventCtx(); const { uid } = useParams<{ uid: string }>(); const act = useAct();
  const q = useQuery({ queryKey: ["cert", e.id, uid], queryFn: () => api.data.certificate(e.id, uid) });
  return (
    <Q q={q} skeleton={<LoadingBlock rows={3} />}>{(c) => {
      const file = async (fmt: "pdf" | "html") => { const b = await act(() => api.data.certificateFile(e.id, uid, fmt), fmt === "pdf" ? "PDF ready" : "Verifiable HTML ready"); if (b) downloadBlob(b, `${c.kind}-certificate-${c.verify_hash.slice(0, 8)}.${fmt}`); };
      return (
        <div>
          <div className="no-print mb-6 flex flex-wrap justify-end gap-2"><Link href={`/verify/${c.verify_hash}`} className="btn"><ShieldCheck size={14} /> Verify</Link><button className="btn" onClick={() => file("html")}><FileDown size={14} /> Verifiable HTML</button><button className="btn btn-primary" onClick={() => file("pdf")}><FileDown size={14} /> Signed PDF</button><button className="btn" onClick={() => window.print()}><Printer size={14} /> Print</button></div>
          <div className="mx-auto aspect-[1.414/1] w-full max-w-[1100px] p-3" style={{ background: "#f4ecd8", color: "#17130b", boxShadow: "0 40px 80px -40px rgba(0,0,0,.8)" }}>
            <div className="relative flex h-full flex-col items-center justify-between border-[3px] border-[#17130b] p-3"><div className="absolute inset-3 border border-[#17130b]/50" />
              <div className="relative z-10 flex h-full w-full flex-col items-center justify-between px-[6%] py-[4%] text-center">
                <div><div className="cond text-[clamp(1rem,2.2vw,1.6rem)] tracking-[0.3em]">{BRAND.name}</div><div className="mono mt-1 text-[clamp(.5rem,.9vw,.7rem)] uppercase tracking-[0.3em] opacity-60">{e.name}</div></div>
                <div><div className="mono text-[clamp(.55rem,1vw,.8rem)] uppercase tracking-[0.35em] opacity-70">{KIND[c.kind]}</div>
                  <div className="my-[3%] font-serif text-[clamp(2.4rem,7.5vw,6rem)] italic leading-none">{c.user_name}</div>
                  <p className="mx-auto max-w-[34rem] text-[clamp(.75rem,1.4vw,1.1rem)] leading-snug">{c.detail} at <b>{c.event_name}</b>, judged in the open with weighted rubrics and cross-judge normalisation.</p></div>
                <div className="flex w-full items-end justify-between">
                  <div className="text-left"><div className="mono text-[clamp(.45rem,.8vw,.62rem)] uppercase tracking-[0.2em] opacity-60">Issued</div><div className="text-[clamp(.7rem,1.2vw,.95rem)]">{fmtDate(c.issued_at)}</div></div>
                  <svg viewBox="0 0 100 100" className="h-[clamp(4rem,10vw,7.5rem)] w-[clamp(4rem,10vw,7.5rem)]"><circle cx="50" cy="50" r="46" fill="none" stroke="#17130b" strokeWidth="2" /><circle cx="50" cy="50" r="40" fill="none" stroke="#17130b" strokeWidth=".6" strokeDasharray="1.5 2.5" />
                    {Array.from({ length: 24 }).map((_, i) => { const a = (i / 24) * Math.PI * 2; return <line key={i} x1={50 + Math.cos(a) * 32} y1={50 + Math.sin(a) * 32} x2={50 + Math.cos(a) * 38} y2={50 + Math.sin(a) * 38} stroke="#17130b" strokeWidth="1" />; })}
                    <text x="50" y="58" textAnchor="middle" fontFamily="var(--font-serif)" fontStyle="italic" fontSize="30" fill="#17130b">V</text></svg>
                  <div className="text-right"><div className="mono text-[clamp(.45rem,.8vw,.62rem)] uppercase tracking-[0.2em] opacity-60">Verify</div>
                    <div className="mt-1"><span className="mono block max-w-[22ch] break-all text-[clamp(.45rem,.8vw,.62rem)]" data-testid="verify-code">{c.verify_hash}</span>
                      <span className="mono mt-1 block text-[clamp(.4rem,.7vw,.55rem)] opacity-60">{c.algorithm ?? "signed"} · key {c.key_id}</span></div></div>
                </div>
              </div>
            </div>
          </div>
        </div>
      );
    }}</Q>
  );
}
