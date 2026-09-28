"use client";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Minus, Plus, Eye } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth, isStaff } from "@/lib/auth";
import { useAct } from "@/lib/act";
import { fingerprint, hashStr, shuffleSeeded } from "@/lib/utils";
import { SplitFlap } from "@/components/SplitFlap";
import { SubmissionCard } from "@/components/SubmissionCard";
import { Empty, Field, PageHead, Q } from "@/components/ui";

interface Ballot { voted: string[]; votes: Record<string, number>; }

function Inner() {
  const { id } = useParams<{ id: string }>(); const { me, authed, roleFor } = useAuth(); const act = useAct(); const staff = isStaff(roleFor(id));
  const ev = useQuery({ queryKey: ["event", id], queryFn: () => api.events.get(id) });
  const gal = useQuery({ queryKey: ["gallery-all", id, false], queryFn: () => api.subs.gallery(id, { limit: 200 }) });
  const [fp, setFp] = useState(""); const [email, setEmail] = useState(""); const [ballot, setBallot] = useState<Ballot>({ voted: [], votes: {} });
  useEffect(() => setFp(fingerprint()), []);
  const voter = me?.user.id ?? fp; const key = `verdict.ballot.${id}.${voter}`;
  useEffect(() => { if (!voter) return; try { setBallot(JSON.parse(localStorage.getItem(key) ?? "null") ?? { voted: [], votes: {} }); } catch { setBallot({ voted: [], votes: {} }); } }, [key, voter]);
  const save = (b: Ballot) => { setBallot(b); try { localStorage.setItem(key, JSON.stringify(b)); } catch { /* ignore */ } };
  const qc = useQueryClient();
  const emailOk = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email) ? email : undefined;
  // Server-side ballot: per-session shuffled order + authoritative budget. Falls back to a local shuffle (mock mode).
  const bal = useQuery({ queryKey: ["ballot", id, me?.user.id ?? "anon", emailOk ?? ""], queryFn: () => api.vote.ballot(id, emailOk), retry: false });
  const order = bal.data?.items.map((i) => i.id);
  const items = useMemo(() => {
    const all = gal.data?.items ?? [];
    if (!order) return shuffleSeeded(all, hashStr(voter + id));
    const byId = new Map(all.map((s) => [s.id, s]));
    return order.map((x) => byId.get(x)).filter((s): s is NonNullable<typeof s> => !!s);
  }, [gal.data, order, voter, id]);
  const counts = useQueries({ queries: staff ? items.map((s) => ({ queryKey: ["votes", s.id, me?.user.id], queryFn: () => api.vote.count(s.id) })) : [] });
  const e = ev.data; if (!e) return null;
  const open = e.status === "voting"; const quad = e.voting_mode === "quadratic";
  const CREDITS = e.vote_credits ?? 25; const VOTES = e.votes_per_voter ?? 1;
  const mine = bal.data?.voter?.my_votes; const myN = (sid: string) => (mine ? mine[sid] ?? 0 : ballot.votes[sid] ?? 0);
  const spent = mine ? Object.values(mine).reduce((a, n) => a + n * n, 0) : Object.values(ballot.votes).reduce((a, n) => a + n * n, 0);
  const left = bal.data?.voter?.credits_left ?? CREDITS - spent; const votesLeft = bal.data?.voter?.votes_left ?? VOTES - ballot.voted.length;
  const refresh = () => qc.invalidateQueries({ queryKey: ["ballot", id] });
  const needAuth = (e.voting_mode === "auth" || quad) && !authed;

  const approve = async (sid: string) => {
    const r = await act(() => api.vote.cast(sid, { fingerprint: fp, email: e.voting_mode === "email" ? email : undefined }), "Vote counted");
    if (r) { save({ ...ballot, voted: [...ballot.voted, sid] }); refresh(); }
  };
  const setQ = async (sid: string, n: number) => {
    const r = await act(() => api.vote.cast(sid, { fingerprint: fp, votes: n }));
    if (r) { save({ ...ballot, votes: { ...ballot.votes, [sid]: n } }); refresh(); }
  };

  return (
    <div>
      <PageHead kicker="Public ballot" title={<>Pick what <em>deserves</em> it.</>} sub={quad ? `Quadratic voting: ${CREDITS} credits. n votes on one project cost n² credits — so spreading your voice beats shouting.` : `You get ${VOTES} vote${VOTES === 1 ? "" : "s"}. Order is shuffled per voter so nobody benefits from being first.`}
      />
      {!open && <div className="mb-8"><Empty title={e.status === "published" || e.status === "archived" ? "Voting has closed" : "Voting isn't open yet"} body={staff ? "Organiser preview — buttons are disabled until the event is in the voting stage." : "Come back when the window opens."} icon={<SplitFlap text="--" size={1.2} scramble={false} />} /></div>}
      {open && (
        <div className="panel ticks mb-8 flex flex-wrap items-center justify-between gap-6 p-6">
          <div className="flex items-center gap-5">{quad ? <><SplitFlap text={String(left).padStart(2, "0")} size={2.6} framed color={left < 5 ? "signal" : "amber"} scramble={false} /><div><div className="label">Credits left</div><div className="mt-1 text-[13px] text-ink3">{spent} spent of {CREDITS}</div></div></>
            : <><div className="flex gap-2">{Array.from({ length: VOTES }).map((_, i) => <i key={i} className="h-9 w-9 rounded-full border-2" style={{ borderColor: "var(--amber)", background: i < votesLeft ? "var(--amber)" : "transparent", boxShadow: i < votesLeft ? "0 0 16px var(--amber)" : undefined }} />)}</div><div><div className="label">Votes left</div></div></>}</div>
          {e.voting_mode === "email" && <div className="w-full max-w-sm"><Field label="Your email (required to vote)"><input className="input" type="email" value={email} onChange={(x) => setEmail(x.target.value)} placeholder="you@example.com" /></Field></div>}
          {needAuth && <div className="flex items-center gap-3 text-[13.5px] text-ink2">This ballot needs an account. <Link href={`/login?next=/events/${id}/vote`} className="btn btn-sm btn-primary">Sign in</Link></div>}
        </div>)}
      <Q q={gal}>
        {() => (
          <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {items.map((s, i) => {
              const n = myN(s.id); const has = mine ? n > 0 : ballot.voted.includes(s.id); const cost = (n + 1) ** 2 - n ** 2; const cnt = counts[i]?.data;
              return (
                <div key={s.id} className="flex flex-col"><SubmissionCard s={s} index={i} href={`/submissions/${s.id}`} /><div className="panel border-t-0 p-4">
                  <div className="space-y-3">
                    {quad ? (
                      <div className="flex items-center justify-between"><div className="flex items-center gap-3"><button className="btn btn-icon btn-sm" disabled={!open || needAuth || n === 0} onClick={() => setQ(s.id, n - 1)} aria-label="Fewer votes"><Minus size={13} /></button>
                        <span className="cond w-8 text-center text-4xl amber">{n}</span><button className="btn btn-icon btn-sm" disabled={!open || needAuth || cost > left} onClick={() => setQ(s.id, n + 1)} aria-label="More votes"><Plus size={13} /></button></div>
                        <span className="mono text-[11px] text-ink3">{n ** 2} credits{cost <= left ? ` · next +${cost}` : ""}</span></div>
                    ) : (
                      <button className={has ? "btn w-full" : "btn btn-primary w-full"} disabled={!open || needAuth || has || votesLeft < 1 || (e.voting_mode === "email" && !email)} onClick={() => approve(s.id)}>{has ? <><Check size={13} /> Voted</> : "Vote for this"}</button>)}
                    {staff && <div className="mono flex items-center gap-2 text-[10.5px] text-amberink"><Eye size={11} /> organiser eyes only: {cnt?.count ?? "…"}</div>}
                  </div></div></div>
              );
            })}
          </div>)}
      </Q>
    </div>
  );
}
export default function VotePage() { return <Inner />; }
