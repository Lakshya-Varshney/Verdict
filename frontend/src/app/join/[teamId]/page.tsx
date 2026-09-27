"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { UserPlus } from "lucide-react";
import { api } from "@/lib/api";
import { useAct } from "@/lib/act";
import { useAuth } from "@/lib/auth";
import { Avatar, ErrorState, LoadingBlock } from "@/components/ui";

export default function JoinPage() {
  const { teamId } = useParams<{ teamId: string }>(); const router = useRouter(); const qc = useQueryClient(); const act = useAct();
  const { authed, loading } = useAuth(); const [code, setCode] = useState(""); const [busy, setBusy] = useState(false);
  useEffect(() => { setCode(new URLSearchParams(window.location.search).get("code") ?? ""); }, []);
  useEffect(() => { if (!loading && !authed) router.replace(`/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`); }, [loading, authed, router]);
  const q = useQuery({ queryKey: ["team", teamId], queryFn: () => api.teams.get(teamId), enabled: authed });
  if (loading || !authed || q.isLoading) return <LoadingBlock rows={2} />;
  if (q.error || !q.data) return <ErrorState error={q.error} retry={() => q.refetch()} />;
  const t = q.data;
  const join = async () => { setBusy(true); const r = await act(() => api.teams.join(t.id, code), `Joined ${t.name}`); setBusy(false); if (r) { await qc.invalidateQueries(); router.push(`/events/${t.event_id}/team`); } };
  return (
    <div className="panel ticks fade-up mx-auto max-w-xl p-10 text-center">
      <UserPlus className="mx-auto mb-5 text-amberink" size={26} /><div className="label mb-3">You&apos;ve been invited to</div>
      <h1 className="display text-[4.2rem]">{t.name}</h1>
      <div className="mt-6 flex justify-center -space-x-2">{t.members.map((m) => <Avatar key={m.user_id} name={m.name} size={38} />)}</div>
      <p className="mt-3 text-[13.5px] text-ink3">{t.members.map((m) => m.name).join(", ")}</p>
      {!code && <p className="mt-6 text-signal text-sm">This link has no invite code. Ask your team lead for the full link.</p>}
      <button className="btn btn-primary mt-8" onClick={join} disabled={busy || !code}>{busy ? "Joining…" : "Join this team"}</button>
    </div>
  );
}
