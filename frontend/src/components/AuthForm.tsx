"use client";
import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight } from "lucide-react";
import { ApiError, USE_MOCK } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { DEMO_ACCOUNTS, DEMO_PASSWORD } from "@/lib/mock/db";
import { Field } from "./ui";
import { FlapCycle } from "./SplitFlap";

export function AuthForm({ mode }: { mode: "login" | "signup" }) {
  const { login, signup } = useAuth(); const router = useRouter();
  const [name, setName] = useState(""); const [email, setEmail] = useState(""); const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null); const [busy, setBusy] = useState(false);
  const isLogin = mode === "login";

  const submit = async (e?: React.FormEvent, creds?: { email: string; password: string }) => {
    e?.preventDefault(); setBusy(true); setErr(null);
    try {
      if (isLogin || creds) await login(creds?.email ?? email, creds?.password ?? password); else await signup(name, email, password);
      const next = new URLSearchParams(window.location.search).get("next");
      router.push(next && next.startsWith("/") ? next : "/events");
    } catch (x) { setErr(x instanceof ApiError ? x.detail : "Could not reach the server."); setBusy(false); }
  };

  return (
    <div className="mx-auto grid max-w-5xl gap-10 lg:grid-cols-[1fr_1fr]">
      <div className="panel ticks fade-up p-8 sm:p-10">
        <div className="label mb-4 text-amberink">{isLogin ? "Access" : "Registration"}</div>
        <h1 className="display text-[3.4rem]">{isLogin ? <>Welcome <em>back.</em></> : <>Take a <em>seat.</em></>}</h1>
        <form className="mt-8 space-y-5" onSubmit={submit} noValidate>
          {!isLogin && <Field label="Full name"><input className="input" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" placeholder="Ada Lovelace" /></Field>}
          <Field label="Email"><input className="input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" placeholder="you@team.dev" /></Field>
          <Field label="Password" hint={!isLogin ? "8+ characters" : undefined}><input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={isLogin ? "current-password" : "new-password"} /></Field>
          {err && <div role="alert" className="border border-signal bg-[color-mix(in_srgb,var(--signal)_10%,transparent)] px-4 py-3 text-[13.5px] text-signal">{err}</div>}
          <button className="btn btn-primary w-full" disabled={busy}>{busy ? "One moment…" : isLogin ? "Sign in" : "Create account"} <ArrowRight size={14} /></button>
        </form>
        <p className="mt-6 text-[13.5px] text-ink2">{isLogin ? <>New here? <Link href="/signup" className="link-u text-amberink">Create an account</Link></> : <>Already registered? <Link href="/login" className="link-u text-amberink">Sign in</Link></>}</p>
      </div>
      <div className="fade-up space-y-6 self-center" style={{ ["--i" as string]: 2 } as React.CSSProperties}>
        <div className="boardframe"><FlapCycle words={["SUBMIT", "SCORE", "AUDIT", "PUBLISH"]} size={3.6} color="amber" /></div>
        {USE_MOCK && (
          <div className="panel p-5">
            <div className="label mb-3 text-amberink">Demo accounts · password “{DEMO_PASSWORD}”</div>
            <div className="grid gap-2 sm:grid-cols-2">
              {DEMO_ACCOUNTS.map((a) => (
                <button key={a.id} type="button" onClick={() => submit(undefined, { email: a.email, password: DEMO_PASSWORD })} className="border border-line px-3 py-2.5 text-left transition-colors hover:border-amber">
                  <span className="block text-[13.5px]">{a.name}</span><span className="label">{a.label} · one click</span>
                </button>
              ))}
            </div>
          </div>
        )}
        <p className="text-[13px] text-ink3">Roles are granted per event. Signing up makes you a participant anywhere — judging and organising are invitation-only.</p>
      </div>
    </div>
  );
}
