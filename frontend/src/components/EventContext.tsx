"use client";
import { createContext, useContext, type ReactNode } from "react";
import { ApiError } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { EventT, Role } from "@/lib/types";
import { Denied, ErrorState, LoadingBlock } from "./ui";

interface Ev { event: EventT; role: Role; }
export const EventCtx = createContext<Ev | null>(null);
export function useEventCtx() { const c = useContext(EventCtx); if (!c) throw new Error("useEventCtx outside event layout"); return c; }

/** UI-level courtesy gate. The real check is the API — this only saves people a dead end. */
export function Gate({ allow, what, children }: { allow: Role[]; what?: string; children: ReactNode }) {
  const { role } = useEventCtx(); const { authed, loading } = useAuth();
  if (loading) return <LoadingBlock />;
  if (role === "admin" || allow.includes(role)) {
    if (!authed && !allow.includes("visitor")) return <ErrorState error={new ApiError(401, "Sign in to use this screen.")} />;
    return <>{children}</>;
  }
  if (!authed && !allow.includes("visitor")) return <ErrorState error={new ApiError(401, "Sign in to use this screen.")} />;
  return <Denied need={allow.filter((r) => r !== "visitor").join(" / ")} what={what ?? `You're signed in as ${role} for this event.`} />;
}
