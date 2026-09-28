"use client";
import Link from "next/link";
import { LogIn } from "lucide-react";
import { useAuth } from "@/lib/auth";
import { Skeleton } from "./ui";

/** Renders children only when signed in; otherwise a friendly prompt. */
export function NeedAuth({ children, what = "continue" }: { children: React.ReactNode; what?: string }) {
  const { authed, loading } = useAuth();
  if (loading) return <Skeleton className="h-64" />;
  if (!authed) return (
    <div className="panel ticks fade-up mx-auto max-w-lg p-10 text-center"><LogIn size={22} className="mx-auto mb-4 text-amberink" /><h2 className="display text-4xl">Sign in to {what}.</h2>
      <p className="mt-3 text-sm text-ink2">Your account holds your team and your drafts.</p>
      <div className="mt-6 flex justify-center gap-3"><Link className="btn btn-primary" href={`/login?next=${typeof window !== "undefined" ? encodeURIComponent(window.location.pathname) : "/"}`}>Sign in</Link><Link className="btn" href="/signup">Create account</Link></div></div>
  );
  return <>{children}</>;
}
