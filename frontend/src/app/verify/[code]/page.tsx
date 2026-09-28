"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { BadgeCheck, ShieldAlert } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { fmtDate } from "@/lib/utils";
import { ErrorState, LoadingBlock, PageHead } from "@/components/ui";

const KIND = { participant: "Certificate of Participation", judge: "Judge Participation Record", winner: "Certificate of Achievement" } as const;

/** Public page: anyone holding a certificate code can check it here, no account needed. */
export default function VerifyPage() {
  const { code } = useParams<{ code: string }>();
  const q = useQuery({ queryKey: ["verify", code], queryFn: () => api.data.verify(code), retry: false });
  if (q.isLoading) return <LoadingBlock rows={3} />;
  if (q.error instanceof ApiError && (q.error.status === 404 || q.error.status === 422))
    return <div className="mx-auto max-w-2xl"><PageHead kicker="Verification" title={<>No such <em>certificate.</em></>} sub="That code isn't on record here. Check it was copied completely." /></div>;
  if (q.error || !q.data) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  const v = q.data; const c = v.certificate;
  return (
    <div className="mx-auto max-w-3xl">
      <PageHead kicker="Verification" title={v.valid ? <>Signature <em>valid.</em></> : <>Signature <em>invalid.</em></>}
        sub={v.valid ? "This document was issued by this platform and has not been altered." : "The stored record does not match its digital signature. Do not trust this document."} />
      <div className="panel ticks p-8" data-testid="verify-result" data-valid={String(v.valid)}>
        <div className="mb-6 flex items-center gap-3">{v.valid ? <BadgeCheck size={28} className="text-ok" /> : <ShieldAlert size={28} className="text-signal" />}
          <span className={"label " + (v.valid ? "text-ok" : "text-signal")}>{v.valid ? "VALID" : "INVALID"} · {v.algorithm}</span></div>
        {c && (
          <dl className="grid gap-4 sm:grid-cols-2">
            <div><dt className="label">Document</dt><dd className="mt-1 text-lg">{KIND[c.kind as keyof typeof KIND] ?? c.kind}</dd></div>
            <div><dt className="label">Recipient</dt><dd className="mt-1 font-serif text-2xl italic">{c.recipient.name}</dd></div>
            <div><dt className="label">Event</dt><dd className="mt-1">{c.event.name}</dd></div>
            <div><dt className="label">Issued</dt><dd className="mt-1">{fmtDate(c.issued_at)}</dd></div>
            <div className="sm:col-span-2"><dt className="label">Detail</dt><dd className="mt-1 text-ink2">{c.detail}</dd></div>
          </dl>
        )}
        <div className="mt-8 border-t border-line pt-4 text-[12px] leading-relaxed text-ink3">
          <p className="mono break-all">code {v.verify_hash} · key {v.key_id}</p>
          <p className="mt-2">You don&apos;t have to trust this page: verify offline with the public key at <code>/.well-known/dogfood-signing-key</code> and <code>backend/scripts/verify_certificate.py</code> (Python standard library only).</p>
        </div>
      </div>
      <div className="mt-6"><Link href="/" className="btn btn-sm">Home</Link></div>
    </div>
  );
}
